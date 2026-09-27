# Checks the rules the config files depend on:
#   1. Every scalability cvar appears in every tier of its group (no preset leaking).
#   2. No scalability cvar is also set in an engine ini (higher priority would lock it).
# Usage: python3 Tools/validate_configs.py   (exit code 1 on failure)
import collections, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = ["Config/DefaultEngine.ini",
          "Config/Profiles/120FPS/DefaultEngine_120FPS.ini",
          "Config/Profiles/UE58/DefaultEngine_UE58.ini"]
SCALABILITY = ["Config/DefaultScalability.ini",
               "Config/Profiles/120FPS/DefaultScalability.ini",
               "Config/Profiles/UE58/60FPS/DefaultScalability.ini",
               "Config/Profiles/UE58/120FPS/DefaultScalability.ini"]

def parse(path):
    sections, cur = collections.OrderedDict(), None
    for line in open(os.path.join(ROOT, path)):
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("["):
            cur = line[1:line.index("]")]
            sections.setdefault(cur, [])
            continue
        sections[cur].append(line.split("=")[0].lstrip("+-"))
    return sections

engine_keys = {k for f in ENGINE for keys in parse(f).values() for k in keys}
ok = True
for f in SCALABILITY:
    groups = collections.defaultdict(dict)
    for sec, keys in parse(f).items():
        if "@" in sec:
            group, tier = sec.split("@")
            groups[group][tier] = set(keys)
    for group, tiers in groups.items():
        allkeys = set().union(*tiers.values())
        for tier, keys in tiers.items():
            if keys != allkeys:
                ok = False
                print(f"{f}: [{group}@{tier}] missing {sorted(allkeys - keys)}")
        overlap = allkeys & engine_keys
        if overlap:
            ok = False
            print(f"{f}: [{group}] cvars also set in an engine ini: {sorted(overlap)}")
print("OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
