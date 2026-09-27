# Optimizing Lighting and Post-Processing in Unreal Engine 5

This is a practical guide to keeping direct lighting, shadows, sky/fog/clouds and post-processing cheap, for UE 5.3–5.8. Notes that apply only to 5.8 are marked **[5.8]**. For everything else that changed in 5.8, see [`UE58_Guide.md`](UE58_Guide.md).

It fits the GPU budget in [`120FPS_Guide.md`](120FPS_Guide.md) section 2.1. At 120 fps these systems share about 3.5 ms:

| Area | Budget |
|---|---|
| Direct lighting | ~0.4 ms |
| VSM shadows | ~1.2–1.3 ms |
| Lumen | ~2.1 ms |
| Fog and sky | ~0.3 ms |
| Post + TSR | ~0.5–0.6 ms |

Related guides:
- [`120FPS_Guide.md`](120FPS_Guide.md): Lumen (section 6), VSM (section 8), upscaling (section 7).
- [`Materials_Textures_Guide.md`](Materials_Textures_Guide.md): emissive, translucency lighting modes.
- [`Common_Bugs_Guide.md`](Common_Bugs_Guide.md) section 9: light leaking, shadow flicker, exposure problems.

---

## Contents

0. [How lighting and post cost works](#0-how-lighting-and-post-cost-works)
1. [Measure](#1-measure)
2. [Choose the lighting pipeline](#2-choose-the-lighting-pipeline)
3. [Light authoring rules](#3-light-authoring-rules)
4. [Shadows](#4-shadows)
5. [Global illumination and the sky light](#5-global-illumination-and-the-sky-light)
6. [MegaLights: many shadowed lights](#6-megalights)
7. [Sky, atmosphere, fog and clouds](#7-sky-atmosphere-fog-and-clouds)
8. [Reflections](#8-reflections)
9. [Post-processing](#9-post-processing)
10. [Post Process Volume hygiene](#10-post-process-volume-hygiene)
11. [Budgets](#11-budgets)
12. [Checklist](#12-checklist)
13. [Sources](#13-sources)

---

## 0. How lighting and post cost works

| System | Cost grows with |
|---|---|
| **Direct lighting** (deferred) | Number of lights × screen pixels each light's radius covers × shading model |
| **Shadows** | Number of shadow-casting lights × geometry in their range × invalidations (VSM) × filtering samples |
| **Indirect lighting** (Lumen) | Internal resolution, scalability settings, how often the scene changes |
| **Volumetrics** (fog, clouds, light shafts) | Grid or sample resolution × lights that scatter into them |
| **Post-processing** | Full-screen passes. Some run at **internal** resolution, some at **output** resolution |

The biggest savings usually come from **fewer shadow-casting lights** and **smaller light radii**, not from lowering quality settings.

---

## 1. Measure

| Tool | What it shows |
|---|---|
| View Mode → **Light Complexity** | How many lights affect each pixel. White areas mean many overlapping light radii |
| `stat gpu` / `ProfileGPU` | *Lights* (direct lighting), *ShadowDepths* / *VirtualShadowMaps*, *Lumen*, *VolumetricFog*, *PostProcessing*, *TSR*, *Bloom*, *DOF*… |
| View Mode → **Lumen** visualizations | Surface cache, card placement, scene overview |
| Show → Visualize → **Virtual Shadow Map** | Cached pages vs invalidated pages |
| **[5.8]** `r.MegaLights.Visualize.LightComplexity`, `r.MegaLights.Debug 1` | MegaLights light weights and rays per pixel |
| **[5.8]** `r.ProfileGPU.TableFormatting 0` | More readable ProfileGPU output in the log |
| Show → **Post Processing** toggles, `ShowFlag.Bloom 0`, `ShowFlag.DepthOfField 0`, … | The cost of each post effect, by turning it off and on |

Measure with async compute off (`r.Lumen.AsyncCompute 0`) when you want per-pass numbers (see `120FPS_Guide.md` section 4).

---

## 2. Choose the lighting pipeline

| Pipeline | Cost | Use when |
|---|---|---|
| **Fully dynamic: Lumen + VSM** (this repo's default) | Medium–high | Dynamic time of day, destruction, building, or fast iteration without baking |
| **[5.8] Lumen Lite** (Medium GI/Reflection quality) | About **half** of Lumen High | Lower-end PCs and handhelds that still need dynamic GI. Used automatically at Medium in the 5.8 profiles |
| **Baked lighting** (GPU Lightmass, static/stationary lights) | Lowest runtime cost | Static worlds, VR, mobile, very low-end PCs. Costs build time, memory for lightmaps, and nothing can move |
| **MegaLights** (5.4+ experimental, **production-ready in 5.8**) | Roughly fixed cost regardless of light count | Scenes with many shadowed lights (cities at night, interiors full of lamps). Works best with hardware ray tracing |
| ~~SSGI~~ | — | **Deprecated in 5.8.** Use Lumen Lite instead |

Pick one per project (or per platform) early. Changing it later means relighting every level.

---

## 3. Light authoring rules

### 3.1 Light types by cost

| Type | Relative cost | Notes |
|---|---|---|
| **Directional** | One per scene; shadows are the main cost | Keep **one** shadowed directional light (sun). A second one (moon) should not cast shadows, or should replace the sun at night |
| **Spot** | Cheapest local light | Narrow cones reduce both lighting and shadow cost |
| **Point** | A shadowed point light renders **6 directions** | Replace with a spot where the light only goes one way (wall lamps, ceiling lights) |
| **Rect** (area) | More expensive shading than spot or point | Use for key soft lights only. Use *Barn Door* settings to limit spread |
| **Sky light** | One per scene | Real-time capture costs extra (section 5.2) |

### 3.2 Per-light settings that save the most

- **Attenuation Radius** as small as possible. Cost scales with the screen area it covers. Check it with *Light Complexity*.
- **Max Draw Distance + Max Distance Fade Range** on every local light: 20–40 m indoors, 50–100 m outdoors.
- **Cast Shadows off** for fill, bounce and decorative lights. Lumen already provides the bounce light.
- **Contact Shadow Length** (small value, e.g. 0.02–0.1) instead of full shadows on small detail lights.
- **Volumetric Scattering Intensity 0** and **Cast Volumetric Shadow off** for lights that don't need to show in fog. Every light that scatters into volumetric fog adds fog cost.
- **Affect Translucent Lighting off** where translucency doesn't need that light.
- **Specular Scale 0** on pure fill lights (small saving, and fewer unwanted highlights).
- **Lighting Channels** to limit which objects a light affects. For example, character rim lights affect only channel 1.
- **Source Radius / Soft Source Radius:** bigger means softer VSM shadows, which need more filtering samples (SMRT). Keep them small on minor lights.

### 3.3 Light functions and IES profiles

- **Light functions** render an extra material pass for every light that uses one, which is expensive. Use them only on a few key lights. On 5.3+ the **Light Function Atlas** makes them cheaper for supported paths; profile before relying on it.
- **IES profiles** are a cheap texture lookup. Prefer IES over light functions for realistic lamp patterns.
- **Animated lights** (flicker, pulse): changing intensity doesn't invalidate shadows, but **moving** a shadowed light invalidates its VSM pages every frame. Keep shadowed lights still. Fake the movement with intensity or with an unshadowed light.

### 3.4 Budgets (per view, starting points)

| Item | Tier A High | Tier B Medium |
|---|---|---|
| Shadowed local lights on screen (VSM) | ≤ 8 | ≤ 6 |
| Unshadowed local lights on screen | ≤ 40 | ≤ 30 |
| Lights overlapping one pixel (Light Complexity) | ≤ 4–6 | ≤ 4 |
| Lights with light functions | ≤ 2–3 | ≤ 1–2 |
| Lights scattering into volumetric fog | ≤ 4 | ≤ 2 |

---

## 4. Shadows

The full VSM tuning is in `120FPS_Guide.md` section 8. The short version:

- **Caching is everything.** Static geometry is cached, so stop invalidations:
  - WPO Disable Distance
  - *Shadow Cache Invalidation Behavior* (Rigid/Static)
  - move the sun in small steps
  - keep shadowed lights still
- **Per tier:** the page pool, resolution LOD bias and SMRT ray counts in `DefaultScalability.ini`.
- **Small objects:** turn *Cast Shadow* off on grass, debris and tiny props, and use contact shadows plus Lumen AO to ground them.
- **Characters:** capsule shadows at distance, and a lower shadow LOD (`120FPS_Guide.md` section 19.2).
- **Distance field shadows** give cheap far shadows for the directional light, especially with a short VSM range.
- **[5.8] New options:**
  - `r.Shadow.Virtual.Nanite.AllowTessellationDirectional/Local 0`: turn off Nanite tessellation in shadows when displacement doesn't need to show in shadows.
  - `r.Shadow.Virtual.DeferredInvalidationBudget`: throttles invalidations from Nanite LOD changes.
  - *Prefiltered Distant* shadows: **experimental**, don't ship on it yet.
- **Baked lighting projects:** stationary lights (max **4 overlapping** stationary lights per area; more fall back to dynamic shadows, which is expensive). Use *Stationary Light Overlap* view mode.

---

## 5. Global illumination and the sky light

### 5.1 Lumen

Full tuning is in `120FPS_Guide.md` section 6. Lighting-specific rules:

- **Don't light rooms with emissive materials.** Emissive is picked up by Lumen as noisy GI. Use real lights for main lighting and keep emissive for small glowing details.
- **Indirect Lighting Intensity** (per light) and **Lumen Scene Lighting Update Speed** (PP volume): leave at defaults. Raising them costs frame time for everything inside the volume.
- **Interiors:** closed geometry and walls ≥ 10 cm prevent light leaking. Don't fix leaking with more lights, which costs twice.
- **[5.8] Lumen Lite at Medium:**
  - Uses an Irradiance Field final gather (`r.Lumen.FinalGatherMethod 0`), about 2× faster than High.
  - The 5.8 profiles in `Config/Profiles/UE58/` enable it by allowing Lumen at Medium.
  - GI is a bit softer and has less detail than High. Check that interiors still read correctly.
- **[5.8]** `r.Lumen.HeightFog 1` applies height fog to reflection hits, which fixes too-clear reflections in foggy scenes at a small cost. It's opt-in in `DefaultEngine_UE58.ini`.
- **[5.8]** `AGameUserSettings::IsGlobalIlluminationAllowed()`: check it before applying Lumen settings from gameplay code or PP volumes.

### 5.2 Sky light

- **Real-time capture** (for time of day) recaptures the sky every frame. Turn on **time slicing** (`r.SkyLight.RealTimeReflectionCapture.TimeSlice=1`) so the capture is spread over several frames.
- For static skies, use a **captured** (non-real-time) sky light and recapture only when the sky changes.
- Keep **one** sky light per scene.

---

## 6. MegaLights

MegaLights (**production-ready in 5.8**) samples a fixed number of lights per pixel, so hundreds of shadowed lights cost roughly the same as a few.

**When to use it**
- Scenes with **many shadowed local lights**: night cities, interiors full of lamps, neon, stage lighting.
- **Not needed** for outdoor scenes lit mostly by the sun plus a few lamps. Classic lights with VSM are cheaper there.

**Setup**
1. *Project Settings → Rendering → Direct Lighting → **MegaLights***. The editor also suggests **Support Hardware Ray Tracing**, which is recommended.
2. On 8 GB GPUs (Tier A in `120FPS_Guide.md`), hardware ray tracing costs **BVH memory** (hundreds of MB, depending on the scene). Add it to the VRAM budget before enabling.
3. If you enable MegaLights, **remove** `r.MegaLights.Supported=0` from `DefaultEngine_UE58.ini`.

**Per-light settings**
- **MegaLights Shadow Method:**
  - **Ray Tracing** (default): no per-light cost, but it uses the simplified ray tracing scene.
  - **Virtual Shadow Maps:** full Nanite detail, but a significant extra cost for each light. Only use it for hero lights.
- **Allow MegaLights** off for lights that should stay on the classic path.

**Scalability cvars**

| Cvar | Controls |
|---|---|
| `r.MegaLights.DownsampleMode` | Resolution of the lighting samples |
| `r.MegaLights.NumSamplesPerPixel` | Samples per downsampled pixel (quality vs noise) |
| `r.MegaLights.Volume.GridPixelSize` | Resolution for fog and translucency lighting |
| `r.MegaLights.FrontLayerTranslucency.SpecularOnly` | Cheaper translucency lighting |
| **[5.8]** `r.MegaLights.ScreenTraces.Quality` | Screen-space trace quality |
| **[5.8]** `r.MegaLights.LightAttenuationFalloff` | Culls lights early by power and falloff (~20% fewer samples, per Tom Looman's 5.8 notes). Set 0 if you see specular artifacts |
| `r.MegaLights.Allow 0` | Turns MegaLights off per scalability level or device profile (for example on Tier B) |

**Performance tips (Epic)**
- Tight attenuation radii and spotlight cones.
- Don't place lights inside geometry.
- Merge small light clusters into one area light.

**Limitations**
- Not with the Forward Renderer.
- No support for Water, Volumetric Clouds, Heterogeneous Volumes or Local Volumetrics.
- Quality drops (more noise) when too many lights affect the same pixel.

---

## 7. Sky, atmosphere, fog and clouds

| Feature | Cost | Tips |
|---|---|---|
| **Sky Atmosphere** | Low | LUT sample counts per tier are already in `DefaultScalability.ini` (EffectsQuality). Keep *Fast Sky LUT* and *Fast Aerial Perspective* on below Cine |
| **Exponential Height Fog** (non-volumetric) | Very low | Use it everywhere. It also hides distant LOD and HLOD transitions (`120FPS_Guide.md` section 16.5) |
| **Volumetric Fog** | Medium | Cost = grid resolution × lights that scatter into it. Grid settings are per tier (ShadowQuality). Limit scattering lights (section 3.2) |
| **Local Fog Volumes** (5.3+) | Low–medium | Use them for local mist, valleys and rooms instead of raising global volumetric fog density |
| **[5.8] Fog Screen Space Scattering** | Experimental | Approximates light scattering through fog. Don't ship on it before profiling |
| **Volumetric Clouds** | **High** | Keep the component's *View / Reflection / Shadow Sample Count Scale* at 1 or below. The default volumetric render target renders clouds at reduced resolution with temporal reconstruction; leave it on. Use a 2D sky texture or HDRI for games where clouds don't need to move or be flown through |
| **Heterogeneous Volumes** (smoke, fire volumes) | **Very high** | Cinematics only. Use Niagara sprites or flipbooks for gameplay |
| **Light shafts** (bloom/occlusion on the directional light) | Low | Keep them on. `r.LightShaftQuality` per tier |

---

## 8. Reflections

| Method | Cost | Use |
|---|---|---|
| **Lumen reflections** | Medium, varies with smooth surfaces | Default for High+ (and Medium on 5.8). Tune with `MaxRoughnessToTraceClamp` and `DownsampleFactor` per tier |
| **Screen Space Reflections** | Low | Low tier and fallback. Only reflects what's on screen |
| **Reflection Capture actors** (sphere/box) | Very low at runtime | Fallback when Lumen reflections are off. Place a few in key interiors |
| **Planar Reflections** | **Very high** (renders the scene again) | Avoid in gameplay at 120 fps. Use Lumen or SSR for water and mirrors. Use them for small mirrors in cutscenes only |
| **Scene Capture 2D/Cube** for mirrors or cameras | **High** (renders the scene again) | Low resolution, update on demand (`bCaptureEveryFrame=false` + `CaptureScene()` when needed), limited show flags |

Rough, dull materials are cheap in Lumen reflections: they reuse the GI above the roughness clamp. Lots of polished floors and glass is what costs.

---

## 9. Post-processing

### 9.1 Where post passes run

In the default pipeline:
- **Depth of field** and **motion blur** run **before** the upscaler, at **internal** resolution. They get cheaper with dynamic resolution.
- **Bloom, tonemapping, color grading, film grain and post-process materials placed after tonemapping** run **after** the upscaler, at **output** resolution. They cost the same at 50% or 100% screen percentage, so keep them lean at 1440p and 4K output.
- **TSR** itself scales with output resolution (`120FPS_Guide.md` section 7.1).

### 9.2 Effects: cost and settings

| Effect | Cost | Recommendation |
|---|---|---|
| **Bloom: Standard** | Low | Keep it. Quality per tier (`r.BloomQuality`) |
| **Bloom: Convolution** (FFT) | **High** | Cinematics only. It's the Bloom *Method* setting in the PP volume |
| **Lens flares** (image-based) | Low–medium | Off by default in this repo's config. Enable per volume if the art needs it |
| **Auto Exposure** (histogram) | Low | Always set **Min/Max EV100** per area. **Manual** exposure is cheaper and more consistent for fixed-lighting levels |
| **Local Exposure** (5.1+) | Low–medium | Useful for high-contrast scenes. Measure its pass. Keep it off when the lighting doesn't need it |
| **Motion blur** | Low–medium | Keep it modest (amount ~0.3–0.5). At 120 fps it's naturally subtle. Quality per tier |
| **Depth of field (Cinematic / Gather)** | Medium–high | **Off during gameplay.** Use it in cutscenes, aiming and photo mode. **[5.8]** `r.DOF.PreferLowerBitDepth 1` on Low/Medium (in the 5.8 profiles) |
| **[5.8] Accumulation DOF** | Offline | For Movie Render Graph renders, not real-time gameplay |
| **SSAO** | Low–medium | Lumen already provides short-range AO. Don't stack SSAO on top of Lumen. SSAO only matters on non-Lumen tiers |
| **Screen Space GI** | — | **Deprecated in 5.8.** Use Lumen / Lumen Lite |
| **Chromatic aberration, vignette, sharpen** | Very low | Fine to use |
| **Film grain** | Low | Fine. Measure at 4K output |
| **Color grading / LUT, tonemapper** | Very low | Fine. **[5.8]** CombineLUTs runs on async compute |
| **Panini projection** | Medium | Avoid unless you need very wide FOV correction |
| **Custom Depth / Stencil** (outlines, x-ray, highlights) | Medium: renders marked objects again | Only mark objects that need it, only while they need it (toggle `Render CustomDepth Pass` at runtime) |

### 9.3 Post-process materials

- Each blendable **post-process material is at least one full-screen pass**. After tonemapping it runs at output resolution, so its cost doesn't drop with dynamic resolution.
- **Budget:**
  - ≤ 2–3 PP materials active at once
  - ≤ 100 instructions each
  - ≤ 3 *SceneTexture* reads each
- Pick the **Blendable Location** carefully:
  - *Before Tonemapping* for effects that need HDR scene color.
  - *After Tonemapping* for stylized overlays.
  - *Replacing the Tonemapper* only if you really replace it.
- Turn PP materials **on only when needed** (damage vignette, underwater, scan effects). Don't leave them at weight 0 with the material still bound. Use **Blend Weight 0 plus removing it from the array**, or toggle the volume.
- **Outlines:** a Custom Depth/Stencil PP outline costs one pass plus the custom depth render. **[5.8]** Substrate Toon shading is experimental. Don't ship on it before profiling.

### 9.4 Anti-aliasing and upscaling

TSR, DLSS, FSR, XeSS and dynamic resolution are covered in `120FPS_Guide.md` section 7. **[5.8]** Dynamic resolution is supported on PC (DX12, Vulkan).

---

## 10. Post Process Volume hygiene

1. **One global (Infinite Extent / Unbound) PP volume** per level with the project defaults: exposure range, bloom and grading.
2. **Local volumes override only what they need.** Tick only those properties' checkboxes. Everything unticked inherits from the global volume.
3. **Never raise Lumen quality in PP volumes** (Final Gather Quality, Lumen Scene Detail, Reflection Quality, Max Trace Distance, update speeds). They multiply the scalability cost for everything inside the volume, and players can't lower them from the settings menu (`120FPS_Guide.md` section 3, step 8).
4. **Scalability first:** quality differences between Low/Medium/High belong in `DefaultScalability.ini`, not in PP volumes. PP values are the same on every preset.
5. **Blend Radius** smooth transitions are cheap, but large overlapping volumes with many ticked properties make lighting hard to debug. Keep them few and well named.
6. **Cinematics:** heavier post (cinematic DOF, convolution bloom) goes in cutscene-only volumes or Sequencer PP tracks, and is disabled when gameplay resumes.

---

## 11. Budgets

For the 120 fps profile. Starting budgets to measure against, from `120FPS_Guide.md` section 2.1:

| Pass | Tier A High (1440p out) | Tier B Medium (1080p out) |
|---|---|---|
| Direct lighting (*Lights*) | ≤ 0.4 ms | ≤ 0.4 ms |
| Shadows (VSM) | ≤ 1.3 ms | ≤ 1.2 ms |
| Lumen GI + reflections | ≤ 2.2 ms | ≤ 2.0 ms (**[5.8]** Lumen Lite: expect about half of High) |
| Volumetric fog + sky + clouds | ≤ 0.3 ms | ≤ 0.3 ms |
| Post-processing + TSR | ≤ 0.6 ms | ≤ 0.5 ms |
| Post-process materials | ≤ 0.15 ms | ≤ 0.1 ms |

---

## 12. Checklist

**Lights**
- [ ] One shadowed directional light. Other local lights are spot rather than point where possible.
- [ ] Tight attenuation radii, and Max Draw Distance + fade on every local light.
- [ ] Shadows only on key lights. Contact shadows for detail lights.
- [ ] Volumetric scattering and translucency lighting off where not needed.
- [ ] Light functions ≤ 2–3. IES instead where possible.
- [ ] Shadowed lights don't move. The sun moves in steps.
- [ ] Light Complexity view has no white hotspots in gameplay areas.

**GI, sky and fog**
- [ ] No scene lighting from emissive.
- [ ] Real-time sky capture time-sliced, or a static capture.
- [ ] Volumetric clouds and heterogeneous volumes only where needed. Local fog volumes for local mist.
- [ ] No planar reflections in gameplay. Scene captures update on demand.
- [ ] **[5.8]** Lumen Lite verified at Medium (`r.Lumen.FinalGatherMethod` → 0).

**Post**
- [ ] One global PP volume, and local volumes override only what they need.
- [ ] No Lumen quality raised in PP volumes.
- [ ] Standard bloom. DOF off in gameplay. Exposure min/max set.
- [ ] No SSAO on top of Lumen, and no SSGI (deprecated in 5.8).
- [ ] ≤ 2–3 PP materials active at once, each lean. Custom depth only where needed.

---

## 13. Sources

- [Epic – Lumen Performance Guide (5.8)](https://dev.epicgames.com/documentation/unreal-engine/lumen-performance-guide-for-unreal-engine)
- [Epic – MegaLights](https://dev.epicgames.com/documentation/en-us/unreal-engine/megalights-in-unreal-engine)
- [Epic – Shadowing in Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine/shadowing-in-unreal-engine)
- [Epic – Virtual Shadow Maps](https://dev.epicgames.com/documentation/en-us/unreal-engine/virtual-shadow-maps-in-unreal-engine)
- [Epic – Unreal Engine 5.8 Release Notes](https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-8-release-notes)
- [Epic – Temporal Super Resolution](https://dev.epicgames.com/documentation/unreal-engine/temporal-super-resolution-in-unreal-engine?lang=en-US)
- [Tom Looman – UE 5.8 Performance Highlights](https://tomlooman.com/unreal-engine-5-8-performance-highlights/)
- [Daniel Wright (Epic) on Lumen Lite](https://x.com/EpicShaders/status/2070573554135953556)
- [Iri Shinsoj – UE5 Lighting Features Reference](https://medium.com/@shinsoj/lighting-features-cheat-sheet-5b81b63b3ab7)
- [polycount – UE5 Lumen & Light Optimization Guide](https://polycount.com/discussion/239120/unreal-engine-5-lumen-light-optimization-guide)
