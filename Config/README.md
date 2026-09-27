# Reusable performance config for Unreal Engine 5

A drop-in set of `.ini` files for UE 5.3 – 5.7 projects (Nanite + Lumen + Virtual Shadow Maps + TSR) tuned for frame time, smooth frame pacing and fast loading.

| File | What it controls |
|---|---|
| `DefaultEngine.ini` | Project-wide settings that don't change with quality presets: rendering pipeline, PSO precaching, async loading, GC, threading, audio, networking |
| `DefaultScalability.ini` | Low / Medium / High / Epic / Cine quality tiers for shadows, GI, reflections, post-processing, textures, effects, foliage and AA |
| `DefaultGame.ini` | Packaging settings: IoStore, Oodle compression, shared shader code (needed for PSO bundles) |

## 120 fps profile

`Profiles/120FPS/` retunes the tiers for a stable 120 fps: **High** on 8 GB GPUs with a Core i5 / Ryzen 5, and **Medium** on lower hardware with Lumen, VSM and fog kept on. It adds dynamic resolution with an 8.33 ms budget. The full instructions are in [`Docs/120FPS_Guide.md`](../Docs/120FPS_Guide.md).

| File | How to use it |
|---|---|
| `Profiles/120FPS/DefaultScalability.ini` | Replaces `DefaultScalability.ini` |
| `Profiles/120FPS/DefaultEngine_120FPS.ini` | Merge its sections into `DefaultEngine.ini` |
| `Profiles/120FPS/DefaultGameUserSettings.ini` | Copy to `Config/`: 120 fps cap, VSync off, dynamic resolution on |

## Install

1. Copy the three files into `<Project>/Config/`. If you already have files with those names, **merge** the sections into them instead of overwriting.
2. Delete `<Project>/Saved/Config` so stale user settings don't mask the new ones.
3. Restart the editor. It will recompile shaders once.
4. Check the result in a **Test** or **Shipping** build with `stat unit`, `stat gpu`, `ProfileGPU` and Unreal Insights.

## Why the settings are split this way

Unreal applies cvars by priority:

```
Scalability < ProjectSetting (RendererSettings) < [SystemSettings] < DeviceProfile < [ConsoleVariables] < Console
```

If you put a quality cvar in `DefaultEngine.ini`, it overrides every scalability tier, and the in-game Low/High menu stops changing it. So all per-tier cvars live only in `DefaultScalability.ini`, and each one appears in every tier. If a cvar is missing from a tier, switching presets leaves the previous value in place ("CVar leaking").

## Main techniques

- **PSO precaching and a bundled PSO cache** remove first-use shader stutter. Record a `.spc` cache with `-logPSO` to cover what precaching misses.
- **Lumen runs on High and Epic only.** High uses Epic's 60 fps configuration, plus a downsampled probe integration on 5.6+. Medium falls back to DFAO + SSR.
- **VSM cost scales per tier** through the page pool, the resolution LOD bias (including the bias used while a light is moving) and the SMRT ray/sample counts.
- **TSR history stays at 100%** below Cine (stock Epic uses 200%). Screen percentage follows display resolution.
- **Static lighting is disabled**, which means fewer shader permutations. Set `r.AllowStaticLighting=True` if you bake lightmaps.
- **The GPU skin cache** skins each mesh once per frame instead of once per pass.
- **Streaming and GC are time-sliced:** a 3 ms async-loading budget, incremental BeginDestroy, parallel GC, destruction on worker threads, GC clusters and a shorter purge interval.
- **The texture pool is capped to real VRAM** with `r.Streaming.LimitPoolSizeToVRAM`.
- **Auto-detect thresholds are raised**, because the stock values put almost every modern GPU on Epic.
- **Network bandwidth defaults are updated** and adaptive net update frequency is on.
- The `[ConsoleVariables]` section of `DefaultEngine.ini` lists **opt-in experimental switches** (incremental GC reachability, VSM receiver mask, Lumen far-field occlusion-only, batched ticks). They're commented out. Enable them one at a time after profiling.

## Adapting to a project

| Project type | Change |
|---|---|
| Baked lighting / stylized | `r.AllowStaticLighting=True`, `r.DynamicGlobalIlluminationMethod=0`, `r.ReflectionMethod=2`, `r.Shadow.Virtual.Enable=0` |
| Hardware ray tracing | `r.RayTracing=True`, `r.Lumen.HardwareRayTracing=True`, then try `r.LumenScene.FarField.OcclusionOnly=1` |
| Big open world | Raise `r.Nanite.Streaming.StreamingPoolSize`, try `gc.ActorClusteringEnabled=True`, tune the VSM page pool |
| Console / handheld (fixed spec) | `r.DiscardUnusedQuality=True`, and pin the tiers with Device Profiles |
| Competitive / low latency | Uncomment `r.GTSyncType=1`, cap the frame rate with `t.MaxFPS` |

Cvars tagged `[5.x+]` are ignored by older engine versions, so the same files work across versions. Confirm the exact names against `Engine/Config/BaseEngine.ini` and `BaseScalability.ini` for your version.

## Sources

- [Epic – Console Variables Reference](https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-console-variables-reference)
- [Epic – Virtual Shadow Maps](https://dev.epicgames.com/documentation/en-us/unreal-engine/virtual-shadow-maps-in-unreal-engine)
- [Epic – Incremental Garbage Collection](https://dev.epicgames.com/documentation/unreal-engine/incremental-garbage-collection-in-unreal-engine?lang=en-US)
- [Epic – Garbage Collection Settings](https://dev.epicgames.com/documentation/unreal-engine/garbage-collection-settings-in-the-unreal-engine-project-settings)
- [Epic – Texture Streaming Configuration](https://dev.epicgames.com/documentation/unreal-engine/texture-streaming-configuration-in-unreal-engine?lang=en-US)
- [Epic tech blog – Shader stuttering and PSO precaching](https://www.unrealengine.com/tech-blog/game-engines-and-shader-stuttering-unreal-engines-solution-to-the-problem)
- [Intel – Unreal Engine 5 Optimization Guide, Ch. 2](https://www.intel.com/content/www/us/en/developer/articles/technical/unreal-engine-optimization-chapter-2.html)
- [Tom Looman – UE 5.6 Performance Highlights](https://tomlooman.com/unreal-engine-5-6-performance-highlights/)
- [Tom Looman – PSO Precaching & Bundled PSOs](https://tomlooman.com/unreal-engine-psocaching/)
- [StraySpark – VSM optimization for open worlds](https://www.strayspark.studio/blog/virtual-shadow-map-optimization-open-worlds-ue5-7)
