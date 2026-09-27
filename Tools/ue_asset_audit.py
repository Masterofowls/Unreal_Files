#!/usr/bin/env python3
"""ue_asset_audit: find out which assets your selected levels really pull into a
packaged build, how big they are, why each one is included, and what is dead
weight, before the package overflows its size budget.

Workflow
  1. export   Dump the project's dependency graph once (launches the editor
              headless with Tools/ue_asset_audit_export.py).
  2. levels   List the maps found in the dump.
  3. analyze  Pick levels (plus optional config cook rules), follow hard and soft
              references, and report sizes, per-level cost, largest assets,
              unused assets, broken references and budget pass/fail.
  4. why      Print the reference chain that pulls a given asset into the build.

Only the Python 3.8+ standard library is needed. Examples are in Tools/README.md.

Exit codes: 0 ok, 1 usage/input error, 2 size budget exceeded,
            3 broken references found with --strict.
"""
import argparse
import csv
import fnmatch
import json
import os
import platform
import re
import subprocess
import sys
from collections import defaultdict, deque

SCHEMA = 1
PACKAGE_EXTENSIONS = (".uasset", ".umap")
COMPANION_EXTENSIONS = (".uexp", ".ubulk", ".uptnl", ".m.ubulk")
EXTERNAL_FOLDERS = ("__ExternalActors__", "__ExternalObjects__")
MAP_CLASSES = {"World"}

EXIT_OK, EXIT_ERROR, EXIT_BUDGET, EXIT_BROKEN = 0, 1, 2, 3


# --------------------------------------------------------------------------- utils

def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.2f %s" % (n, unit))
        n /= 1024.0
    return "%.2f GB" % n


def mb(n):
    return round(n / (1024.0 * 1024.0), 2)


def die(msg, code=EXIT_ERROR):
    print("error: " + msg, file=sys.stderr)
    sys.exit(code)


def to_package(object_path):
    """'/Game/Maps/L.L' or '/Game/BP.BP_C' -> '/Game/Maps/L'. Returns None for code paths."""
    if not object_path:
        return None
    p = object_path.strip()
    # Class refs sometimes look like  /Script/Engine.BlueprintGeneratedClass'/Game/X.X_C'
    m = re.search(r"'(/[^']+)'", p)
    p = m.group(1) if m else p.strip('"').strip("'")
    if not p.startswith("/") or p.startswith(("/Script/", "/Temp/", "/Memory/")) or p == "None":
        return None
    return p.split(".", 1)[0].split(":", 1)[0]


# --------------------------------------------------------------------------- graph

class Graph:
    def __init__(self, data):
        if data.get("schema") != SCHEMA:
            die("unsupported dump schema %r (expected %d); re-run 'export'" % (data.get("schema"), SCHEMA))
        self.project_dir = data.get("project_dir", "")
        self.project_name = data.get("project_name", "")
        self.engine_version = data.get("engine_version", "")
        self.mounts = data.get("mounts", {"/Game": "Content"})
        self.packages = data["packages"]
        self._lower = {p.lower(): p for p in self.packages}

    @classmethod
    def load(cls, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return cls(json.load(fh))
        except FileNotFoundError:
            die("dump not found: %s (run 'export' first)" % path)
        except json.JSONDecodeError as e:
            die("dump is not valid JSON: %s (%s)" % (path, e))

    def canonical(self, pkg):
        if pkg in self.packages:
            return pkg
        return self._lower.get(pkg.lower())

    def is_external(self, pkg):
        return any("/%s/" % f in pkg for f in EXTERNAL_FOLDERS)

    def maps(self):
        return sorted(p for p, d in self.packages.items()
                      if d.get("class") in MAP_CLASSES and not self.is_external(p))

    def mount_of(self, pkg):
        best = None
        for m in self.mounts:
            if pkg == m or pkg.startswith(m + "/"):
                if best is None or len(m) > len(best):
                    best = m
        return best

    def external_packages_for_map(self, map_pkg):
        """World Partition one-file-per-actor packages that belong to a map."""
        mount = self.mount_of(map_pkg) or "/" + map_pkg.strip("/").split("/")[0]
        rest = map_pkg[len(mount):]
        prefixes = tuple("%s/%s%s/" % (mount, f, rest) for f in EXTERNAL_FOLDERS)
        return sorted(p for p in self.packages if p.startswith(prefixes))

    def map_of_external(self, pkg):
        """'/Game/__ExternalActors__/Maps/L_Main/0/AB/X' -> '/Game/Maps/L_Main' (if that map exists)."""
        for f in EXTERNAL_FOLDERS:
            marker = "/%s/" % f
            if marker in pkg:
                mount, rest = pkg.split(marker, 1)
                parts = rest.split("/")
                for i in range(len(parts) - 1, 0, -1):
                    cand = self.canonical("%s/%s" % (mount, "/".join(parts[:i])))
                    if cand and cand in self.packages and self.packages[cand].get("class") in MAP_CLASSES:
                        return cand
        return None

    def packages_under(self, directory):
        d = directory.rstrip("/") + "/"
        return sorted(p for p in self.packages if p.startswith(d))


# --------------------------------------------------------------------------- config

def read_ini(path):
    """Minimal Unreal ini reader: returns [(section, op, key, value)] in order."""
    entries = []
    section = None
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith(";") or line.startswith("#"):
                    continue
                if line.startswith("[") and "]" in line:
                    section = line[1:line.index("]")]
                    continue
                op = ""
                if line[0] in "+-.!":
                    op, line = line[0], line[1:]
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                entries.append((section, op, key.strip(), value.strip()))
    except FileNotFoundError:
        pass
    return entries


def config_rules(project_dir):
    """Cook roots and exclusions defined by the project's config files."""
    cfg = os.path.join(project_dir, "Config")
    engine = read_ini(os.path.join(cfg, "DefaultEngine.ini"))
    game = read_ini(os.path.join(cfg, "DefaultGame.ini"))
    rules = {"maps": [], "packages": [], "always_dirs": [], "never_dirs": [],
             "cook_all": False, "notes": []}

    for section, _op, key, value in engine:
        if section == "/Script/EngineSettings.GameMapsSettings" and key in (
                "GameDefaultMap", "TransitionMap", "ServerDefaultMap",
                "GlobalDefaultGameMode", "GlobalDefaultServerGameMode", "GameInstanceClass"):
            pkg = to_package(value)
            if pkg:
                (rules["maps"] if key.endswith("Map") else rules["packages"]).append(pkg)

    def apply(target, op, item):
        if op == "!":            # e.g. !MapsToCook=ClearArray
            target.clear()
        elif item is None:
            return
        elif op == "-":
            if item in target:
                target.remove(item)
        elif item not in target:
            target.append(item)

    map_type_dirs = None
    for section, op, key, value in game:
        if section == "/Script/UnrealEd.ProjectPackagingSettings":
            if key == "MapsToCook":
                m = re.search(r'FilePath\s*=\s*"([^"]+)"', value)
                apply(rules["maps"], op, to_package(m.group(1)) if m else None)
            elif key in ("DirectoriesToAlwaysCook", "DirectoriesToNeverCook"):
                m = re.search(r'Path\s*=\s*"([^"]+)"', value)
                target = rules["always_dirs"] if key == "DirectoriesToAlwaysCook" else rules["never_dirs"]
                apply(target, op, m.group(1).rstrip("/") if m else None)
            elif key == "bCookAll" and value.lower() == "true":
                rules["cook_all"] = True
        elif section == "/Script/Engine.AssetManagerSettings" and key == "PrimaryAssetTypesToScan":
            dirs = [d.rstrip("/") for d in re.findall(r'Path\s*=\s*"([^"]+)"', value)]
            if re.search(r"CookRule\s*=\s*AlwaysCook", value):
                for d in dirs:
                    apply(rules["always_dirs"], "+", d)
            if re.search(r'PrimaryAssetType\s*=\s*"?Map"?\s*[,)]', value):
                map_type_dirs = dirs

    if not rules["maps"]:
        rules["notes"].append(
            "MapsToCook is empty: unless you pass -map= to the cook, the cooker may cook every map the "
            "Asset Manager 'Map' type finds (%s). List your shipping maps explicitly (see --ini-snippet)."
            % (", ".join(map_type_dirs) if map_type_dirs else "/Game/Maps by default"))

    if rules["cook_all"]:
        rules["notes"].append("bCookAll=True: EVERYTHING in the project is cooked, whatever the levels reference.")
    for k in ("maps", "packages", "always_dirs", "never_dirs"):
        rules[k] = list(dict.fromkeys(rules[k]))  # de-duplicate, keep order
    return rules


# --------------------------------------------------------------------------- cooked output

class Cooked:
    """Sizes of cooked packages under Saved/Cooked/<Platform>."""

    def __init__(self, platform_dir, graph):
        self.root = platform_dir
        self.graph = graph
        self.sizes = {}          # package -> bytes
        self.other_bytes = 0     # shader libraries, registry, etc.
        self.other_files = []
        self._scan()

    def _mount_dirs(self):
        out = []
        proj = self.graph.project_name
        for mount, rel in self.graph.mounts.items():
            out.append((mount, os.path.join(self.root, proj, rel)))
        out.append(("/Engine", os.path.join(self.root, "Engine", "Content")))
        return out

    def _scan(self):
        if not os.path.isdir(self.root):
            die("cooked dir not found: %s (expected Saved/Cooked/<Platform>)" % self.root)
        claimed = set()
        for mount, abs_dir in self._mount_dirs():
            if not os.path.isdir(abs_dir):
                continue
            for root, _dirs, files in os.walk(abs_dir):
                groups = defaultdict(int)
                for f in files:
                    full = os.path.join(root, f)
                    base = f
                    for ext in (".m.ubulk",) + PACKAGE_EXTENSIONS + COMPANION_EXTENSIONS:
                        if f.lower().endswith(ext):
                            base = f[: -len(ext)]
                            break
                    else:
                        continue
                    try:
                        groups[base] += os.path.getsize(full)
                    except OSError:
                        continue
                    claimed.add(os.path.normpath(full))
                rel_dir = os.path.relpath(root, abs_dir).replace("\\", "/")
                for base, size in groups.items():
                    rel = base if rel_dir == "." else rel_dir + "/" + base
                    self.sizes[mount + "/" + rel] = self.sizes.get(mount + "/" + rel, 0) + size
        for root, _dirs, files in os.walk(self.root):
            for f in files:
                full = os.path.normpath(os.path.join(root, f))
                if full in claimed:
                    continue
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                self.other_bytes += size
                self.other_files.append((os.path.relpath(full, self.root).replace("\\", "/"), size))
        self.other_files.sort(key=lambda x: -x[1])


# --------------------------------------------------------------------------- traversal

class Walk:
    """BFS over the dependency graph from a set of roots.

    Phase 1 follows hard references only (what must load). Phase 2, when soft
    references are followed, continues from everything reached so far over hard
    and soft edges; packages first reached there are "soft-only".
    """

    def __init__(self, graph, roots, follow_soft=True, never_dirs=()):
        self.graph = graph
        self.never = tuple(d.rstrip("/") + "/" for d in never_dirs)
        self.parent = {}                  # pkg -> (parent pkg or None, "root" | "hard" | "soft")
        self.missing = defaultdict(set)   # referenced project package not in the dump -> referencers
        self.blocked = defaultdict(set)   # referenced package in a never-cook folder -> referencers
        self.external = defaultdict(set)  # engine / engine-plugin content -> referencers

        self.hard_reach = set()
        queue = deque()
        for r in roots:
            c = graph.canonical(r)
            if c is None:
                self.missing[r].add("<root>")
            elif c not in self.hard_reach:
                self.hard_reach.add(c)
                self.parent[c] = (None, "root")
                queue.append(c)
        self._bfs(queue, self.hard_reach, soft=False)

        self.reach = set(self.hard_reach)
        if follow_soft:
            self._bfs(deque(sorted(self.hard_reach)), self.reach, soft=True)
        self.soft_only = self.reach - self.hard_reach

    def _bfs(self, queue, visited, soft):
        while queue:
            pkg = queue.popleft()
            node = self.graph.packages.get(pkg, {})
            edges = [(d, "hard") for d in node.get("hard", [])]
            if soft:
                edges += [(d, "soft") for d in node.get("soft", [])]
            for dep, kind in edges:
                c = self.graph.canonical(dep)
                if c is None:
                    mount = "/" + dep.strip("/").split("/")[0]
                    if mount == "/Engine" or mount not in self.graph.mounts:
                        self.external[dep].add(pkg)
                    else:
                        self.missing[dep].add(pkg)
                    continue
                if self.never and c.startswith(self.never):
                    self.blocked[c].add(pkg)
                    continue
                if c not in visited:
                    visited.add(c)
                    self.parent.setdefault(c, (pkg, kind))
                    queue.append(c)

    def chain(self, pkg):
        out, cur, seen = [], self.graph.canonical(pkg) or pkg, set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            parent, kind = self.parent.get(cur, (None, "?"))
            out.append((cur, kind))
            cur = parent
        return list(reversed(out))


def format_chain(chain, graph=None):
    parts = []
    for i, (pkg, kind) in enumerate(chain):
        name = pkg.rsplit("/", 1)[-1]
        owner = graph.map_of_external(pkg) if graph is not None else None
        if owner:
            name = "%s[actor %s]" % (owner.rsplit("/", 1)[-1], name)
        parts.append(name if i == 0 else ("-> %s%s" % (name, " (soft)" if kind == "soft" else "")))
    return " ".join(parts)


# --------------------------------------------------------------------------- level selection

def resolve_levels(graph, specs):
    maps = graph.maps()
    by_short = defaultdict(list)
    for m in maps:
        by_short[m.rsplit("/", 1)[-1].lower()].append(m)
    out, errors = [], []
    for spec in specs:
        pkg = to_package(spec) or spec
        if any(ch in spec for ch in "*?["):
            hits = [m for m in maps if fnmatch.fnmatchcase(m.lower(), spec.lower())]
            if not hits:
                errors.append("no map matches pattern %r" % spec)
            out.extend(hits)
            continue
        c = graph.canonical(pkg)
        if c and c in maps:
            out.append(c)
            continue
        hits = by_short.get(spec.lower(), [])
        if len(hits) == 1:
            out.append(hits[0])
        elif len(hits) > 1:
            errors.append("%r is ambiguous: %s (use the full /Game/... path)" % (spec, ", ".join(hits)))
        else:
            errors.append("map not found: %r (see 'levels')" % spec)
    return list(dict.fromkeys(out)), errors


def level_roots(graph, level):
    return [level] + graph.external_packages_for_map(level)


# --------------------------------------------------------------------------- analysis

def analyze(graph, args):
    levels, errors = resolve_levels(graph, args.levels or [])
    for e in errors:
        print("error: " + e, file=sys.stderr)
    if errors:
        sys.exit(EXIT_ERROR)

    project_dir = args.project_dir or graph.project_dir
    rules = config_rules(project_dir) if (args.from_config or args.never_cook_from_config) else None

    roots, root_reason = [], {}

    def add_root(pkg, reason):
        c = graph.canonical(pkg)
        if c is None:
            roots.append(pkg)
            root_reason.setdefault(pkg, reason)
            return
        if c not in root_reason:
            roots.append(c)
            root_reason[c] = reason

    for lvl in levels:
        for p in level_roots(graph, lvl):
            add_root(p, "level " + lvl.rsplit("/", 1)[-1])
    if args.from_config and rules:
        for m in rules["maps"]:
            c = graph.canonical(m)
            if c:
                for p in level_roots(graph, c):
                    add_root(p, "config map")
            else:
                add_root(m, "config map")
        for p in rules["packages"]:
            add_root(p, "config class")
        for d in rules["always_dirs"]:
            for p in graph.packages_under(d):
                add_root(p, "always-cook dir " + d)
    for r in args.extra_root or []:
        if graph.canonical(r):
            add_root(r, "--extra-root")
        else:
            under = graph.packages_under(r)
            if not under:
                print("warning: --extra-root %s matched nothing" % r, file=sys.stderr)
            for p in under:
                add_root(p, "--extra-root " + r)

    if not roots:
        die("nothing selected: pass --levels and/or --from-config (see 'levels')")

    never = list(args.never_cook or [])
    if rules and (args.never_cook_from_config or args.from_config):
        never += rules["never_dirs"]
    follow_soft = args.soft != "ignore"

    walk = Walk(graph, roots, follow_soft=follow_soft, never_dirs=never)

    cooked = Cooked(args.cooked_dir, graph) if args.cooked_dir else None
    use_cooked = args.size == "cooked"
    if use_cooked and not cooked:
        die("--size cooked needs --cooked-dir")

    def size_of(pkg):
        if use_cooked:
            return cooked.sizes.get(pkg, 0)
        return graph.packages.get(pkg, {}).get("size", 0)

    # Per-level closures (same traversal settings, level roots only).
    per_level = []
    closures = {}
    for lvl in levels:
        w = Walk(graph, level_roots(graph, lvl), follow_soft=follow_soft, never_dirs=never)
        closures[lvl] = w.reach
    for lvl in levels:
        others = set().union(*(closures[o] for o in levels if o != lvl)) if len(levels) > 1 else set()
        uniq = closures[lvl] - others
        per_level.append({
            "level": lvl,
            "external_actor_packages": len(graph.external_packages_for_map(lvl)),
            "packages": len(closures[lvl]),
            "bytes": sum(size_of(p) for p in closures[lvl]),
            "unique_packages": len(uniq),
            "unique_bytes": sum(size_of(p) for p in uniq),
        })

    reach = walk.reach
    total = sum(size_of(p) for p in reach)
    soft_only_bytes = sum(size_of(p) for p in walk.soft_only)

    by_class = defaultdict(lambda: [0, 0])
    by_folder = defaultdict(lambda: [0, 0])
    for p in reach:
        s = size_of(p)
        cls = graph.packages[p].get("class") or "(unknown)"
        by_class[cls][0] += 1
        by_class[cls][1] += s
        parts = p.strip("/").split("/")
        folder = "/" + "/".join(parts[: max(1, min(args.group_depth, len(parts) - 1))])
        by_folder[folder][0] += 1
        by_folder[folder][1] += s

    assets = []
    for p in reach:
        assets.append({
            "package": p,
            "class": graph.packages[p].get("class", ""),
            "bytes": size_of(p),
            "source_bytes": graph.packages[p].get("size", 0),
            "cooked_bytes": cooked.sizes.get(p) if cooked else None,
            "soft_only": p in walk.soft_only,
            "levels": [l for l in levels if p in closures[l]],
            "root_reason": root_reason.get(p, ""),
            "why": format_chain(walk.chain(p), graph),
        })
    assets.sort(key=lambda a: -a["bytes"])

    # Unused: project content that nothing selected reaches.
    project_mounts = tuple(m + "/" for m in graph.mounts)
    unused = []
    for p, d in graph.packages.items():
        if p in reach or not p.startswith(project_mounts):
            continue
        unused.append({"package": p, "class": d.get("class", ""), "bytes": d.get("size", 0)})
    unused.sort(key=lambda a: -a["bytes"])
    unused_by_folder = defaultdict(lambda: [0, 0])
    for u in unused:
        parts = u["package"].strip("/").split("/")
        folder = "/" + "/".join(parts[: max(1, min(args.group_depth, len(parts) - 1))])
        unused_by_folder[folder][0] += 1
        unused_by_folder[folder][1] += u["bytes"]

    cooked_report = None
    if cooked:
        cooked_pkgs = set(cooked.sizes)
        not_needed = sorted(((p, cooked.sizes[p]) for p in cooked_pkgs - reach
                             if not p.startswith("/Engine/")), key=lambda x: -x[1])
        reachable_not_cooked = sorted(p for p in reach if p not in cooked_pkgs)
        cooked_report = {
            "cooked_packages": len(cooked_pkgs),
            "cooked_package_bytes": sum(cooked.sizes.values()),
            "other_cooked_bytes": cooked.other_bytes,
            "largest_other_files": cooked.other_files[:15],
            "cooked_but_not_needed": not_needed,
            "cooked_but_not_needed_bytes": sum(s for _p, s in not_needed),
            "reachable_but_not_cooked": reachable_not_cooked,
        }

    report = {
        "project": graph.project_name,
        "engine_version": graph.engine_version,
        "size_basis": "cooked" if use_cooked else "source (uncooked editor files)",
        "levels": levels,
        "roots": len(roots),
        "follow_soft": follow_soft,
        "never_cook_dirs": never,
        "config": rules,
        "total_packages": len(reach),
        "total_bytes": total,
        "hard_packages": len(walk.hard_reach),
        "soft_only_packages": len(walk.soft_only),
        "soft_only_bytes": soft_only_bytes,
        "per_level": per_level,
        "by_class": sorted(([k, v[0], v[1]] for k, v in by_class.items()), key=lambda x: -x[2]),
        "by_folder": sorted(([k, v[0], v[1]] for k, v in by_folder.items()), key=lambda x: -x[2]),
        "assets": assets,
        "unused_packages": len(unused),
        "unused_bytes": sum(u["bytes"] for u in unused),
        "unused_by_folder": sorted(([k, v[0], v[1]] for k, v in unused_by_folder.items()), key=lambda x: -x[2]),
        "unused": unused,
        "missing": {k: sorted(v) for k, v in sorted(walk.missing.items())},
        "blocked_by_never_cook": {k: sorted(v) for k, v in sorted(walk.blocked.items())},
        "external_refs": {k: sorted(v) for k, v in sorted(walk.external.items())},
        "cooked": cooked_report,
    }
    return report


# --------------------------------------------------------------------------- output

def print_table(rows, headers, out):
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out.write(line + "\n" + "  ".join("-" * w for w in widths) + "\n")
    for r in rows:
        out.write("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) + "\n")


def print_summary(rep, args, out=None):
    out = out or sys.stdout
    w = out.write
    w("\n=== ue_asset_audit: %s %s ===\n" % (rep["project"], ("(UE %s)" % rep["engine_version"]) if rep["engine_version"] else ""))
    w("Size basis: %s%s\n" % (rep["size_basis"], "" if rep["follow_soft"] else "   [soft references IGNORED]"))
    w("Levels: %s\n" % (", ".join(l.rsplit("/", 1)[-1] for l in rep["levels"]) or "(none, config roots only)"))
    if rep["config"]:
        for n in rep["config"]["notes"]:
            w("NOTE: %s\n" % n)
    w("\nTOTAL: %d packages, %s  (hard %d, soft-only %d = %s)\n" % (
        rep["total_packages"], fmt_size(rep["total_bytes"]), rep["hard_packages"],
        rep["soft_only_packages"], fmt_size(rep["soft_only_bytes"])))
    if args.budget_mb is not None:
        ok = rep["total_bytes"] <= args.budget_mb * 1024 * 1024
        w("BUDGET: %s of %s MB -> %s\n" % (fmt_size(rep["total_bytes"]), args.budget_mb, "OK" if ok else "EXCEEDED"))

    w("\nPer level:\n")
    rows = []
    for l in rep["per_level"]:
        over = ""
        if args.level_budget_mb is not None and l["bytes"] > args.level_budget_mb * 1024 * 1024:
            over = "OVER"
        rows.append([l["level"].rsplit("/", 1)[-1], l["packages"], fmt_size(l["bytes"]),
                     l["unique_packages"], fmt_size(l["unique_bytes"]), l["external_actor_packages"], over])
    print_table(rows, ["level", "pkgs", "size", "unique pkgs", "unique size", "ext. actors", ""], out)

    w("\nBy asset class (top %d):\n" % args.top_groups)
    print_table([[c, n, fmt_size(s)] for c, n, s in rep["by_class"][: args.top_groups]], ["class", "pkgs", "size"], out)
    w("\nBy folder (depth %d, top %d):\n" % (args.group_depth, args.top_groups))
    print_table([[f, n, fmt_size(s)] for f, n, s in rep["by_folder"][: args.top_groups]], ["folder", "pkgs", "size"], out)

    w("\nLargest included assets (top %d) and why they're included:\n" % args.top)
    print_table([[fmt_size(a["bytes"]), a["class"], a["package"] + (" [soft]" if a["soft_only"] else ""), a["why"]]
                 for a in rep["assets"][: args.top]], ["size", "class", "package", "reference chain"], out)

    w("\nUNUSED by the selection: %d packages, %s (source size). Largest folders:\n" % (
        rep["unused_packages"], fmt_size(rep["unused_bytes"])))
    print_table([[f, n, fmt_size(s)] for f, n, s in rep["unused_by_folder"][: args.top_groups]], ["folder", "pkgs", "size"], out)

    if rep["missing"]:
        w("\nBROKEN references (%d): referenced packages that don't exist:\n" % len(rep["missing"]))
        for k, v in list(rep["missing"].items())[:30]:
            w("  %s  <- %s\n" % (k, ", ".join(x.rsplit("/", 1)[-1] for x in v[:5])))
    if rep["blocked_by_never_cook"]:
        w("\nReferenced but in DirectoriesToNeverCook (%d) - will be missing at runtime:\n" % len(rep["blocked_by_never_cook"]))
        for k, v in list(rep["blocked_by_never_cook"].items())[:30]:
            w("  %s  <- %s\n" % (k, ", ".join(x.rsplit("/", 1)[-1] for x in v[:5])))
    if rep["external_refs"]:
        w("\nEngine / engine-plugin content referenced: %d packages (sizes not in the dump; use --cooked-dir to see them).\n"
          % len(rep["external_refs"]))

    c = rep["cooked"]
    if c:
        w("\nCOOKED OUTPUT (%s):\n" % args.cooked_dir)
        w("  cooked packages: %d, %s   other cooked files (shaders, registry, engine plugins...): %s\n" % (
            c["cooked_packages"], fmt_size(c["cooked_package_bytes"]), fmt_size(c["other_cooked_bytes"])))
        w("  cooked but NOT needed by the selection: %d packages, %s  <- size you can remove\n" % (
            len(c["cooked_but_not_needed"]), fmt_size(c["cooked_but_not_needed_bytes"])))
        for p, s in c["cooked_but_not_needed"][:15]:
            w("    %10s  %s\n" % (fmt_size(s), p))
        if c["reachable_but_not_cooked"]:
            w("  reachable but not in the cooked output: %d (editor-only references, or the cook is stale)\n"
              % len(c["reachable_but_not_cooked"]))
    w("\nSizes are before pak/IoStore compression. Oodle usually shrinks the final package noticeably,\n"
      "so use a cooked-size budget with margin, and confirm with the staged build.\n")


def write_outputs(rep, args):
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1)
        print("wrote " + args.json)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            wr.writerow(["package", "class", "size_mb", "source_mb", "cooked_mb", "soft_only", "levels", "root_reason", "why"])
            for a in rep["assets"]:
                wr.writerow([a["package"], a["class"], mb(a["bytes"]), mb(a["source_bytes"]),
                             "" if a["cooked_bytes"] is None else mb(a["cooked_bytes"]),
                             a["soft_only"], ";".join(l.rsplit("/", 1)[-1] for l in a["levels"]),
                             a["root_reason"], a["why"]])
        print("wrote " + args.csv)
    if args.unused_csv:
        with open(args.unused_csv, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            wr.writerow(["package", "class", "size_mb"])
            for u in rep["unused"]:
                wr.writerow([u["package"], u["class"], mb(u["bytes"])])
        print("wrote " + args.unused_csv)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            write_markdown(rep, args, fh)
        print("wrote " + args.md)
    if args.ini_snippet:
        with open(args.ini_snippet, "w", encoding="utf-8") as fh:
            write_ini_snippet(rep, args, fh)
        print("wrote " + args.ini_snippet)


def write_markdown(rep, args, fh):
    w = fh.write
    w("# Asset audit: %s\n\n" % rep["project"])
    w("- Size basis: %s\n- Levels: %s\n- Soft references followed: %s\n" % (
        rep["size_basis"], ", ".join("`%s`" % l for l in rep["levels"]) or "none", rep["follow_soft"]))
    w("- **Total: %d packages, %s** (soft-only: %d, %s)\n" % (
        rep["total_packages"], fmt_size(rep["total_bytes"]), rep["soft_only_packages"], fmt_size(rep["soft_only_bytes"])))
    w("- Unused by selection: %d packages, %s\n\n" % (rep["unused_packages"], fmt_size(rep["unused_bytes"])))
    w("## Per level\n\n| Level | Packages | Size | Unique packages | Unique size |\n|---|---|---|---|---|\n")
    for l in rep["per_level"]:
        w("| `%s` | %d | %s | %d | %s |\n" % (l["level"], l["packages"], fmt_size(l["bytes"]),
                                             l["unique_packages"], fmt_size(l["unique_bytes"])))
    w("\n## By class\n\n| Class | Packages | Size |\n|---|---|---|\n")
    for c, n, s in rep["by_class"][: args.top_groups]:
        w("| %s | %d | %s |\n" % (c, n, fmt_size(s)))
    w("\n## By folder\n\n| Folder | Packages | Size |\n|---|---|---|\n")
    for f, n, s in rep["by_folder"][: args.top_groups]:
        w("| `%s` | %d | %s |\n" % (f, n, fmt_size(s)))
    w("\n## Largest included assets\n\n| Size | Class | Package | Reference chain |\n|---|---|---|---|\n")
    for a in rep["assets"][: args.top]:
        w("| %s | %s | `%s`%s | %s |\n" % (fmt_size(a["bytes"]), a["class"], a["package"],
                                        " (soft)" if a["soft_only"] else "", a["why"]))
    w("\n## Unused folders\n\n| Folder | Packages | Size |\n|---|---|---|\n")
    for f, n, s in rep["unused_by_folder"][: args.top_groups]:
        w("| `%s` | %d | %s |\n" % (f, n, fmt_size(s)))
    if rep["missing"]:
        w("\n## Broken references\n\n")
        for k, v in rep["missing"].items():
            w("- `%s` referenced by %s\n" % (k, ", ".join("`%s`" % x for x in v[:5])))
    if rep["cooked"]:
        c = rep["cooked"]
        w("\n## Cooked but not needed (%d, %s)\n\n" % (len(c["cooked_but_not_needed"]), fmt_size(c["cooked_but_not_needed_bytes"])))
        for p, s in c["cooked_but_not_needed"][: args.top]:
            w("- %s `%s`\n" % (fmt_size(s), p))


def write_ini_snippet(rep, args, fh):
    w = fh.write
    w("; Generated by Tools/ue_asset_audit.py. Review before merging into Config/DefaultGame.ini.\n")
    w("[/Script/UnrealEd.ProjectPackagingSettings]\n")
    w("; Cook exactly the audited levels (otherwise the cooker may cook every map it finds).\n")
    w("!MapsToCook=ClearArray\n")
    for l in rep["levels"]:
        w('+MapsToCook=(FilePath="%s")\n' % l)
    w("; Candidate folders that nothing in the selection uses (largest first).\n")
    w("; Only uncomment after checking nothing loads them by string path at runtime.\n")
    for f, n, s in rep["unused_by_folder"][: args.top_groups]:
        if s <= 0:
            continue
        w(';+DirectoriesToNeverCook=(Path="%s")   ; %d packages, %s unused\n' % (f, n, fmt_size(s)))


# --------------------------------------------------------------------------- commands

def cmd_export(args):
    uproject = os.path.abspath(args.project)
    if not uproject.endswith(".uproject") or not os.path.isfile(uproject):
        die("--project must point to an existing .uproject file")
    editor = args.editor_cmd
    if not editor:
        if not args.engine:
            die("pass --engine <UE root> or --editor-cmd <path to UnrealEditor-Cmd>")
        system = platform.system()
        if system == "Windows":
            editor = os.path.join(args.engine, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
        elif system == "Darwin":
            editor = os.path.join(args.engine, "Engine", "Binaries", "Mac", "UnrealEditor-Cmd")
        else:
            editor = os.path.join(args.engine, "Engine", "Binaries", "Linux", "UnrealEditor-Cmd")
    out = os.path.abspath(args.out)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ue_asset_audit_export.py")
    cmd = [editor, uproject, "-run=pythonscript", "-script=%s" % script.replace("\\", "/"),
           "-EnablePlugins=PythonScriptPlugin", "-unattended", "-nop4", "-nosplash", "-NullRHI", "-stdout",
           "-FullStdOutLogOutput"]
    env = dict(os.environ, UE_ASSET_AUDIT_OUT=out)
    print("running: " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    print("output:  " + out)
    if args.dry_run:
        return EXIT_OK
    if not os.path.isfile(editor):
        die("editor not found: %s" % editor)
    if os.path.exists(out):
        os.remove(out)
    rc = subprocess.call(cmd, env=env)
    if not os.path.isfile(out):
        die("the editor finished (exit %d) but wrote no dump. Check that the Python Editor Script "
            "Plugin is enabled and read the log above." % rc)
    g = Graph.load(out)
    print("exported %d packages, %d maps" % (len(g.packages), len(g.maps())))
    return EXIT_OK


def cmd_levels(args):
    g = Graph.load(args.dump)
    rows = []
    for m in g.maps():
        ext = g.external_packages_for_map(m)
        row = [m, len(ext), fmt_size(g.packages[m].get("size", 0) + sum(g.packages[p].get("size", 0) for p in ext))]
        if args.closure:
            w = Walk(g, level_roots(g, m), follow_soft=not args.hard_only)
            row.append(fmt_size(sum(g.packages[p].get("size", 0) for p in w.reach)))
        rows.append(row)
    headers = ["map", "ext. actors", "map size"] + (["closure size"] if args.closure else [])
    print_table(rows, headers, sys.stdout)
    print("\n%d maps" % len(rows))
    return EXIT_OK


def cmd_analyze(args):
    g = Graph.load(args.dump)
    rep = analyze(g, args)
    print_summary(rep, args)
    write_outputs(rep, args)
    code = EXIT_OK
    if args.strict and (rep["missing"] or rep["blocked_by_never_cook"]):
        print("\nFAIL: broken references (--strict)", file=sys.stderr)
        code = EXIT_BROKEN
    over_total = args.budget_mb is not None and rep["total_bytes"] > args.budget_mb * 1024 * 1024
    over_level = args.level_budget_mb is not None and any(
        l["bytes"] > args.level_budget_mb * 1024 * 1024 for l in rep["per_level"])
    if over_total or over_level:
        print("\nFAIL: size budget exceeded", file=sys.stderr)
        code = EXIT_BUDGET
    return code


def cmd_why(args):
    g = Graph.load(args.dump)
    levels, errors = resolve_levels(g, args.levels or [])
    if errors:
        die("; ".join(errors))
    roots = [p for l in levels for p in level_roots(g, l)]
    if args.from_config:
        rules = config_rules(args.project_dir or g.project_dir)
        roots += [p for m in rules["maps"] if g.canonical(m) for p in level_roots(g, g.canonical(m))]
        roots += rules["packages"] + [p for d in rules["always_dirs"] for p in g.packages_under(d)]
    if not roots:
        die("nothing selected: pass --levels and/or --from-config")
    walk = Walk(g, roots, follow_soft=args.soft != "ignore")
    code = EXIT_OK
    for asset in args.asset:
        pkg = g.canonical(to_package(asset) or asset)
        if pkg is None:
            print("%s: not in the dump" % asset)
            code = EXIT_ERROR
        elif pkg not in walk.reach:
            print("%s: NOT included by this selection" % pkg)
        else:
            print("%s  (%s)%s" % (pkg, fmt_size(g.packages[pkg].get("size", 0)),
                                  " [only via soft references]" if pkg in walk.soft_only else ""))
            for p, kind in walk.chain(pkg):
                owner = g.map_of_external(p)
                print("    %-6s %s%s" % (kind, p, ("   (actor in %s)" % owner) if owner else ""))
    return code


def build_parser():
    ap = argparse.ArgumentParser(prog="ue_asset_audit", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="dump the dependency graph via a headless editor run")
    e.add_argument("--project", required=True, help="path to <Game>.uproject")
    e.add_argument("--engine", help="Unreal Engine root folder (contains Engine/)")
    e.add_argument("--editor-cmd", help="explicit path to UnrealEditor-Cmd")
    e.add_argument("--out", default="asset_deps.json", help="output JSON (default: asset_deps.json)")
    e.add_argument("--dry-run", action="store_true", help="print the command without running it")
    e.set_defaults(func=cmd_export)

    l = sub.add_parser("levels", help="list maps in a dump")
    l.add_argument("dump")
    l.add_argument("--closure", action="store_true", help="also compute each map's full dependency size")
    l.add_argument("--hard-only", action="store_true", help="with --closure: ignore soft references")
    l.set_defaults(func=cmd_levels)

    def selection(p):
        p.add_argument("dump", help="JSON written by 'export'")
        p.add_argument("--levels", nargs="+", metavar="MAP",
                       help="maps: /Game/Maps/L_Main, L_Main (short name) or a pattern like '/Game/Maps/*'")
        p.add_argument("--from-config", action="store_true",
                       help="also add cook roots from Config/*.ini (MapsToCook, default maps, game mode, "
                            "DirectoriesToAlwaysCook, Asset Manager AlwaysCook) and honor DirectoriesToNeverCook")
        p.add_argument("--project-dir", help="project folder for --from-config (default: from the dump)")
        p.add_argument("--soft", choices=["follow", "ignore"], default="follow",
                       help="follow soft references like the cooker does (default) or ignore them")

    a = sub.add_parser("analyze", help="size report for selected levels")
    selection(a)
    a.add_argument("--extra-root", nargs="+", metavar="PKG_OR_DIR",
                   help="extra packages or folders loaded by code/string paths (e.g. /Game/UI)")
    a.add_argument("--never-cook", nargs="+", metavar="DIR", help="treat folders as never cooked")
    a.add_argument("--never-cook-from-config", action="store_true",
                   help="apply DirectoriesToNeverCook without adding other config roots")
    a.add_argument("--cooked-dir", help="Saved/Cooked/<Platform> folder: compare with the real cook")
    a.add_argument("--size", choices=["source", "cooked"], default="source",
                   help="size basis: uncooked editor files (default) or cooked files (needs --cooked-dir)")
    a.add_argument("--budget-mb", type=float, help="fail (exit 2) if the total exceeds this many MB")
    a.add_argument("--level-budget-mb", type=float, help="fail (exit 2) if any level's closure exceeds this")
    a.add_argument("--strict", action="store_true", help="fail (exit 3) on broken or never-cook references")
    a.add_argument("--top", type=int, default=25, help="rows in the largest-assets list")
    a.add_argument("--top-groups", type=int, default=15, help="rows in class/folder tables")
    a.add_argument("--group-depth", type=int, default=2, help="folder depth for grouping (default 2: /Game/X)")
    a.add_argument("--json", help="write the full report as JSON")
    a.add_argument("--csv", help="write every included asset as CSV")
    a.add_argument("--unused-csv", help="write unused project assets as CSV")
    a.add_argument("--md", help="write a Markdown report")
    a.add_argument("--ini-snippet", help="write a DefaultGame.ini snippet (MapsToCook + never-cook candidates)")
    a.set_defaults(func=cmd_analyze)

    wy = sub.add_parser("why", help="show why assets are included")
    selection(wy)
    wy.add_argument("--asset", nargs="+", required=True, help="package or object paths to explain")
    wy.set_defaults(func=cmd_why)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
