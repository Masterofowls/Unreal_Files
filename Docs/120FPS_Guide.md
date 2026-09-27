# 120 FPS in Unreal Engine 5 with Lumen, Nanite and Virtual Shadow Maps

This guide covers two targets. The first is a stable 120 fps on **High** on the target PC (8 GB VRAM, Core i5 or Ryzen 5 class, 16 GB RAM). The second is a stable 120 fps on **Medium** on a weaker PC, while keeping the game's look.

It assumes UE 5.3 to 5.7 and Windows with DX12 and SM6. It builds on the configs in `Config/` and the 120 fps profile in `Config/Profiles/120FPS/`.

> **Read this first.** At 120 fps every frame has to finish in **8.33 ms** on the CPU *and* the GPU, which is half the 60 fps budget. Config files alone can't get you there. About a third of the work is config (this repo), a third is content budgets (sections 5–10 and 16–22) and a third is CPU work (sections 12, 18–21). Every number here is a **starting budget**. Measure your own game on real Tier A and Tier B machines and adjust.

---

## Contents

0. [What "stable 120" and "without losing visuals" mean](#0-definitions)
1. [Hardware tiers and resolution targets](#1-hardware-tiers-and-resolution-targets)
2. [Frame, CPU and memory budgets](#2-budgets)
3. [Install the 120 fps profile](#3-install-the-120-fps-profile)
4. [Measure before you change anything](#4-measure-first)
5. [Nanite](#5-nanite)
6. [Lumen](#6-lumen)
7. [Upscaling, dynamic resolution and frame generation](#7-upscaling-dynamic-resolution-frame-generation)
8. [Virtual Shadow Maps and lights](#8-virtual-shadow-maps-and-lights)
9. [Materials and shaders](#9-materials-and-shaders)
10. [Translucency, VFX, fog and post](#10-translucency-vfx-fog-post)
11. [Auto-detect and the settings menu](#11-auto-detect-and-the-settings-menu)
12. [CPU: game thread and render thread](#12-cpu)
13. [Streaming, VRAM (8 GB) and RAM (16 GB)](#13-streaming-and-memory)
14. [Hitches: PSO, streaming, GC and spawning](#14-hitches)
15. [Frame pacing and latency](#15-frame-pacing-and-latency)
16. [Distance rendering: LOD, culling, HLOD](#16-distance-rendering)
17. [Landscape](#17-landscape)
18. [Many actors and instancing](#18-many-actors-and-instancing)
19. [Animated meshes: skeletal, cloth, hair, crowds](#19-animated-meshes-skeletal-meshes-cloth-hair-crowds)
20. [Physics simulation (Chaos)](#20-physics-simulation-chaos)
21. [Collision and queries](#21-collision-and-queries)
22. [Other systems: water, decals, audio, networking, AI](#22-other-systems)
23. [Validation: test plan and pass criteria](#23-validation)
24. [Troubleshooting table](#24-troubleshooting)
25. [Sources](#25-sources)

---

## 0. Definitions

**"Stable 120"** means the following pass criteria, used throughout this guide. They are checked with the test plan in section 23.

| Metric | Requirement |
|---|---|
| Average fps (capped at 120) | 120 |
| Average fps with no cap | ≥ 135. That leaves about 12% headroom, and without headroom there's no stability |
| 1% low | ≥ 110 fps (frame time ≤ 9.1 ms) |
| 0.1% low | ≥ 90 fps |
| Hitches > 33 ms during gameplay | 0 (loading screens excluded) |
| Frame generation | **Not counted.** 120 must be real rendered frames |

**"Without losing visuals"** means the rendering *features* stay on and only their *internal cost* goes down. This is the main difference from a normal "Medium" preset.

| Keep ON at Medium (defines the look) | Reduce instead (hard to see at 120 fps) |
|---|---|
| Lumen GI, including short-range AO | Internal resolution (dynamic, reconstructed by TSR) |
| Virtual Shadow Maps with soft shadows | Lumen update rates, probe density, integrate resolution |
| Lumen reflections (half resolution) | Mesh SDF detail tracing (global SDF only below Epic) |
| Volumetric fog | TSR history at 100% instead of 200% |
| Full tonemapper, bloom, eye adaptation | Soft-shadow sample counts for local lights (8 → 2) |
| High material quality, full texture mips | Nanite pixels-per-edge 1 → 1.5 |

Why a lower internal resolution works: TSR accumulates detail over time. Epic's formula for the time to reach one sample per pixel is `1000 / (ScreenPercentage² × FrameRate)` ms. At 58% and 120 fps that takes about **25 ms**. At 50% and 60 fps it takes about **67 ms**. So a 120 fps game at ~60% resolution converges faster than a typical 60 fps console game.

---

## 1. Hardware tiers and resolution targets

| | **Tier A: target PC → High @ 120** | **Tier B: lower PC → Medium @ 120** |
|---|---|---|
| GPU | RTX 3060 Ti / 4060 / 4060 Ti 8 GB / 5060, RX 6650 XT / 7600, Arc B580 | RTX 2060 6 GB / 3050 8 GB, RX 5600 XT / 6600, Arc A580 |
| CPU | Core i5-12400 / 13400 / 14400, Ryzen 5 5600 / 7600 (6 cores / 12 threads) | Core i5-10400, Ryzen 5 3600 |
| RAM | 16 GB, dual channel | 16 GB, dual channel |
| Storage | NVMe SSD | SATA SSD (HDD is not supported at 120 fps) |
| Output resolution | 1440p **or** 1080p | 1080p |
| Internal resolution (dynamic) | 1440p: 55–70% (~790p–1000p). 1080p: 70–90% | 55–75% (~600p–810p) |
| Upscaler | TSR, or DLSS / FSR / XeSS "Quality" or "Balanced" | TSR, or DLSS / FSR / XeSS "Balanced" |
| Fallback if still over budget | Epic tier at 60 fps or 90 fps cap | Low tier (Lumen off) |

Tier B is the slowest hardware this guide supports at 120 fps with Lumen. For GTX 10xx cards and integrated GPUs, use the **Low** tier (Lumen off) and aim for 60–120 fps.

---

## 2. Budgets

### 2.1 GPU budget: 8.33 ms, designed for 7.3 ms

These are starting splits. Check yours with `ProfileGPU` and `stat gpu` **with async compute off** (`r.Lumen.AsyncCompute 0`). Async overlap makes the pass timings unreliable. With async on, the real total is lower than the sum.

| Pass | Tier A High (1440p @ ~62%) | Tier B Medium (1080p @ ~62%) |
|---|---|---|
| Nanite visibility buffer + base pass (materials) | 1.6 ms | 1.6 ms |
| Non-Nanite geometry (skeletal meshes, translucent prepass) | 0.4 | 0.4 |
| Virtual Shadow Maps (marking, raster, soft-shadow filtering) | 1.3 | 1.2 |
| Lumen scene lighting + screen probe gather (GI) | 1.6 | 1.5 |
| Lumen reflections | 0.6 | 0.5 |
| Deferred lighting (direct lights) | 0.4 | 0.4 |
| Volumetric fog + sky atmosphere | 0.3 | 0.3 |
| Translucency + Niagara VFX | 0.5 | 0.5 |
| Post-processing + TSR (at output resolution) | 0.6 | 0.5 |
| **Sum** | **7.3 ms** | **6.9 ms** |
| Headroom (spikes, driver, OS) | ~1.0 ms | ~1.4 ms (weaker GPU, more variance) |

Epic's reference point: Lumen **High** is budgeted at **4 ms at 1080p on current consoles for 60 fps** (GI + reflections). At 120 fps you get about half of that, so the Lumen internals are cut further in the 120 fps profile and the lower internal resolution does the rest.

### 2.2 CPU budget (measured on the Tier B CPU; Tier A then has headroom)

`stat unit` shows *Game*, *Draw* (render thread), *RHIT* and *GPU*. The frame time is the **highest** of these, not the sum, because the threads run in parallel.

| Thread | Budget | Typical split |
|---|---|---|
| Game thread | **≤ 6.5 ms** | Gameplay ticks 2.0 · Animation 1.0 · Physics 1.0 · Character movement 0.8 · AI/navigation 0.5 · UI 0.5 · Streaming/GC 0.4 · Other 0.3 |
| Render thread | **≤ 6.0 ms** | Visibility/culling 1.5 · Mesh draw commands 2.5 · Shadow setup 1.0 · Other 1.0 |
| RHI thread | ≤ 5.0 ms | Driven by non-Nanite draw calls and PSO state changes |

### 2.3 Content budgets (per frame, in the worst gameplay view)

| Item | Tier A High | Tier B Medium | How to check |
|---|---|---|---|
| Non-Nanite mesh draw calls | ≤ 2,500 | ≤ 1,800 | `stat RHI` (DrawPrimitive calls), `stat SceneRendering` |
| Skeletal meshes animating at full rate | ≤ 20 | ≤ 12 | `stat anim`, Animation Budget Allocator debug |
| Shadow-casting local lights visible | ≤ 8 | ≤ 6 | Light complexity view |
| Active Niagara systems | ≤ 60 | ≤ 40 | `stat Niagara`, `fx.Niagara.Debug.*` |
| Overlapping translucent layers | ≤ 3 | ≤ 2 | Quad Overdraw view |
| Base pass instructions (common materials) | ≤ 250 | ≤ 250 (same materials) | Material Stats, Shader Complexity view |
| Ticking actors | ≤ 300 | ≤ 300 | `stat Game`, `dumpticks` |
| Awake simulated physics bodies | ≤ 200 | ≤ 150 | `stat physics`, Chaos Visual Debugger |
| Synchronous traces per frame | ≤ 400 | ≤ 300 | Collision Analyzer |
| Characters with simulated cloth | ≤ 6 | ≤ 4 | `stat anim`, Insights |
| Actors loaded at once (World Partition) | ≤ 25,000 | ≤ 15,000 | `obj list class=Actor` |
| Landscape paint layers per component | ≤ 4 | ≤ 4 | Landscape mode layer visualizers |

### 2.4 Memory budget

**VRAM on 8 GB cards (Tier A):**

| Consumer | Budget | Control |
|---|---|---|
| Texture streaming pool | 2.5 GB | `r.Streaming.PoolSize` (TextureQuality tier) |
| Render targets (1440p, TSR history, Lumen, VSM) | ~1.0 GB | Resolution, TSR history 100% |
| Nanite streaming pool | 512 MB | `r.Nanite.Streaming.StreamingPoolSize` |
| VSM physical pages (4096 × 64 KB) | 256 MB | `r.Shadow.Virtual.MaxPhysicalPages` |
| Lumen surface cache + SDFs | 300–500 MB | Mesh distance field resolution, card count |
| GPU Scene, geometry, non-Nanite buffers | 0.7–1.0 GB | LODs, instance counts |
| Windows, browser, Discord, overlays | ~1.0 GB | Not under your control, so reserve it |
| **Target total** | **≤ 7.2 GB** | Check with `stat RHI`, `rhi.DumpMemory`, `memreport -full` |

**System RAM (16 GB):** keep the game's working set at **≤ 10 GB**. Windows and background apps take 3–5 GB. Past about 12 GB the OS starts paging, which causes random hitches.

---

## 3. Install the 120 fps profile

1. Copy `Config/DefaultEngine.ini`, `Config/DefaultGame.ini` and `Config/DefaultScalability.ini` into your project (see `Config/README.md`).
2. **Replace** your project's `DefaultScalability.ini` with `Config/Profiles/120FPS/DefaultScalability.ini`.
3. **Merge** `Config/Profiles/120FPS/DefaultEngine_120FPS.ini` into `DefaultEngine.ini`, section by section. It adds dynamic resolution (8.33 ms), Lumen async compute, the animation budget and Slate invalidation.
4. Copy `Config/Profiles/120FPS/DefaultGameUserSettings.ini` to `Config/`. It sets the 120 cap, VSync off and dynamic resolution on.
5. Enable these plugins: **Animation Budget Allocator**. Optional: **NVIDIA DLSS/Streamline + Reflex**, **AMD FSR**, **Intel XeSS**.
6. Delete `Saved/Config`, restart the editor and let the shaders recompile.
7. Check **Project Settings → Rendering**:
   - Nanite on, Virtual Textures on, Generate Mesh Distance Fields on
   - Dynamic GI = Lumen, Reflections = Lumen, Shadow Map Method = Virtual Shadow Maps
   - Support Hardware Ray Tracing **off**
   - Allow Static Lighting **off** (fully dynamic)
   - Substrate **off**, unless the art direction needs it (profile it)
8. Check every **Post Process Volume**. The Lumen settings in a PP volume multiply the scalability cost:
   - *Lumen Scene Detail*, *Final Gather Quality*, *Reflection Quality* and *Max Trace Distance* at default (1.0 and 200 m or less)
   - *Lumen Scene Lighting Update Speed* and *Final Gather Lighting Update Speed* at 1.0
   - Any value above 1 undoes the 120 fps profile for everything inside that volume.

---

## 4. Measure first

Always profile a **Test** or **Shipping** build. Development builds add about 30% variance (Intel).

| Question | Command / tool |
|---|---|
| Am I CPU- or GPU-bound? | `stat unit`, `stat unitgraph`. The highest of Game, Draw, RHIT and GPU is the limit |
| Which GPU pass is expensive? | `ProfileGPU` (Ctrl+Shift+,), `stat gpu`, `r.Lumen.AsyncCompute 0` while measuring |
| Nanite | `stat nanite`, Show → Visualize → Nanite (Triangles, Overdraw, Evaluate WPO) |
| Lumen | Show → Visualize → Lumen (Overview, Surface Cache, Card Placement) |
| VSM | Show → Visualize → Virtual Shadow Map (Cached Pages, Invalidation), `r.ShaderPrint 1` + `r.Shadow.Virtual.ShowStats 1` |
| Game thread detail | Unreal Insights: `-trace=default,gpu,frame,memory,loadtime -statnamedevents` |
| Hitches | `stat dumphitches`, Insights timing view, `stat psocache` (PSO misses) |
| Draw calls | `stat RHI`, `stat SceneRendering`, `stat InitViews` |
| Memory | `stat streaming`, `stat RHI`, `memreport -full`, `rhi.DumpMemory` |
| Resolution chosen by dynamic resolution | `stat DynamicRes`, or `r.DynamicRes.OperationMode 0` + `r.ScreenPercentage 62` for a fixed comparison |

**Workflow:** pick the 3 worst views in your game (dense combat, open vista, interior full of lights). Record them with a Sequencer camera so every run is identical. Fix the biggest line item, re-measure, and repeat.

---

## 5. Nanite

Nanite removes most draw call and LOD cost, so the render thread becomes cheap. It still has a GPU cost that depends on materials, overdraw and WPO.

1. **Use Nanite for every opaque or masked static mesh**, including foliage and small props. Nanite only works with that kind of geometry.
   - Not supported: translucent meshes, decals, most skeletal meshes (Nanite skinning in 5.5+ is still experimental).
   - Landscape: use Nanite landscape (5.3+). It also makes landscape shadows cheaper in VSM.
2. **Prefer opaque materials.** Masked, two-sided, WPO and pixel depth offset force Nanite's *programmable raster*, which costs about 20–30% more raster time for foliage (Epic's figure). For foliage, modeled opaque leaves often beat masked cards.
3. **WPO Disable Distance on every mesh or foliage type that uses WPO.** This is the most important Nanite + VSM setting for foliage. WPO invalidates shadow cache pages every frame. Also turn off *Evaluate World Position Offset* on meshes that don't need it. Verify with Visualize → Nanite → Evaluate WPO.
4. **Avoid pixel depth offset** on Nanite materials.
5. **Control overdraw.** Heavy kitbashing (many meshes stacked inside each other) makes Nanite rasterize hidden triangles. Check Visualize → Nanite → Overdraw and delete hidden geometry.
6. **Keep ≤ 3 material slots per mesh.** Nanite shades one material bin at a time, so fewer unique materials on screen means a faster base pass.
7. **Foliage:** turn on *Preserve Area* (5.2+) so distant foliage doesn't thin out, which avoids raising density to compensate.
8. **Displacement / tessellation:** leave off unless it's a hero feature.
9. **Streaming pool:** 512 MB. If `stat nanite` shows pool pressure (LOD pop, blurry geometry), raise it, and account for that against the VRAM budget.
10. **Fallback meshes:** keep them reasonable. They're used for collision, and for Lumen/ray tracing when Nanite isn't available.
11. **Per tier:** `r.Nanite.MaxPixelsPerEdge` = 1 (High) and 1.5 (Medium) is already in the profile.

---

## 6. Lumen

The profile uses **software Lumen**. It traces against the global SDF only at High and Medium, and adds mesh SDF detail tracing at Epic. Lumen stays on at Medium.

### 6.1 Settings in the profile, and why

| Setting | High | Medium | Why |
|---|---|---|---|
| `r.Lumen.DiffuseIndirect.Allow` | 1 | 1 | Keeps the look. Lumen GI is never turned off above Low |
| `r.Lumen.TraceMeshSDFs.Allow` | 0 | 0 | Global SDF tracing only (~cheapest). Indoor games on Tier A can try 1 |
| `ScreenProbeGather.DownsampleFactor` | 32 | 32 | Fewer probes. Dynamic resolution already scales the probe count |
| `ScreenProbeGather.IntegrateDownsampleFactor` | 2 | 2 | 5.6+: much cheaper integration |
| `ScreenProbeGather.StochasticInterpolation` | 1 | 1 | AMD measured ~30% faster with little visual loss |
| `ScreenProbeGather.SpatialFilterNumPasses` | 2 | 1 | AMD recommends 1–2 instead of 3 |
| `LumenScene.Radiosity.UpdateFactor` / `DirectLighting.UpdateFactor` | 96 / 48 | 128 / 64 | Updates the surface cache less often. At 120 fps the update rate is still high in real time |
| `Reflections.DownsampleFactor` / `MaxRoughnessToTraceClamp` | 2 / 0.4 | 2 / 0.3 | Rough surfaces reuse GI instead of tracing reflection rays |
| Async compute (`LumenScene.Lighting`, `DiffuseIndirect`, `Reflections`) | on | on | Overlaps Lumen with raster passes |
| Hardware ray tracing | off | off | Cheaper on 8 GB cards and saves BVH memory (AMD: ~1.2 ms) |

### 6.2 Content rules for Lumen

- **Wall thickness ≥ 10 cm.** Thinner walls leak light, and people then raise quality to hide the leaks.
- **Turn off Affect Distance Field Lighting** on grass, small debris and props smaller than about 30 cm. They add SDF update cost but no visible GI.
- **Avoid huge merged meshes and extreme aspect ratios.** They get poor surface cache cards. Check Visualize → Lumen → Card Placement.
- **Don't light scenes with emissive.** Lumen picks it up as noise. Use real lights for main lighting.
- **Sky light:** if the time of day changes, use real-time capture with time slicing (`r.SkyLight.RealTimeReflectionCapture.TimeSlice=1`).
- **Glossy-heavy scenes** (wet streets, glass towers): Lumen reflections are the most variable Lumen cost. If Medium misses budget, set `r.Lumen.Reflections.Allow=0` in `[ReflectionQuality@1]` first (about 1 ms saved). Then place a few **Sphere Reflection Captures** in key areas so SSR has a fallback.
- **Post Process Volumes:** keep the Lumen settings at defaults (section 3, step 8).

---

## 7. Upscaling, dynamic resolution, frame generation

### 7.1 TSR (default)

- TSR's cost depends on **output** resolution (Epic: ~0.43 ms at 4K from 50%). Keep `r.TSR.History.ScreenPercentage=100`, because 200% makes the history pass about 4× more expensive.
- Epic's recommended screen percentages: **1440p → 58–66%**, **1080p output → up to 100%**. Don't go below 50% unless the output is above 4K.
- Optional for competitive games: `r.TSR.Velocity.WeightClampingSampleCount=2` gives less blur in motion.

### 7.2 DLSS, FSR and XeSS (optional plugins)

- **NVIDIA** (RTX cards): DLSS Super Resolution in *Quality* or *Balanced* often looks better than TSR at the same internal resolution and moves the upscale cost onto tensor cores.
- **AMD FSR** (any GPU) and **Intel XeSS** (any GPU, fastest on Arc).
- Show the upscaler as a menu option. Keep TSR as the default for the most consistent image.

### 7.3 Dynamic resolution (already configured)

`r.DynamicRes.FrameTimeBudget=8.33`, minimum 50%, maximum 100%, 10% GPU headroom. Calm scenes render near native and heavy scenes lower the resolution instead of dropping frames. Dynamic resolution only reacts to the **GPU**. It can't fix a CPU-bound frame (section 12).

If you offer several frame caps (60/90/120/144), update the budget from code. It must use **SetByCode**, because the ini value has higher priority than SetByGameSetting:

```cpp
// MyGameUserSettings.cpp
void UMyGameUserSettings::SetTargetFrameRate(float TargetFPS)
{
    SetFrameRateLimit(TargetFPS);
    if (IConsoleVariable* Budget = IConsoleManager::Get().FindConsoleVariable(TEXT("r.DynamicRes.FrameTimeBudget")))
    {
        // Leave the ~10% TargetedGPUHeadRoom to the engine; pass the raw frame time.
        Budget->Set(1000.f / FMath::Max(TargetFPS, 30.f), ECVF_SetByCode);
    }
    ApplySettings(false);
}
```

### 7.4 Frame generation (DLSS FG, FSR FG, XeSS FG)

Frame generation doubles the frames on screen but **not** responsiveness, and it adds latency. Per the definition in section 0 it doesn't count toward "stable 120".

- Tier A: a real 120 fps is the goal. Frame generation is optional, for 240 Hz displays.
- Tier B: frame generation from a stable **≥ 60–70 fps** base can reach 120 on screen. Always pair it with **Reflex** or **Anti-Lag 2**, and label it clearly in the menu.

---

## 8. Virtual Shadow Maps and lights

VSM is cheap when its **cache** works and expensive when something keeps invalidating pages.

1. **Stop invalidations.** Check Show → Visualize → Virtual Shadow Map → Invalidation. The usual sources:
   - **WPO foliage:** set WPO Disable Distance (section 5.3).
   - **Moving meshes that barely move:** set the primitive's *Shadow Cache Invalidation Behavior*. Use *Rigid* for movable-but-mostly-static objects and *Static* when their WPO shouldn't update shadows.
   - **A moving sun:** time of day invalidates the whole directional light cache every frame. Rotate the sun in small steps every 0.5–1 s instead of continuously. The profile also applies `ResolutionLodBiasDirectionalMoving`.
   - **Nanite streaming:** leave `r.Nanite.VSMInvalidateOnLODDelta` at its default.
2. **Don't lower shadow resolution twice.** VSM resolution already follows the *internal* pixel density, so at ~62% screen percentage shadows cost less automatically. That's why the 120 fps profile uses a *smaller* resolution LOD bias (High 0.5, Medium 1.0) than the 60 fps profile.
3. **Page pool:** 4096 pages (256 MB) on High and 2048 on Medium. If you see the "VSM page pool overflow" warning or flickering shadows, raise it. Don't hide it with a higher bias.
4. **Local lights:**
   - Turn *Cast Shadows* off on fill and bounce lights. Lumen already provides indirect light.
   - Keep attenuation radius tight, and set *Max Draw Distance* and *Max Distance Fade Range* on every light.
   - Prefer **spot lights** to point lights: a shadowed point light renders 6 directions.
   - Use **contact shadows** for small detail lights instead of full shadows.
   - Stay within 6–8 shadowed local lights on screen.
   - Soft-shadow samples for local lights are at 2 (AMD: 8 → 2 is visually almost identical).
5. **Non-Nanite meshes in VSM** (skeletal meshes, non-Nanite statics) are the expensive path. Convert what you can to Nanite. Use LODs and a lower *Shadow LOD* on the rest.
6. **Many shadowed lights** (night city, clubs): try **MegaLights** (5.5+, experimental, beta in 5.6). It lights and shadows many lights at a roughly fixed cost. Profile it on Tier B before relying on it.
7. **Short view-distance games** (indoor, top-down): lowering `r.Shadow.Virtual.Clipmap.LastLevel` from 22 to about 18–20 drops distant clipmap levels.

---

## 9. Materials and shaders

Medium keeps **High material quality** (`r.MaterialQualityLevel=1`), so the materials themselves have to be efficient:

- **Budgets:** ≤ 250 base-pass instructions and ≤ 10 texture samples for common materials. Hero materials can use more. Check with Material Stats and the Shader Complexity view.
- **Pack textures** (ORM = occlusion, roughness, metallic in one texture) and use **shared samplers**.
- Use material **instances**, not unique materials. Limit **static switches**, because every combination is a separate shader and PSO, which means more compile hitches (section 14).
- **Landscape:** ≤ 4 layers per component, use a **Runtime Virtual Texture** for layer blending, and use Nanite landscape.
- **Two-sided** only where it's needed. **Masked** only where it's needed (section 5.2).
- **Quality Switch nodes:** use them for invisible savings (for example an extra detail normal) but never for a visibly different look on Medium.
- **Substrate:** off unless the art direction needs it. Profile the base pass if it's on.

---

## 10. Translucency, VFX, fog, post

- **Translucency** is the classic 120 fps killer: overdraw at full cost with no Nanite.
  - Check with the Quad Overdraw view and stay within 2–3 overlapping layers.
  - Particles: use the *Volumetric NonDirectional* lighting mode. *Surface ForwardShading* is expensive, so keep it for hero glass only.
  - Turn on Separate Translucency (default) and keep large smoke sprites few and big, not many and small.
- **Niagara:**
  - Use **GPU simulation** above about 1k particles, and **fixed bounds**.
  - Assign every system an **Effect Type** with scalability: distance culling, instance-count caps and **budget scaling**.
  - Enable component **pooling** (Auto Release) for anything spawned often.
  - The profile's `fx.Niagara.QualityLevel` and `r.EmitterSpawnRateScale` per tier only work if the emitters define scalability overrides.
- **Fog:**
  - Volumetric fog stays on at Medium: 16 px grid at internal resolution, which is cheap.
  - For local fog use **Local Fog Volumes** (5.3+) instead of heterogeneous volumes.
- **Post:**
  - Lens flares off by default.
  - Depth of field only in cinematics or aiming, not during gameplay.
  - Motion blur stays on (it's cheap and at 120 fps it's subtle).
  - Most post passes run at internal resolution, so they cost less at 120 fps.

---

## 11. Auto-detect and the settings menu

### 11.1 Calibrate the benchmark to your tiers

1. On a **Tier B** PC and a **Tier A** PC, run `synthbenchmark` in the console and note the **GPU index**.
2. In `[ScalabilitySettings]` of the 120 fps `DefaultScalability.ini`, set the thresholds so that Tier B lands on **1 (Medium)** and Tier A lands on **2 (High)**. For example, if Tier B scores 180 and Tier A scores 320, use `"GPU 120 250 600"`.
3. On first launch, run the benchmark and clamp the texture tier by VRAM:

```cpp
void UMyGameInstance::ApplyFirstLaunchScalability()
{
    UGameUserSettings* Settings = UGameUserSettings::GetGameUserSettings();
    if (Settings->GetLastGPUBenchmarkResult() > 0.f) { return; } // already done

    Settings->RunHardwareBenchmark();
    Settings->ApplyHardwareBenchmarkResults();

    // 6 GB cards: keep textures at Medium even if the GPU scores High.
    FTextureMemoryStats MemStats;
    RHIGetTextureMemoryStats(MemStats);
    const int64 VRAMMB = MemStats.DedicatedVideoMemory / (1024 * 1024);
    if (VRAMMB > 0 && VRAMMB < 7000)
    {
        Settings->SetTextureQuality(FMath::Min(Settings->GetTextureQuality(), 1));
    }

    Settings->SetFrameRateLimit(120.f);
    Settings->SetDynamicResolutionEnabled(true);
    Settings->ApplySettings(false);
}
```

### 11.2 What to expose in the menu

- The overall preset (Low / Medium / High / Epic), plus the individual groups.
- **Frame cap** (60 / 90 / 120 / 144 / unlimited), wired to `SetTargetFrameRate` (section 7.3).
- **Dynamic resolution** on/off, and a manual resolution scale when it's off.
- **Upscaler** (TSR / DLSS / FSR / XeSS) and **frame generation** (off by default).
- **VSync** and **Reflex / Anti-Lag**.

---

## 12. CPU

At 120 fps the CPU usually hits the limit before the GPU does, especially on the i5-10400 and Ryzen 5 3600. Dynamic resolution can't help here.

### 12.1 Game thread

**Ticking**
- Default every actor and component to `PrimaryActorTick.bCanEverTick = false`. Turn ticking on only where it's needed.
- Use `SetActorTickInterval()` or `TickInterval` for anything that doesn't need every frame (AI perception, UI refresh, gameplay checks). At 120 fps, "every frame" means 120 calls per second.
- Replace polling with events, timers and delegates. Move Blueprint `Tick` logic in hot paths to C++.
- Use the **Significance Manager** to score actors by distance, visibility and importance. Lower the tick rate, turn off effects and simplify AI for insignificant ones.

**Animation**
- Enable the **Animation Budget Allocator**, with `a.Budget.BudgetMs=1.0` already in the profile, and use `USkeletalMeshComponentBudgeted`.
- On skeletal meshes: `VisibilityBasedAnimTickOption = OnlyTickPoseWhenRendered`, `bEnableUpdateRateOptimizations = true` (URO is enabled globally in the base config).
- In Anim Blueprints, use *Blueprint Thread Safe Update Animation* and Property Access, and keep the Event Graph empty. That lets the animation update run on worker threads.
- Modular characters: use **Leader Pose Component**, not Copy Pose.
- Crowds: use the **Animation Sharing** plugin or **Mass** (vertex-animated crowds).
- Skeletal mesh LODs with bone reduction. The profile's `r.SkeletalMeshLODBias` handles Medium.

**Physics and movement**
- Set `bGenerateOverlapEvents = false` by default, and use simple collision (never *complex as simple* on moving objects).
- **CharacterMovementComponent** is expensive for each character. Distant AI should use simplified movement, lower tick rates or Mass.
- 5.6+: optionally turn on `s.GroupedComponentMovement.Enable=1` (commented out in the profile).

**AI and navigation**
- Time-slice EQS queries and raise perception update intervals.
- NavMesh runtime generation: use *Dynamic Modifiers Only* where you can.

**UI**
- `Slate.EnableGlobalInvalidation=1` is in the profile.
- Wrap HUD parts in **Invalidation Boxes** and use **Retainer Boxes** for widgets that animate rarely.
- Remove UMG property bindings, which run every frame, and update widgets from events.

**Spawning**
- Pool projectiles, VFX and pickups. `SpawnActor` and `Destroy` in combat cause hitches and GC pressure.

### 12.2 Render thread and RHI

- Nanite everywhere possible (section 5) removes most draw calls.
- For repeated non-Nanite meshes, use **ISM/HISM**. Auto-instancing (`r.MeshDrawCommands.DynamicInstancing`) is pinned on.
- Use **HLOD** (World Partition HLOD layers: Instanced or Merged) for distant content.
- Set cull distances (Cull Distance Volumes, per-instance cull distance for foliage) on small non-Nanite props.
- Keep the number of dynamic *movable* primitives down, because each one updates GPU Scene every frame.
- Parallel rendering cvars are pinned on in the base `DefaultEngine.ini`.

---

## 13. Streaming and memory

- **World Partition:** size loading ranges so the NVMe streaming never blocks. Use HLODs for everything outside the loading range. Use Data Layers for gameplay variants.
- **No synchronous loads during gameplay.** Replace `LoadObject`, hard references and Blueprint cast chains with **soft references + async loading** (`FStreamableManager`, Asset Manager bundles). The Unreal Insights *Asset Loading* track shows sync loads.
- The async loading budgets in the base config (3 ms per frame) keep streaming inside the frame budget.
- **Textures:**
  - Max 2K for props; 4K only for hero or large surfaces, preferably as Virtual Textures.
  - Use the correct compression: BC7 for color, BC5 for normals, BC4 for masks.
  - Assign texture groups so `r.Streaming.PoolSize` per tier actually has an effect.
  - Avoid *Never Stream* except for UI.
- **8 GB VRAM:** follow the table in section 2.4. `r.Streaming.LimitPoolSizeToVRAM=1` is on. If `stat streaming` shows *Over Budget*, reduce texture sizes. Don't raise the pool beyond what fits.
- **16 GB RAM:**
  - Keep the working set ≤ 10 GB.
  - Unload menu assets in gameplay.
  - Check audio: stream long files, and don't keep big banks resident (*Retain on Load* only for short, frequent sounds).
  - Watch `memreport -full` for duplicate assets.

---

## 14. Hitches

At 120 fps a single 30 ms hitch is 3–4 dropped frames, and players notice it far more than a lower average.

1. **Shader/PSO compilation.** The base config enables PSO precaching and a bundled PSO cache. Record the cache before release:
   1. Package a build and launch it with `-logPSO`.
   2. Play through every level, weapon, VFX and UI screen.
   3. Collect the `.rec.upipelinecache` files and the `.shk` files from the cook.
   4. Run `UnrealEditor-Cmd.exe <Project> -run=ShaderPipelineCacheTools expand <*.rec.upipelinecache> <*.shk> <Out>.spc`.
   5. Put the `.spc` file in `Build/Windows/PipelineCaches/` and repackage.
   6. On loading screens, call `r.ShaderPipelineCache.SetBatchMode fast`. Use `background` in menus.
   7. Verify with `stat psocache`: runtime misses should be near 0.
2. **Streaming:** no sync loads (section 13). Pre-stream the next area with World Partition streaming sources.
3. **Garbage collection:**
   - The base config sets a 30 s interval, incremental BeginDestroy and parallel GC.
   - Call `GEngine->ForceGarbageCollection(true)` during loading screens and cutscene cuts.
   - Pool objects so there's less garbage to begin with.
4. **First-use VFX and audio:** pre-warm Niagara systems (pooling with warm-up) and pre-load combat sounds.
5. **Spawning:** pool anything that's spawned (section 12.1).

---

## 15. Frame pacing and latency

- **Frame cap at 120** (`FrameRateLimit`). Use one limiter only: don't combine `t.MaxFPS`, VSync and a driver cap.
- **VRR (G-Sync / FreeSync) monitors:** VSync off, cap at 120, or at refresh − 3 for 144 Hz+ monitors. This gives the smoothest pacing.
- **Fixed 120 Hz without VRR:** VSync on. Any frame over 8.33 ms then becomes a 16.7 ms frame, so the headroom from section 0 is essential.
- **Latency:** integrate **NVIDIA Reflex** (plugin) and **AMD Anti-Lag 2**. Keep `r.OneFrameThreadLag=1`. Use `r.GTSyncType=1` only if you have CPU headroom and need the lowest latency (competitive games).
- Fullscreen or windowed fullscreen both work well on DX12 (flip model). Test both.

---

## 16. Distance rendering

**Goal:** distant content should cost almost nothing while silhouettes, lighting and atmosphere still read correctly. Unreal handles distance in four layers, from near to far:

```
Nanite continuous LOD  →  non-Nanite LODs  →  culling (draw distance)  →  HLOD for unloaded cells
```

### 16.1 What Nanite does *not* make free at distance

Nanite reduces far *geometry* automatically. These costs remain and are what you tune:

- **Materials:** base-pass cost is per pixel, so a distant expensive material costs the same per pixel as a near one.
- **WPO:** keeps evaluating until *WPO Disable Distance* (section 5.3).
- **Shadows:** VSM clipmaps still cover far geometry. Caching keeps this cheap unless something invalidates it (section 8).
- **Non-Nanite meshes:** skeletal meshes, translucent meshes and particles need classic LODs and culling (below).
- **Lights:** a distant shadowed light still renders shadows unless it has a *Max Draw Distance*.

### 16.2 LODs for non-Nanite meshes

- **Skeletal meshes:** at least 4 LODs (section 19.1). **Non-Nanite static meshes:** 3–4 LODs, or assign an **LOD Group** (SmallProp, LargeProp, Foliage…) so LOD screen sizes are consistent project-wide.
- Typical screen sizes: LOD1 0.5, LOD2 0.25, LOD3 0.12, LOD4 0.06. Tune them by eye with *Show → LOD Coloration*.
- **Per tier** (already in both scalability files):
  - `r.StaticMeshLODDistanceScale` = 1.5 (Low), 1.25 (Medium), 1.0 (High and up). Values above 1 switch to lower LODs sooner.
  - `r.SkeletalMeshLODBias` = 2 / 1 / 0.
  - `r.ViewDistanceScale` scales every cull distance (0.6 / 0.85 / 1.0).
- Set **Min LOD per quality level** on heavy meshes, so Medium never streams or renders LOD0 of big non-Nanite assets.

### 16.3 Culling: draw distances

| What | Setting | Starting value |
|---|---|---|
| Small props (non-Nanite, and Nanite smaller than ~50 cm) | *Desired Max Draw Distance*, or a **Cull Distance Volume** | Size 50 cm → 30 m · 200 cm → 80 m · 500 cm → 150 m · larger → never |
| Foliage instances | Foliage Type *Cull Distance* (start/end) | Small plants 40–60 m, bushes 100–150 m, trees → HLOD |
| Landscape grass | Grass Variety *Start/End Cull Distance* | 30–60 m (Medium) / 50–80 m (High) |
| Lights | *Max Draw Distance* + *Max Distance Fade Range* | Interior 20–40 m, exterior 50–100 m |
| Niagara | Effect Type → *Max Distance* culling | Ambient 50 m, combat 150 m |
| Decals | *Fade Screen Size* | 0.01–0.02 |
| Skeletal meshes | `VisibilityBasedAnimTickOption` (section 19.4) | Stop animating when not visible |

- **Occlusion:** Nanite does its own occlusion. For non-Nanite geometry in dense interiors, rely on large occluders (walls, terrain) and keep the default HZB occlusion on.
- All draw distances are multiplied by `r.ViewDistanceScale`, so one per-tier scale adjusts the whole world.

### 16.4 HLOD and World Partition: the far distance

- **Loading range:** only cells within the World Partition loading range contain real actors. Everything beyond is shown by **HLOD** actors. Test different ranges live with:
  ```
  wp.Runtime.OverrideRuntimeSpatialHashLoadingRange -grid=0 -range=25600
  ```
- **Recommended HLOD layer setup:**

  | Ring | HLOD layer type | Notes |
  |---|---|---|
  | Just outside the loading range | **Instanced** | Keeps the original Nanite meshes as ISM. Almost no quality loss, very few draw calls |
  | Mid distance | **Merged** or **Simplified** | One mesh + baked material per cluster, Nanite enabled on the output |
  | Far distance / skyline | **Approximated** | Very low cost. 512–1024 px baked textures |

- Enable **Cast Shadow** on HLODs so distant silhouettes keep their shadows. With Nanite HLOD meshes this is cheap in VSM.
- **Starting cell sizes:** main grid cell 128 m, loading range 256–384 m (Tier B) and 384–512 m (Tier A). Streaming cost goes up with loading range, and 120 fps leaves little frame time for streaming (section 13).

### 16.5 Keep the distance looking rich at low cost

- **Sky Atmosphere aerial perspective + Exponential Height Fog** naturally hide lower distant detail. Tune the fog so the HLOD transition sits inside the haze.
- Distant trees: HLOD or **octahedral impostors** (billboards baked from many angles) beyond ~300 m.
- Distant GI: software Lumen traces within the global SDF range. Beyond it, lighting comes from the sky light, so keep a real-time or captured **Sky Light** in every outdoor level.

---

## 17. Landscape

1. **Use Nanite landscape** (5.3+) on both tiers:
   - Cheaper raster, cheaper VSM shadows, and no VSM invalidation when the landscape changes LOD.
   - **Memory caveat (Epic):** Nanite landscape streams *two* copies of the data (Nanite + regular heightmap). Check the RAM/VRAM budget from section 2.4, especially on 16 GB RAM.
   - Rebuild Nanite data before cooking (*Build → Build Nanite*). Keep `Landscape.Nanite.LiveRebuildOnModification 0` while sculpting.
2. **Component layout:** fewer, larger components mean fewer draw calls and less CPU. Use Epic's recommended sizes, for example 127×127 quads per section with 1×1 or 2×2 sections per component. In World Partition, landscape streaming proxies follow the grid.
3. **Material:**
   - **≤ 4 paint layers per component.** Every extra weightmap layer adds a full set of texture samples. Check painted layer counts in Landscape mode visualizers and clean up stray paint.
   - Use a **Runtime Virtual Texture (RVT):** the complex layer blending renders once into a virtual texture (base color, normal, roughness), so landscape shading becomes a few cheap RVT samples. Meshes can sample the same RVT to blend into the terrain.
   - Use shared samplers and texture arrays or packed textures. Add distance-based macro variation instead of more layers.
4. **Non-Nanite landscape** (if you can't use Nanite landscape):
   - Tune the Landscape actor's *LOD 0 Screen Size*, *LOD 0 Distribution Setting* and *LOD Distribution Setting*. Higher distribution means LODs drop sooner.
   - 5.5+ also adds `landscape.*NonNaniteVirtualShadowMapInvalidation*` cvars to reduce shadow invalidation from landscape LOD changes.
5. **Landscape grass** is the most common hidden landscape cost:
   - Use **Nanite, opaque** grass meshes where possible, with WPO Disable Distance set.
   - Turn off **Cast Dynamic Shadow** for short grass. This is a huge VSM saving; contact shadows and Lumen AO keep it grounded.
   - Turn off **collision** and **Affect Distance Field Lighting** on grass.
   - Set start/end cull distances (section 16.3). Density scales per tier with `grass.DensityScale`.
6. **Collision:** set *Collision Mip Level* to 1 (or use *Simple Collision Mip Level*). This gives a quarter-resolution heightfield for physics, which is cheaper and uses less memory. Turn off *Generate Overlap Events* on the landscape.
7. **Splines and roads:** landscape spline meshes should be Nanite. Don't leave thousands of spline mesh components. Bake them to static meshes or ISM (for example with PCG) for large networks.
8. **PCG:** for 120 fps, **generate at edit time** and save the result. Only use runtime generation (5.4+, GPU in 5.5+) for truly procedural worlds, and budget it within the streaming time.

---

## 18. Many actors and instancing

The CPU cost of a world scales with the number of **actors and components**, not triangles. Every actor adds tick, transform updates, overlap updates, GC work, streaming registration and possibly replication.

### 18.1 Starting budgets (Tier B CPU)

| Item | Budget |
|---|---|
| Actors loaded at once (World Partition) | ≤ 15,000–25,000 (measure with `obj list class=Actor`) |
| Ticking actors/components | ≤ 300 |
| Components moving per frame (transform updates) | ≤ 500 |
| Scene components per interactive actor | ≤ 15–20 |
| Replicated actors relevant to one client | ≤ 150 without Iris/RepGraph |

### 18.2 Pick the right representation for the count

| How many of the same thing | Use |
|---|---|
| 1–50 unique, interactive (player, bosses, doors with logic) | Regular **Actors** |
| Hundreds to hundreds of thousands, static decoration | **ISM** with Nanite meshes (Foliage tool, PCG, Packed Level Actors). With Nanite, plain ISM is enough. HISM's CPU cluster tree only helps non-Nanite LODs |
| Many *interactive but mostly idle* objects (trees you can chop, pickups, destructible props) | **Instanced Actors** (5.5+, experimental): stored as Mass/ISM data and "hydrated" into real actors only near the player |
| Hundreds to thousands of moving agents (crowds, traffic, animals) | **Mass Entity** (MassCrowd / MassTraffic) with representation LOD: skeletal mesh 0–30 m → vertex-animated static mesh 30–80 m → ISM 80–200 m → culled |
| Spawned often (projectiles, shells, VFX, pickups) | **Pooling**: reuse, never Spawn/Destroy in combat |
| Kitbashed buildings and set dressing | **Packed Level Actors** / Level Instances (auto-batched into ISM) or *Merge Actors* for non-Nanite |

### 18.3 Rules for the actors you keep

- **Mobility = Static** for everything that never moves. Static primitives don't update GPU Scene or invalidate VSM, and they're cheaper to register. *Movable* only when it really moves.
- **Shallow attachment trees:** moving a parent updates every child transform. Use sockets and fewer child components.
- **Moving many actors:** a sweep (`SetActorLocation(..., bSweep=true)`) and overlap updates on every move add up. Teleport or skip the sweep for things that don't need collision, and turn off `bGenerateOverlapEvents` (section 21.4). 5.6+: `s.GroupedComponentMovement.Enable=1` (opt-in in the profile).
- **Batch ticking:** instead of 500 actors each with its own `Tick`, register them with one **manager** (for example a `UTickableWorldSubsystem`) that loops over a tight array once per frame. This is often 5–10× cheaper.
- **Tick rate:** use `TickInterval` and the **Significance Manager** (section 12.1) so distant or unseen actors tick less often or not at all.
- **Spawning cost:**
  - Use `SpawnActorDeferred` for setup, and keep construction scripts and `BeginPlay` light.
  - Async-load classes before spawning, so there are no sync loads (section 13).
- **GC:** fewer UObjects means faster garbage collection. Pooling and ISM both reduce object count.

### 18.4 Many replicated actors (multiplayer)

- **Dormancy:** `DORM_Initial` for placed actors that rarely change, and `FlushNetDormancy` when they do.
- Set `NetCullDistanceSquared` and a low `NetUpdateFrequency` per class. Adaptive update frequency is on in the base config.
- Use the **push model** and **Iris** (5.4+) or the **Replication Graph** once more than ~100 replicated actors are relevant.

---

## 19. Animated meshes (skeletal meshes, cloth, hair, crowds)

### 19.1 Budgets

| Item | Tier A High | Tier B Medium |
|---|---|---|
| Characters animating at full rate | ≤ 20 | ≤ 12 |
| Bones at LOD0 (body) / face | ≤ 150 / ≤ 250 | same assets, rely on LOD |
| LODs per character | ≥ 4 (LOD1 −50% tris, LOD2 −75%, LOD3 −90%) | same |
| Bone influences per vertex | 8 at LOD0 hero, 4 at LOD1+ | 4 |
| Characters with cloth simulating | ≤ 6 | ≤ 4 |
| Active ragdolls | ≤ 6 | ≤ 4 |
| Hair strands (groom) | Hero character only, LOD0 | Hair cards/meshes |

### 19.2 Mesh setup

- **LODs with bone reduction:** remove fingers, face and twist bones on LOD2+. Turn off cloth, morph targets and extra bone influences on LOD1+.
- **`Component Use Fixed Skel Bounds`** (Epic): skip recalculating bounds every frame for characters whose bounds don't change much.
- **Shadows:**
  - Skeletal meshes are the expensive non-Nanite VSM path. Set a lower *Shadow LOD* / *Min LOD* for shadows.
  - Turn off **Cast Shadow** on small attachments (holsters, trinkets).
  - Use **capsule shadows** for distant characters.
- **Nanite skinned meshes** (5.5+, experimental) can make crowds of detailed characters cheaper on the GPU. Profile them before relying on them.

### 19.3 GPU skinning

- The **GPU Skin Cache** is on in the base config: each mesh is skinned once per frame instead of per pass.
- If many characters are on screen and some drop out of the cache (`r.SkinCache.SceneMemoryLimitInMB`, 128 MB by default), raise the limit carefully against the VRAM budget.
- Use **Recompute Tangents** only for LOD0 hero faces with heavy morph targets, never project-wide.
- **Morph targets:** LOD0–1 only. Strip them from lower LODs.

### 19.4 CPU: Anim Blueprints and updates

1. Use **Blueprint Thread Safe Update Animation** plus **Property Access**, and keep the *Event Graph* empty. The update then runs on worker threads.
2. Turn on **Warn About Blueprint Usage** in the Anim BP class settings to keep AnimGraph nodes on the fast path.
3. Set **`VisibilityBasedAnimTickOption`**:
   - `OnlyTickPoseWhenRendered` for NPCs.
   - `OnlyTickMontagesWhenNotRendered` where montage notifies must still fire.
4. **Update Rate Optimizations (URO):** Epic's guidance is 15 Hz or lower at appropriate distances. The **Animation Budget Allocator** (`a.Budget.BudgetMs=1.0` in the profile) does this automatically within a fixed ms budget.
5. **Modular characters:** use **Leader Pose Component** (one pose drives all parts). Copy Pose and separate Anim BPs per part multiply the cost.
6. **Expensive nodes** (Control Rig, Full Body IK, RigidBody, Look-At) should set their **LOD Threshold** so they run only at LOD0–1.
7. **Linked Anim Layers:** only link the layers that are in use. Keep state machines shallow.
8. **Motion Matching:** keep pose databases small and per-context, and limit how often searches run for background characters.
9. **Root motion** blocks parallel animation update when movement needs it. Use it only for characters that need it.

### 19.5 Crowds

- **Animation Sharing** plugin: many actors share a few animation instances.
- **Vertex Animation Textures** (AnimToTexture plugin) + ISM/Nanite for background crowds: thousands of animated characters at almost no CPU cost.
- Combine with Mass representation LOD (section 18.2).

### 19.6 Cloth (Chaos Cloth)

- **≤ 300 simulated vertices** per garment and **self-collision off** (the most expensive part of cloth). Collide against a few physics-asset capsules only.
- Turn off cloth on LOD2+ and for characters beyond ~15 m.
- 5.5+ Cloth Assets: cap quality per platform with `p.ClothAsset.MinLodQualityLevel`.
- Default cloth costs about 1–3 ms per character on consumer CPUs, so it's a major budget item at 120 fps.

### 19.7 Hair and fur (Groom)

- Use **strands** only for the hero character on High and Epic, and **hair cards** or meshes on Medium and at distance.
- Set **Groom LODs** with screen sizes: strands at LOD0, cards at LOD1+. Budget strands the same way as expensive translucency.

### 19.8 "Animated" static meshes

- Use WPO for wind or flags only with WPO Disable Distance set (section 5.3).
- Flipbooks and Niagara mesh particles are cheaper than skeletal meshes for simple repeated motion.

---

## 20. Physics simulation (Chaos)

### 20.1 Physics cost grows with frame rate

With default (synchronous) physics the solver steps **once per frame**. At 120 fps physics runs **twice as often** as at 60 fps, which doubles its CPU cost. Pick a model:

| Model | When | Settings |
|---|---|---|
| **Sync** (default in the config) | Light physics: props, a few ragdolls | Budget ≤ 1.0 ms/frame on the game thread |
| **Async physics** (experimental) | Physics-heavy games (vehicles, destruction, many bodies), networked physics | `bTickPhysicsAsync=True`, `AsyncFixedTimeStepSize=0.016667` → physics runs on its own thread at a fixed 60 Hz with interpolation. This halves the physics cost at 120 fps and moves it off the game thread. Gameplay forces must use the async physics tick callbacks. Test thoroughly |
| **Substepping** | Only when a simulation is unstable at large steps | Rarely needed at 90+ fps. Don't use it with Chaos Vehicles (use async instead) |

The base `DefaultEngine.ini` now sets sync physics, `MaxPhysicsDeltaTime=0.033333` (clamps spikes), `bDisableKinematicStaticPairs=True` and `bSupportUVFromHitResults=False`. The 120 fps add-on turns on `p.Chaos.Solver.Joint.UseSimd=1` (5.5+, up to ~15% faster joints).

### 20.2 Keep bodies asleep

- A sleeping body costs almost nothing. Set explicit **sleep thresholds on Physical Materials** so debris settles quickly.
- Turn **Start Awake** off for placed physics props.
- Don't let gameplay code wake everything: avoid needless `AddForce`/`AddImpulse` and radial forces over large radii.

### 20.3 Budgets (Tier B)

| Item | Budget |
|---|---|
| Awake simulated bodies | ≤ 150 |
| Constraints (joints, ragdoll limbs, chains) | ≤ 80 |
| Simultaneous ragdolls | ≤ 4–6 |
| Active destruction pieces | ≤ 300 |

### 20.4 Solver and CCD

- Keep project-wide solver iterations at the defaults. Raise **per body** (*Position/Velocity Solver Iteration Count*) only for the few objects that jitter.
- **CCD off by default.** Enable it per body only for fast, small simulated objects.
- **Bullets should never be physics bodies:** use hitscan traces, or `ProjectileMovementComponent` with a sweep (section 21.5).
- `p.Chaos.Solver.Deterministic`: if it's on in your engine version and you don't need bit-exact replays, turning it off can recover frame time.

### 20.5 Ragdolls

- **Simplified physics asset:** ≤ 12–15 capsule/sphyl bodies. Turn off collision between adjacent bodies, and between the ragdoll and Pawn/Camera channels.
- **Ragdoll LOD:**
  - After 3–5 s, or once asleep, freeze the ragdoll by taking a pose snapshot and turning off simulation.
  - Cap simultaneous ragdolls with a pool and freeze the oldest one first.
- Use **Physical Animation** / active ragdoll blending only on characters close to the camera.

### 20.6 Destruction (Geometry Collections)

- **2–3 cluster levels.** Raise damage thresholds so small hits don't fracture everything.
- **Always remove debris:** use *Remove on Sleep* / *Remove on Break* timers, and turn small pieces into non-colliding, non-simulating remnants.
- Render collections as Nanite / ISM. 5.6+: **Root Proxy** meshes render the intact object cheaply before it breaks.
- For **scripted** destruction (set pieces), **record it with the Chaos Cache Manager** and play it back. It costs zero simulation at runtime.

### 20.7 Vehicles

- Use Chaos Vehicles with **async physics**, simple collision (boxes and convexes) and simple wheel sweeps.
- Cap the number of AI vehicles that fully simulate. Distant traffic should use Mass (section 18.2).

### 20.8 Profiling physics

- `stat physics`, `stat chaos`
- **Chaos Visual Debugger** (record and inspect the simulation)
- Debug draw: `p.Chaos.DebugDraw.Enabled 1` + `p.Chaos.Solver.DebugDrawShapes 1`
- Unreal Insights game-thread timings

---

## 21. Collision and queries

### 21.1 Collision presets: the cheapest collision is none

| Object | Preset / setting |
|---|---|
| Decorative props, detail meshes, grass, small foliage | **NoCollision** |
| Things that only need traces (interaction highlight, camera, visibility) | **QueryOnly** on specific channels |
| Static world geometry the player walks on or hits | **BlockAll**-style profile, simple shapes |
| Simulating bodies | **Query and Physics**, simple shapes only |

### 21.2 Collision shapes, from cheapest to most expensive

1. **Box / sphere / capsule** primitives
2. **Convex hulls:** ≤ 8 hulls per mesh, ≤ 32 vertices each
3. **Auto convex** decomposition (clean it up by hand)
4. **Use Complex as Simple:** only for static world geometry where exact traces matter. **Never** for moving or simulating objects

Nanite meshes take their collision from the authored simple collision or the fallback mesh, so author simple collision for them explicitly.

### 21.3 Channels and profiles

- Create **custom object channels** (for example `Projectile`, `Interactable`, `Vehicle`) and **trace channels** (`Weapon`, `Interaction`, `Camera`) in *Project Settings → Collision*.
- Each query then tests only the objects that care. A weapon trace that ignores foliage, debris and triggers is far cheaper than one on `Visibility`.
- Build **profiles** from these channels and assign profiles, not per-object custom responses. That's easier to audit and harder to get wrong.

### 21.4 Overlap events

- **`Generate Overlap Events` off by default** on every component except real triggers. Every moving component with overlaps on runs an overlap update each time it moves.
- Triggers: use simple shapes on a dedicated trigger channel that overlaps only Pawn (or whatever should trigger it).
- Fast moving objects (projectiles): use **sweep hit results** instead of overlap events.
- Avoid actors with many overlapping components that move every frame. Merge them into one trigger shape.

### 21.5 Traces and sweeps

- Prefer **single line traces by channel**, keep them short, and keep `bTraceComplex=false`. Multi traces, sphere and capsule sweeps, and complex traces cost more. Use them only where needed.
- **Batch and defer:** for AI perception, cover checks, footstep surface checks and similar bulk queries, use **async traces**. They run in parallel and the result arrives next frame:

```cpp
// Fire-and-forget async trace; result arrives next frame via delegate.
FTraceDelegate OnTraceDone;
OnTraceDone.BindUObject(this, &UMySensor::HandleTrace);
GetWorld()->AsyncLineTraceByChannel(EAsyncTraceType::Single, Start, End,
    ECC_GameTraceChannel2 /* e.g. "Perception" */, FCollisionQueryParams(SCENE_QUERY_STAT(Perception), false),
    FCollisionResponseParams::DefaultResponseParam, &OnTraceDone);
```

- **Cache and time-slice:** check line of sight for each AI every 0.1–0.25 s, spread across frames, not every frame for every agent.
- **Budget:** ≤ 300 synchronous traces per frame on Tier B. Check with the **Collision Analyzer** (*Tools → Debug → Collision Analyzer*).

### 21.6 Character movement collision

- `CharacterMovementComponent` sweeps and checks the floor on every move, which is one of the largest per-character CPU costs.
- Distant AI: switch to **NavWalking** movement mode (follows the navmesh with no floor sweeps). Also lower the tick rate via significance and turn off `bEnablePhysicsInteraction`.
- Use RVO / Detour crowd avoidance only for agents that need it.
- Many simple agents: move them to Mass (section 18.2).

### 21.7 Debugging

- `show Collision`, `stat Collision`, the Collision Analyzer, and Player Collision / Visibility Collision view modes.
- Chaos debug draw for physics shapes (section 20.8).

---

## 22. Other systems

**Water (Water plugin)**
- Single Layer Water shading is expensive, and it's a smooth surface, so it's a Lumen reflection hotspot.
- Lower the Water Zone *render target resolution*, use fewer water bodies, and keep the water mesh LOD/tile settings coarse at distance.
- If water covers a large part of the screen, use SSR for water reflections on Medium.

**Decals**
- Many overlapping DBuffer decals add up. Set *Fade Screen Size* on every decal.
- Use **mesh decals** for large-scale grime, and scale the decal count with `r.DetailMode` per tier.

**Audio**
- **Concurrency groups** per sound type (for example gunfire 8, footsteps 6, impacts 10) plus a global voice cap (64 in the base config). Use attenuation with **virtualization**: only important loops *Play when Silent*.
- Stream music and long voice lines. Use cheap-to-decode compression (ADPCM/PCM) for very frequent short SFX.
- Keep MetaSounds graphs lean. They run on the audio render thread.

**Networking**
- Server tick at 60 Hz (base config).
- Dormancy, relevancy, push model, and Iris or Replication Graph (section 18.4).
- Client-side prediction and smoothing make 120 fps clients feel smooth with a 60 Hz server.

**AI and navigation**
- NavMesh *Runtime Generation*: **Static** or **Dynamic Modifiers Only**. Full dynamic rebuilds are expensive.
- Use **async path queries** and cap Detour crowd agents.
- Raise AI Perception update intervals and time-budget EQS queries.
- **StateTree** is generally lighter than Behavior Trees for many agents. Distant AI thinks less often via significance (section 12.1).

**Cinematics**
- Cutscenes can briefly use heavier settings (for example Epic shadows or DOF) because gameplay input isn't needed. Switch back when the cutscene ends and keep the 120 fps cap.

---

## 23. Validation

### 23.1 Test setup

- **Machines:** at least one real **Tier A** (e.g. RTX 4060 8 GB + i5-12400, 16 GB) and one **Tier B** (e.g. RTX 2060 6 GB + Ryzen 5 3600, 16 GB), with current drivers and a normal background (Steam, Discord, a browser).
- **Build:** Test configuration, with the recorded PSO cache.
- **Routes:**
  - Route 1: a 10-minute scripted Sequencer flythrough covering the worst views from section 4.
  - Route 2: 10 minutes of real play in the heaviest combat or crowd scenario.
- **Capture:**
  - Launch with `-csvprofile` or use `CsvProfile Start/Stop`, then turn the CSV into a report with `PerfReportTool`.
  - Use Unreal Insights for hitch analysis.
  - Use PresentMon / CapFrameX for independent frame-time percentiles.

### 23.2 Pass criteria (both tiers, capped at 120)

| Metric | Pass |
|---|---|
| Average fps (capped) / uncapped | 120 / ≥ 135 |
| 1% low / 0.1% low | ≥ 110 / ≥ 90 fps |
| Frames > 33 ms in gameplay | 0 |
| Average dynamic resolution | Tier A 1440p ≥ 60% · Tier B 1080p ≥ 58% |
| Frames with resolution at the 50% floor | < 10%. Otherwise the content is over budget, not the settings |
| VRAM / RAM | ≤ 7.2 GB (8 GB card), ≤ 5.5 GB (6 GB card) / ≤ 10 GB |
| `stat psocache` runtime misses | ~0 after warm-up |

Run the check on every milestone build. Performance falls off gradually as content is added, so catching it early is much cheaper.

---

## 24. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `stat unit`: Game ≈ frame time, GPU lower | Game thread bound | Section 12.1: ticks, animation budget, CharacterMovement, UI bindings |
| Draw ≈ frame time | Render thread bound | More Nanite, ISM/HISM, HLOD, cull distances |
| GPU bound, resolution pinned at 50% | Content over budget | `ProfileGPU` → biggest pass → matching section |
| Big *ShadowDepths / VirtualShadowMap* cost | Cache invalidation | WPO Disable Distance, Invalidation Behavior, sun steps (section 8) |
| Big *Lumen Screen Probe Gather* | Too many probes or updates | Check PP volume overrides (section 3, step 8). Lower `SpatialFilterNumPasses` |
| Big *Lumen Reflections* | Lots of smooth surfaces | Lower `MaxRoughnessToTraceClamp`, or disable at Medium + reflection captures |
| Big *Nanite VisBuffer* | Overdraw, masked or WPO foliage | Overdraw view, opaque leaves, WPO distance |
| Big *Translucency* | Particle overdraw | Fewer, larger sprites; lighting mode; Effect Type budgets |
| Stutter the first time something appears | PSO miss | Record the bundled cache (section 14.1), `stat psocache` |
| Periodic hitch every 30–60 s | GC | Pooling, GC during loading screens, check `gc.*` settings |
| Hitch when entering new areas | Sync load or streaming | Insights loading track, soft references, WP ranges |
| Blurry textures, "Over budget" in `stat streaming` | VRAM pool too small or textures too big | Texture sizes / groups. Don't just raise the pool on 8 GB |
| Uneven pacing even at 120 average | Double caps, no VRR | Section 15: one limiter, VRR, or VSync with headroom |
| *Physics* / *Chaos* high in the game thread | Too many awake bodies, or sync physics at 120 Hz | Sleep thresholds, ragdoll freeze, async physics at 60 Hz (section 20) |
| *UpdateOverlaps* / *MoveComponent* high | Overlap events on moving components | Turn overlaps off, NoCollision on decoration, fewer moving components (sections 18.3, 21.4) |
| Many *CharacterMovement* entries | Floor sweeps for every AI | NavWalking, significance tick rates, Mass (section 21.6) |
| *Animation* / *Worker* anim tasks high | Anim BP on the game thread, no URO | Thread-safe update, budget allocator, LOD thresholds (section 19.4) |
| Cloth takes 1–3 ms per character | Too many sim vertices or self-collision | ≤ 300 vertices, self-collision off, LOD cutoff (section 19.6) |
| Distant pop-in or HLOD transition visible | Loading range too small or HLOD too coarse | Instanced HLOD ring, fog placement (section 16.4–16.5) |
| Landscape base pass expensive | Too many layers per component | ≤ 4 layers, RVT (section 17) |
| Hitch when many actors spawn | Construction script, sync class loads | Pooling, deferred spawn, async class loading (section 18.3) |
| Shimmering at low resolution | TSR undersampled | Keep ≥ 55% at 1080p, use DLSS/XeSS on supported GPUs, fix high-frequency content |

---

## 25. Sources

- [Epic – Lumen Performance Guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-performance-guide-for-unreal-engine)
- [Epic – Temporal Super Resolution](https://dev.epicgames.com/documentation/unreal-engine/temporal-super-resolution-in-unreal-engine?lang=en-US)
- [Epic – Dynamic Resolution](https://dev.epicgames.com/documentation/unreal-engine/dynamic-resolution-in-unreal-engine)
- [Epic – Virtual Shadow Maps](https://dev.epicgames.com/documentation/en-us/unreal-engine/virtual-shadow-maps-in-unreal-engine)
- [Epic – Animation Budget Allocator](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-budget-allocator-in-unreal-engine)
- [Epic – Animation Optimization](https://dev.epicgames.com/documentation/unreal-engine/animation-optimization-in-unreal-engine?lang=en-US)
- [Epic – Incremental Garbage Collection](https://dev.epicgames.com/documentation/unreal-engine/incremental-garbage-collection-in-unreal-engine?lang=en-US)
- [Epic tech blog – Shader stuttering and PSO precaching](https://www.unrealengine.com/tech-blog/game-engines-and-shader-stuttering-unreal-engines-solution-to-the-problem)
- [AMD GPUOpen – Unreal Engine Performance Guide](https://gpuopen.com/learn/unreal-engine-performance-guide/)
- [Intel – UE5 Optimization Guide, Ch. 2](https://www.intel.com/content/www/us/en/developer/articles/technical/unreal-engine-optimization-chapter-2.html)
- [Tom Looman – UE 5.6 Performance Highlights](https://tomlooman.com/unreal-engine-5-6-performance-highlights/)
- [Tom Looman – PSO Precaching & Bundled PSOs](https://tomlooman.com/unreal-engine-psocaching/)
- [Tom Looman – Game Optimization on a Budget](https://tomlooman.com/unreal-engine-optimization-talk/)
- [Iri Shinsoj – Notes on foliage in UE5](https://medium.com/@shinsoj/notes-on-foliage-in-unreal-5-3522b6eb159f)
- [Epic – Physics Settings](https://dev.epicgames.com/documentation/en-us/unreal-engine/physics-settings-in-the-unreal-engine-project-settings)
- [Epic – Collision Overview](https://dev.epicgames.com/documentation/unreal-engine/collision-in-unreal-engine---overview)
- [Epic – Using Nanite with Landscapes](https://dev.epicgames.com/documentation/unreal-engine/using-nanite-with-landscapes-in-unreal-engine)
- [Epic – World Partition HLOD](https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition---hierarchical-level-of-detail-in-unreal-engine)
- [Epic – Skeletal Mesh Rendering Paths](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-rendering-paths-in-unreal-engine)
- [Epic – Large Numbers of Entities with Mass](https://dev.epicgames.com/community/learning/talks-and-demos/37Oz/large-numbers-of-entities-with-mass-in-unreal-engine-5)
- [Epic community – World Partition HLOD tips](https://dev.epicgames.com/community/learning/tutorials/z050/unreal-engine-5-world-partition-hlods-tips-tricks)
- [Tom Looman – UE 5.5 Performance Highlights](https://tomlooman.com/unreal-engine-5-5-performance-highlights/)
- [PerfGuard – Chaos Physics Performance](https://getperfguard.com/tutorials/chaos-physics)
- [Bryan Corell – Async collision traces](https://medium.com/@bryan.corell/using-async-collision-traces-in-unreal-engine-4-2cc312c825f5)
- [StraySpark – Mass AI crowds and traffic](https://www.strayspark.studio/blog/crowd-traffic-simulation-ue5-mass-ai)
