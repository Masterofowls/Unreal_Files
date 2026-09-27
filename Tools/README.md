# Tools

| Tool | What it does |
|---|---|
| [`ue_asset_audit.py`](#ue_asset_audit-what-will-my-levels-really-ship) | **Asset audit CLI.** Shows which assets the selected levels actually pull into a packaged build (with all dependencies), how big they are, why each is included, and what's unused. Fails CI when a size budget is exceeded |
| `ue_asset_audit_export.py` | Editor-side exporter used by `ue_asset_audit.py export`. Runs inside Unreal |
| `validate_configs.py` | Checks the `Config/` scalability files: every cvar is in every tier, and none is overridden by an engine ini |
| `gen_scalability_120fps.py` | Generates `Config/Profiles/120FPS/DefaultScalability.ini`, or with `ue58` the UE 5.8 variant |
| `gen_scalability_ue58_60fps.py` | Generates the UE 5.8 variant of `Config/DefaultScalability.ini` |

Everything needs only **Python 3.8+** (standard library). Run the tests with:

```
python3 -m unittest discover -s Tools/tests -v
```

---

## ue_asset_audit: what will my levels really ship?

Packaged builds grow without anyone noticing:
- a test map left in the cook list
- a Blueprint that casts to a cinematic
- a soft reference to a 2 GB sequence
- a folder of old textures nobody deleted

`ue_asset_audit` answers four questions **before** you package:

1. **What do these levels pull in?** The full dependency closure of the maps you pick, including World Partition external actors (`__ExternalActors__` / `__ExternalObjects__`), hard references and soft references (the cooker cooks soft references too).
2. **How big is it?** Totals, per level (including what's unique to each level), per asset class and per folder, and the largest assets.
3. **Why is this asset included?** A reference chain for each asset, for example `L_Main -> BP_Hero -> LS_Intro (soft) -> T_Big`.
4. **What's dead weight?** Project content that nothing in the selection uses. With a cooked folder it also lists packages that were **cooked but aren't needed**, which is size you can remove.

It also reports **broken references** (packages that don't exist), references into `DirectoriesToNeverCook` (these will be missing at runtime), and a warning if `MapsToCook` is empty (the cooker may then cook every map it finds).

### How it works

```
UnrealEditor-Cmd (headless)                   plain Python, no Unreal needed
+-------------------------------+  deps.json  +-------------------------------+
| ue_asset_audit_export.py      | ----------> | ue_asset_audit.py             |
| Asset Registry: all packages, |             | levels / analyze / why        |
| hard + soft deps, file sizes  |             | reports, budgets, exit codes  |
+-------------------------------+             +-------------------------------+
```

- The dependency data comes from Unreal's own **Asset Registry**, so it's the same information the editor's Reference Viewer and Size Map use. No `.uasset` parsing, and it works across engine versions.
- Export once (a few minutes on large projects), then analyze any combination of levels instantly. Re-export after content changes.

### Requirements

- The **Python Editor Script Plugin** must be enabled (*Edit → Plugins → Python Editor Script Plugin*). The export also passes `-EnablePlugins=PythonScriptPlugin`.
- The project must be compiled (C++ projects: build the *Development Editor* target first).

### 1. Export the dependency graph

```bash
# Windows
python Tools/ue_asset_audit.py export --project D:/Projects/MyGame/MyGame.uproject ^
    --engine "C:/Program Files/Epic Games/UE_5.8" --out asset_deps.json

# Or point at the editor binary directly
python Tools/ue_asset_audit.py export --project MyGame.uproject --editor-cmd "C:/.../UnrealEditor-Cmd.exe"

# See the command without running it
python Tools/ue_asset_audit.py export --project MyGame.uproject --engine "C:/UE_5.8" --dry-run
```

### 2. List the maps

```bash
python Tools/ue_asset_audit.py levels asset_deps.json            # maps + World Partition actor counts
python Tools/ue_asset_audit.py levels asset_deps.json --closure  # + full dependency size of each map
```

### 3. Analyze a selection

```bash
# The levels you intend to ship (full paths, short names or patterns)
python Tools/ue_asset_audit.py analyze asset_deps.json --levels L_MainMenu L_Chapter1 "/Game/Maps/Chapters/*"

# What the project's config would cook: MapsToCook, default maps, game mode,
# DirectoriesToAlwaysCook, Asset Manager AlwaysCook rules, DirectoriesToNeverCook
python Tools/ue_asset_audit.py analyze asset_deps.json --from-config

# Add content loaded by C++ or string paths, which the Asset Registry can't see
python Tools/ue_asset_audit.py analyze asset_deps.json --levels L_Main --extra-root /Game/UI /Game/Data/DA_Loot

# Compare against a real cook and use cooked sizes (closest to the shipped size)
python Tools/ue_asset_audit.py analyze asset_deps.json --from-config \
    --cooked-dir D:/Projects/MyGame/Saved/Cooked/Windows --size cooked

# Reports
python Tools/ue_asset_audit.py analyze asset_deps.json --levels L_Main L_Menu \
    --md audit.md --csv included.csv --unused-csv unused.csv --json audit.json \
    --ini-snippet cook_settings.ini
```

| Option | Meaning |
|---|---|
| `--levels MAP...` | Maps to ship: `/Game/Maps/L_Main`, `L_Main`, or a pattern like `/Game/Maps/*` |
| `--from-config` | Add the cook roots from `Config/DefaultEngine.ini` and `DefaultGame.ini`, and honor `DirectoriesToNeverCook` |
| `--extra-root PKG_OR_DIR...` | Extra packages or folders that code loads by path |
| `--soft follow\|ignore` | Follow soft references like the cooker (default), or ignore them to see the hard-only core |
| `--never-cook DIR...` | Treat folders as excluded (test a `DirectoriesToNeverCook` change before making it) |
| `--cooked-dir DIR` | `Saved/Cooked/<Platform>`: finds cooked-but-unneeded packages, shader and other file sizes |
| `--size source\|cooked` | Size basis: uncooked editor files (default) or cooked files (needs `--cooked-dir`) |
| `--budget-mb N` | Exit code **2** if the total is over N MB |
| `--level-budget-mb N` | Exit code **2** if any single level's closure is over N MB |
| `--strict` | Exit code **3** on broken references or references into never-cook folders |
| `--top`, `--top-groups`, `--group-depth` | Report length and folder grouping depth |
| `--json`, `--csv`, `--unused-csv`, `--md` | Machine-readable and Markdown reports |
| `--ini-snippet FILE` | A `DefaultGame.ini` snippet: `MapsToCook` for the selected levels, plus commented `DirectoriesToNeverCook` candidates for the largest unused folders |

### 4. Ask why something is included

```bash
python Tools/ue_asset_audit.py why asset_deps.json --levels L_Main --asset /Game/Cine/T_Big
# /Game/Cine/T_Big  (1000.00 KB) [only via soft references]
#     root   /Game/Maps/L_Main
#     hard   /Game/Chars/BP_Hero
#     soft   /Game/Cine/LS_Intro
#     hard   /Game/Cine/T_Big
```

Then fix the link, for example with a soft reference that's only loaded when needed, a different data asset, or by moving the cinematic reference out of the hero Blueprint.

### Use it in CI

```bash
python Tools/ue_asset_audit.py analyze asset_deps.json --from-config \
    --cooked-dir Saved/Cooked/Windows --size cooked \
    --budget-mb 20000 --level-budget-mb 6000 --strict --md audit.md
# exit 0 = OK, 2 = over budget, 3 = broken references, 1 = bad input
```

Publish `audit.md` as a build artifact, so every build shows what grew and why.

### Accuracy and limits

- **Source sizes** (default) are uncooked editor files. They include editor-only data and aren't compressed the way the final package is. **Cooked sizes** (`--cooked-dir --size cooked`) are much closer to what ships. The final pak/IoStore files are usually smaller still, because of Oodle compression.
- **The Asset Registry can't see everything:**
  - assets loaded **by string path** at runtime
  - some references made from **C++ constructors** (`ConstructorHelpers`)
  - content pulled in by **Asset Manager rules** beyond the AlwaysCook directories
  - **localization** and **plugin** content that's cooked separately

  Add those with `--extra-root`, or compare against a real cook with `--cooked-dir`: anything cooked but not reachable shows up there.
- **Editor-only references** (for example source files referenced only in the editor) may show as included in source mode, but they're not cooked. `--cooked-dir` lists them as *reachable but not cooked*.
- **Engine content** (`/Engine/...`) and engine plugin content are listed as external references. Their sizes appear only in `--cooked-dir` mode.
- The tool **never modifies** your project. `--ini-snippet` only writes a suggestion file for you to review.
