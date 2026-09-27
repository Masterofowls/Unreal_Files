# Unreal_Files
Unreal Engine docs, configs, .ini, components

| Path | Contents |
|---|---|
| `Config/` | Reusable performance-tuned `.ini` files, the 120 fps profile and the UE 5.8 profiles ([README](Config/README.md)) |
| `Docs/120FPS_Guide.md` | Reaching a stable 120 fps with Lumen, Nanite and VSM |
| `Docs/Common_Bugs_Guide.md` | Avoiding common Unreal bugs, crashes, and packaging and replication errors |
| `Docs/Code_Optimization_Guide.md` | Optimizing Blueprints and C++: profiling, Blueprint VM costs, moving logic to C++, containers, threading |
| `Docs/Materials_Textures_Guide.md` | Optimizing materials and textures: shader cost, permutations, blend modes, compression, mips, streaming, virtual textures |
| `Docs/Lighting_PostProcess_Guide.md` | Optimizing lighting and post-processing: light authoring, shadows, MegaLights, fog and clouds, reflections, post effects, PP volumes |
| `Docs/UE58_Guide.md` | Upgrading to UE 5.8: what changed, Lumen Lite, MegaLights, 5.8 config profiles |
| `Templates/UE.gitattributes` | Git LFS setup with file locking for Unreal projects |
| `Tools/` | Scripts that generate the 120 fps and UE 5.8 scalability files, and `validate_configs.py` to check tier consistency and cvar priority |
