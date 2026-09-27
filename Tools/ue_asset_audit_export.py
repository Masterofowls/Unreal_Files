"""Runs INSIDE the Unreal Editor (Python Editor Script Plugin) and exports the
project's package dependency graph to JSON for Tools/ue_asset_audit.py.

You normally don't run this directly. Use:
    python Tools/ue_asset_audit.py export --project <Game.uproject> --engine <UE root>

which launches:
    UnrealEditor-Cmd <Game.uproject> -run=pythonscript -script="<this file>" -unattended -nop4 -nosplash
with the output path passed in the UE_ASSET_AUDIT_OUT environment variable.

Output format (schema version 1):
{
  "schema": 1,
  "project_dir": "...", "project_name": "...", "engine_version": "...",
  "mounts": {"/Game": "Content", "/MyPlugin": "Plugins/MyPlugin/Content"},
  "packages": {
     "/Game/Maps/L_Main": {"class": "World", "files": ["Content/Maps/L_Main.umap"],
                           "size": 123456, "hard": ["/Game/..."], "soft": ["/Game/..."]}
  }
}
"""
import json
import os
import time

import unreal  # only available inside the editor

SCHEMA = 1
PACKAGE_EXTENSIONS = (".uasset", ".umap")
# Companion files that belong to the same package (source or cooked).
COMPANION_EXTENSIONS = (".uexp", ".ubulk", ".uptnl", ".m.ubulk")


def log(msg):
    unreal.log("[ue_asset_audit] " + msg)


def norm(path):
    return os.path.normpath(path).replace("\\", "/")


def find_mounts(project_dir):
    """Map content mount points to directories relative to the project."""
    mounts = {"/Game": "Content"}
    plugins_dir = os.path.join(project_dir, "Plugins")
    for root, dirs, files in os.walk(plugins_dir):
        for f in files:
            if not f.endswith(".uplugin"):
                continue
            plugin_dir = root
            content = os.path.join(plugin_dir, "Content")
            if os.path.isdir(content):
                name = os.path.splitext(f)[0]
                mounts["/" + name] = norm(os.path.relpath(content, project_dir))
        # don't descend into plugin Content/Source folders looking for .uplugin
        dirs[:] = [d for d in dirs if d not in ("Content", "Source", "Binaries", "Intermediate")]
    return mounts


def list_packages(project_dir, mounts):
    """Walk every mount on disk and return {package_name: [relative files]}."""
    packages = {}
    for mount, rel_dir in mounts.items():
        abs_dir = os.path.join(project_dir, rel_dir)
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                base, ext = os.path.splitext(f)
                if ext.lower() not in PACKAGE_EXTENSIONS:
                    continue
                rel_file = norm(os.path.relpath(os.path.join(root, f), project_dir))
                rel_in_mount = norm(os.path.relpath(os.path.join(root, base), abs_dir))
                pkg = mount + "/" + rel_in_mount
                files_for_pkg = [rel_file]
                for cext in COMPANION_EXTENSIONS:
                    comp = os.path.join(root, base + cext)
                    if os.path.isfile(comp):
                        files_for_pkg.append(norm(os.path.relpath(comp, project_dir)))
                packages[pkg] = files_for_pkg
    return packages


def make_options(hard, soft):
    opts = unreal.AssetRegistryDependencyOptions()
    for prop, value in (("include_hard_package_references", hard),
                        ("include_soft_package_references", soft),
                        ("include_searchable_names", False),
                        ("include_hard_management_references", False),
                        ("include_soft_management_references", False)):
        try:
            opts.set_editor_property(prop, value)
        except Exception:  # property missing in this engine version
            pass
    return opts


def asset_class(asset_data):
    path = getattr(asset_data, "asset_class_path", None)  # UE 5.1+
    if path is not None:
        name = getattr(path, "asset_name", None)
        if name is not None:
            return str(name)
    cls = getattr(asset_data, "asset_class", None)  # UE 5.0 and older
    return str(cls) if cls is not None else ""


def to_names(result):
    if not result:
        return []
    out = []
    for n in result:
        s = str(n)
        # Code packages and transient packages have no content to cook.
        if s and not s.startswith(("/Script/", "/Temp/", "/Memory/")):
            out.append(s)
    return sorted(set(out))


def main():
    out_path = os.environ.get("UE_ASSET_AUDIT_OUT")
    if not out_path:
        log("UE_ASSET_AUDIT_OUT is not set; nothing to do.")
        return 1

    project_dir = norm(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
    project_file = unreal.Paths.get_project_file_path() if hasattr(unreal.Paths, "get_project_file_path") else ""
    project_name = os.path.splitext(os.path.basename(project_file))[0] if project_file else os.path.basename(project_dir.rstrip("/"))

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    log("Scanning asset registry...")
    registry.search_all_assets(True)
    if hasattr(registry, "wait_for_completion"):
        registry.wait_for_completion()

    mounts = find_mounts(project_dir)
    packages_on_disk = list_packages(project_dir, mounts)
    log("Found %d packages in %d mounts" % (len(packages_on_disk), len(mounts)))

    hard_opts = make_options(True, False)
    soft_opts = make_options(False, True)

    packages = {}
    start = time.time()
    for i, (pkg, files) in enumerate(sorted(packages_on_disk.items())):
        if i and i % 2000 == 0:
            log("  %d / %d packages (%.0fs)" % (i, len(packages_on_disk), time.time() - start))
        classes = [asset_class(a) for a in (registry.get_assets_by_package_name(pkg) or [])]
        hard = to_names(registry.get_dependencies(pkg, hard_opts))
        soft = [s for s in to_names(registry.get_dependencies(pkg, soft_opts)) if s not in hard]
        size = 0
        for rel in files:
            try:
                size += os.path.getsize(os.path.join(project_dir, rel))
            except OSError:
                pass
        packages[pkg] = {
            "class": classes[0] if classes else "",
            "files": files,
            "size": size,
            "hard": hard,
            "soft": soft,
        }

    engine_version = ""
    try:
        engine_version = unreal.SystemLibrary.get_engine_version()
    except Exception:
        pass

    data = {
        "schema": SCHEMA,
        "project_dir": project_dir,
        "project_name": project_name,
        "engine_version": engine_version,
        "mounts": mounts,
        "packages": packages,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    log("Wrote %d packages to %s in %.0fs" % (len(packages), out_path, time.time() - start))
    return 0


# UE's pythonscript commandlet doesn't guarantee __name__ == "__main__", so run
# whenever the output path is set. Tests import this module with autorun off.
if os.environ.get("UE_ASSET_AUDIT_OUT") and not os.environ.get("UE_ASSET_AUDIT_NO_AUTORUN"):
    main()
