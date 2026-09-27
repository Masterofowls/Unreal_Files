# Unreal Engine 5.8: What Changes for This Repo, and How to Use It

UE 5.8 was released on **17 June 2026**; hotfixes 5.8.1 and 5.8.2 are out. It's reported as the last major 5.x release before Epic's focus moves to UE 6.

This guide covers:
- how to **upgrade** a project to 5.8 safely
- what **changed** that affects the configs and guides in this repo
- which **new 5.8 features** help performance, and which to leave alone for now

Everything else in this repo still applies to 5.8, except the changes listed in section 2.

---

## Contents

1. [Upgrade steps](#1-upgrade-steps)
2. [Changes that affect this repo](#2-changes-that-affect-this-repo)
3. [Installing the 5.8 profiles](#3-installing-the-58-profiles)
4. [New features that help performance](#4-new-features-that-help-performance)
5. [120 fps on 5.8: what changes for Tier A and Tier B](#5-120-fps-on-58)
6. [Experimental in 5.8: don't ship on these yet](#6-experimental-in-58)
7. [Verify after upgrading](#7-verify-after-upgrading)
8. [Sources](#8-sources)

---

## 1. Upgrade steps

Follow the general upgrade rules in `Common_Bugs_Guide.md` section 16. For 5.8 specifically:

1. **Branch or back up first.** Don't upgrade mid-milestone.
2. **Plugins:** check that every Fab/marketplace plugin (DLSS/Streamline, FSR, XeSS, Reflex, and your middleware) has a 5.8 build.
3. **Open a copy of the project in 5.8**, rebuild C++ from the IDE, and fix **all deprecation warnings**. Known deprecations and removals:

   | Deprecated or removed | Replacement |
   |---|---|
   | **Screen Space GI (SSGI)** | Lumen / **Lumen Lite** |
   | **LightWeightInstances** | ISM, Instanced Actors, or Mass (`120FPS_Guide.md` section 18) |
   | `r.SkipRedundantTransformUpdate` (removed) | Delete it from your ini files |
   | `r.Water.SingleLayer.ForceVelocity` | `r.Water.SingleLayer.VelocityOutputPass` (0 none, 1 depth prepass (default), 2 legacy base pass) |
   | **Movie Render Queue presets** | Still work but get no new features. Move to **Movie Render Graph** (production-ready in 5.8) |

4. **Compile all Blueprints** (`-run=CompileAllBlueprints`) and fix material errors.
5. **Resave** assets (`-run=ResavePackages`) once everything works.
6. **Replace this repo's scalability files** with the 5.8 variants (section 3).
7. **Record a new PSO cache** (`120FPS_Guide.md` section 14.1). Shader permutations changed a lot in 5.8, so old `.spc` files are stale.
8. **Rebuild HLODs.** 5.8's perceptual diff skips rebuilds that don't change anything visually.
9. **Cook, package and run the validation plan** (`120FPS_Guide.md` section 23) on Tier A and Tier B hardware before merging the upgrade.

---

## 2. Changes that affect this repo

| 5.8 change | Effect | What this repo does |
|---|---|---|
| **Lumen Lite:** Medium GI/Reflection quality uses an Irradiance Field final gather (`r.Lumen.FinalGatherMethod 0`), about 2× faster than Lumen High | The base 60 fps `DefaultScalability.ini` turns Lumen **off** at Medium, which would **block** Lumen Lite | `Config/Profiles/UE58/60FPS/DefaultScalability.ini` allows Lumen GI and reflections at Medium |
| `r.Lumen.ScreenProbeGather.IntegrateDownsampleFactor` **removed from High** in Epic's scalability (too noisy) | Our profiles used 2 at High | The 5.8 variants use **1** at High (both 60 and 120 fps) |
| **MegaLights production-ready** | Viable for light-heavy scenes, and **hardware ray tracing is recommended** | Off by default. `r.MegaLights.Supported=0` in `DefaultEngine_UE58.ini` strips its shaders. See `Lighting_PostProcess_Guide.md` section 6 |
| **SSGI deprecated** | — | None of our tiers use SSGI. Nothing to change |
| **Dynamic resolution supported on PC** (DX12, Vulkan) | Our 120 fps profile depends on it | Already configured (8.33 ms budget) |
| **"Mask material only in early Z-pass" on by default** | Masked materials are cheaper in the prepass | Nothing to change |
| **MallocBinned3 default on Windows** | Allocator change | Nothing to change. Re-measure memory (`memreport -full`) after upgrading |
| **Nanite streaming pool and GPU Scene use reserved resources** | No memory spike when they resize | Nothing to change. `r.Nanite.Streaming.StreamingPoolSize` still applies |
| `r.Material.StripUnusedDefaultTextures=1` (default) | Default textures of unused material parameters aren't loaded | Free memory saving |
| **Distance fields on integrated GPUs** | Lumen and DF features can now run on some iGPUs | Our **Low** tier still turns Lumen off, which is right for iGPUs at 60+ fps |
| **PSO precaching fails gracefully** when shader data is missing | Fewer crashes, but missing PSOs still cause hitches | Keep recording the bundled PSO cache |
| New **`r.DOF.PreferLowerBitDepth`** | Lower-precision DOF buffers | Set to 1 on Low/Medium in the 5.8 variants |

---

## 3. Installing the 5.8 profiles

| File | Use |
|---|---|
| `Config/Profiles/UE58/60FPS/DefaultScalability.ini` | **Replaces** `Config/DefaultScalability.ini` in 5.8 projects targeting 60 fps. Medium = Lumen Lite |
| `Config/Profiles/UE58/120FPS/DefaultScalability.ini` | **Replaces** the 120 fps `DefaultScalability.ini` in 5.8 projects |
| `Config/Profiles/UE58/DefaultEngine_UE58.ini` | **Merge** into `DefaultEngine.ini`, after the 120 fps add-on if you use it. It strips MegaLights shaders and lists opt-in 5.8 switches |

Everything else (`DefaultEngine.ini`, `DefaultGame.ini`, `DefaultEngine_120FPS.ini`, `DefaultGameUserSettings.ini`, `DefaultEditorPerProjectUserSettings.ini`) works unchanged in 5.8.

The 5.8 scalability files are **generated** from the 5.3–5.7 versions with only the section 2 changes applied, so the two stay in sync. Every cvar still appears in every tier.

---

## 4. New features that help performance

### Rendering

| Feature | How to use it |
|---|---|
| **Lumen Lite** | Used automatically at Medium GI/Reflection quality with the 5.8 profiles. Check it's active: `r.Lumen.FinalGatherMethod` → 0 at Medium |
| **MegaLights** (production) | For many shadowed lights: `Lighting_PostProcess_Guide.md` section 6. Budget the ray tracing memory on 8 GB cards |
| **VSM: Nanite tessellation in shadows toggle** | `r.Shadow.Virtual.Nanite.AllowTessellationDirectional/Local 0` when displacement doesn't need to show in shadows |
| **VSM: deferred invalidation budget** | `r.Shadow.Virtual.DeferredInvalidationBudget` throttles invalidations caused by Nanite LOD changes |
| **Nanite foliage: Pixel Programmable Distance** (new foliage type property) | Set it like WPO Disable Distance. Beyond it, foliage uses the cheaper fixed-function raster path |
| **Lumen height fog on reflections** | `r.Lumen.HeightFog 1` (opt-in): reflections in fog match the scene |
| **Lumen: skip unlit hits** | `r.Lumen.ScreenProbeGather.ScreenTraces.HZBTraversal.SkipUnlitHits 1` (opt-in): less GI noise from unlit meshes |
| **DOF lower bit depth** | `r.DOF.PreferLowerBitDepth 1` on low tiers (in the 5.8 profiles) |
| **CombineLUTs on async compute, TSR thin-geometry optimizations** | Automatic |
| **Fewer shader permutations** (Lumen, VSM, Substrate, volumetric fog, MegaLights) | Automatic. Shorter compiles, fewer PSOs |

### CPU, streaming and memory

| Feature | How to use it |
|---|---|
| **Hierarchical CPU culling for non-Nanite ISM** | `r.SceneCulling.HierarchicalCPUCulling 1` (opt-in) for scenes with many non-Nanite instances |
| **JIT async loading** | `s.StreamableEnableJITAsyncLoadingGlobally 1` + compile with `UE_ENABLE_STREAMABLE_JIT_ASYNC_LOADING=1`. Trickles large bursts of async loads (opt-in, test streaming hitches) |
| **Incremental GC while actors are pending purge** | `s.ContinuouslyIncrementalGCWhileActorsPendingPurge` / `wp.Runtime.LevelStreamingContinuouslyIncrementalGCWhileActorsPendingPurgeForWP` smooth GC spikes when World Partition unloads many actors |
| **PCG runtime scheduler sleep** | `pcg.RuntimeGeneration.TimeBetweenRuntimeGenSchedulerTicks` (up to ~30% less game thread cost for runtime PCG) |
| **HLOD perceptual diff** | Automatic. HLOD rebuilds are skipped when the visual change is insignificant |
| **Navmesh link pool sizing** (`bMinimizeLinkPoolSize`) | Around 30 MB saved in large nav worlds |
| **Blueprint async action limit** | `bp.MaxAsyncActionCount` catches runaway async Blueprint actions |

### Tools

| Tool | Use |
|---|---|
| **Shader count overlay** in the Material and Material Instance editors + `UMaterialEditingLibrary::ListShaders()` | Track permutations (`Materials_Textures_Guide.md` section 2.2) |
| **World Partition Insights** (per-cell streaming analysis, session playback) and `wp.Editor.ExportMinimapForInsights` | Debug streaming hitches |
| `r.ProfileGPU.TableFormatting 0` | Readable ProfileGPU logs |
| `stats.UnitTimestamp 1` | Timestamps in `stat unit`, for matching captures |
| MegaLights visualizers (`r.MegaLights.Visualize.LightComplexity`, `r.MegaLights.Debug 1`) | Find the lights that cost the most |

---

## 5. 120 fps on 5.8

**Tier B (Medium @ 120) gains the most:**
- **Lumen Lite** costs about half of Lumen High. Epic's High budget is ~4 ms at 1080p on consoles, so Medium GI should land well under the 1.5 ms GI line in `120FPS_Guide.md` section 2.1.
- Use the saved time for a **higher dynamic resolution floor**: try `r.DynamicRes.MinScreenPercentage=58` for Tier B at 1080p, and measure.
- GI is softer than High. Check interiors and small-scale indirect detail, which is where Lumen Lite differs most from High.

**Tier A (High @ 120):**
- `IntegrateDownsampleFactor` goes back to 1 at High (Epic's 5.8 change, less noise). That costs a little GPU time.
  - Measure `LumenScreenProbeGather` in `ProfileGPU`.
  - If you need the time back, lower `SpatialFilterNumPasses` to 1 or raise the Radiosity update factors in `[GlobalIlluminationQuality@2]`. Don't re-add the downsample factor.
- **MegaLights:** only for light-heavy levels, only on Tier A, and only after measuring the hardware ray tracing memory (BVH) on an 8 GB card. Keep `r.MegaLights.Allow 0` for Medium and below.
- Re-record the **PSO cache** and re-run the pass criteria (`120FPS_Guide.md` section 23). 5.8 changes enough shaders that old measurements don't carry over.

---

## 6. Experimental in 5.8

Try these in a branch, but don't ship on them without a full profile and QA pass:

- **Mesh Terrain:** a next-generation terrain (3D, layered, Nanite, virtual textures). Keep **Landscape** (Nanite landscape) for production (`120FPS_Guide.md` section 17).
- **MetaHuman Collections:** crowds of MetaHumans ("hundreds on mobile, thousands on high-end"). Promising for crowds. Until it's stable, use Mass + vertex animation (`120FPS_Guide.md` section 19.5).
- **Fast Geometry Streaming** updates.
- **VSM Prefiltered Distant shadows** (`r.Shadow.Virtual.PrefilteredDistant.ProjectEnable`).
- **Fog Screen Space Scattering** and **Substrate Toon shading.**
- **SM6 on iOS** (Metal Shader Converter).
- **Control Rig Physics** is **Beta**.
- **Lumen Lite** itself is listed as **Beta** in Epic's release notes, and is the default on current handhelds. Validate it on your content before shipping Medium on Lumen Lite.

---

## 7. Verify after upgrading

Type these in the console of a packaged Test build, at each quality preset:

| Check | Expected |
|---|---|
| `scalability 1`, then `r.Lumen.FinalGatherMethod` | `0` (Lumen Lite active at Medium) |
| `scalability 2`, then `r.Lumen.FinalGatherMethod` | Not `0` (screen probe gather at High) |
| `r.Lumen.DiffuseIndirect.Allow` at Medium | `1` |
| `r.MegaLights.Supported` | `0` (unless you enabled MegaLights on purpose) |
| `r.DynamicRes.OperationMode` / `stat DynamicRes` | Dynamic resolution active with the 8.33 ms budget (120 fps profile) |
| `stat psocache` after a play-through | Runtime PSO misses ~0 with the new cache |
| `memreport -full` after 30 min | No growth compared with the pre-upgrade build |

Then run the full test plan in `120FPS_Guide.md` section 23.

---

## 8. Sources

- [Epic – Unreal Engine 5.8 Release Notes](https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-8-release-notes)
- [Epic – Unreal Engine 5.8 is now available](https://www.unrealengine.com/news/unreal-engine-5-8-is-now-available)
- [Epic – Lumen Performance Guide (5.8)](https://dev.epicgames.com/documentation/unreal-engine/lumen-performance-guide-for-unreal-engine)
- [Epic – MegaLights](https://dev.epicgames.com/documentation/en-us/unreal-engine/megalights-in-unreal-engine)
- [Epic Forums – 5.8.1 Hotfix](https://forums.unrealengine.com/t/5-8-1-hotfix-released/2738864) · [5.8.2 Hotfix](https://forums.unrealengine.com/t/5-8-2-hotfix-released/2746335)
- [Tom Looman – UE 5.8 Performance Highlights](https://tomlooman.com/unreal-engine-5-8-performance-highlights/)
- [Daniel Wright (Epic) on Lumen Lite](https://x.com/EpicShaders/status/2070573554135953556)
- [CG Channel – 5 key features in UE 5.8](https://www.cgchannel.com/2026/06/see-5-key-features-for-cg-artists-in-unreal-engine-5-8/)
- [Guru3D – UE 5.8 debuts Lumen Lite and production-ready MegaLights](https://www.guru3d.com/story/unreal-engine-58-debuts-lumen-lite-and-productionready-megalights/)
- [TechPowerUp – UE 5.8 paves way for better optimization in UE6](https://www.techpowerup.com/350071/unreal-engine-5-8-paves-way-for-better-optimization-in-ue6)
