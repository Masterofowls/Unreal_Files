# Optimizing Materials and Textures in Unreal Engine 5

This is a practical guide to keeping materials cheap on the GPU and textures cheap in VRAM, without the game looking worse. It fits the budgets in [`120FPS_Guide.md`](120FPS_Guide.md), where the base pass (Nanite + materials) is budgeted at **~1.6 ms** and textures at **~2.5 GB of an 8 GB card**.

Related guides:
- [`120FPS_Guide.md`](120FPS_Guide.md): Nanite, Lumen, VSM, translucency and landscape at the scene level.
- [`Code_Optimization_Guide.md`](Code_Optimization_Guide.md): CPU-side code.
- [`Common_Bugs_Guide.md`](Common_Bugs_Guide.md) section 9: visual bugs (pink materials, ghosting, etc.).

---

## Contents

0. [Where the cost goes](#0-where-the-cost-goes)
1. [Measure](#1-measure)
2. [Material architecture: masters, instances and permutations](#2-material-architecture)
3. [Pixel shader cost](#3-pixel-shader-cost)
4. [Blend modes, masked, translucency, WPO and PDO](#4-blend-modes-masked-translucency-wpo-and-pdo)
5. [Materials with Nanite, Lumen and VSM](#5-materials-with-nanite-lumen-and-vsm)
6. [Texture formats and compression](#6-texture-formats-and-compression)
7. [Texture resolution, mips and texture groups](#7-texture-resolution-mips-and-texture-groups)
8. [Streaming and virtual textures](#8-streaming-and-virtual-textures)
9. [Sampling: packing, samplers, atlases and arrays](#9-sampling-packing-samplers-atlases-and-arrays)
10. [Budgets](#10-budgets)
11. [Audit workflow and automation](#11-audit-workflow-and-automation)
12. [Checklist](#12-checklist)
13. [Sources](#13-sources)

---

## 0. Where the cost goes

| Cost | Driven by | Symptom |
|---|---|---|
| **GPU time per pixel** | Material instruction count, texture samples, blend mode, overdraw | High *BasePass* / *Translucency* in `stat gpu` |
| **GPU raster time** (Nanite) | Masked, WPO, PDO, two-sided materials → programmable raster | High *Nanite VisBuffer* |
| **Shader count / compile time / PSO hitches** | Static switches, usage flags, number of master materials | Long shader compiles, first-use stutter |
| **VRAM** | Texture resolution × format × count | "Texture streaming pool over budget", blurry textures, D3D device removed |
| **Memory bandwidth** | Many large texture samples per pixel | Everything slower at high resolution |
| **Download / disk size** | Texture size and compression | Large builds, slow installs and loads |

---

## 1. Measure

**Materials**
- **Viewport → View Mode → Optimization Viewmodes:**
  - *Shader Complexity:* green = cheap, red/white = expensive.
  - *Shader Complexity & Quads* / *Quad Overdraw:* translucency overdraw and tiny triangles.
  - *Shader Instruction Count* (4.27+): instructions per pixel.
- **Material Editor → Stats** and **Platform Stats:** instruction counts per shader stage, texture samples, and the number of shader permutations. Check with the *SM6* platform selected.
- **Tools → Audit → Material Analyzer:** which static switch and parameter combinations exist across instances, and how many permutations they create.
- `stat gpu`, `ProfileGPU`: *BasePass*, *Translucency* and *Nanite* timings (see `120FPS_Guide.md` section 4).

**Textures**
- `stat streaming`: pool usage and whether you're over budget.
- **Tools → Audit → Statistics → Texture Stats:** every loaded texture with size, format, group and memory. Sort by memory.
- **`listtextures`** console command: dumps loaded textures with formats and sizes to the log.
- **View Mode → Texture Streaming Accuracy → Required Texture Resolution:** shows textures that are much bigger than needed on screen.
- **Size Map** (right-click an asset): how much texture memory an asset pulls in.

---

## 2. Material architecture

### 2.1 Few master materials, many instances

- Build a small set of **master materials**, for example:
  - `M_Master_Opaque`
  - `M_Master_Masked_Foliage`
  - `M_Master_Translucent_Glass`
  - `M_Master_Landscape`
  - `M_Master_VFX_Unlit`
- Make everything else a **Material Instance**. Instances with only scalar/vector/texture parameter changes share the parent's shaders, so they add **no** compile time, shader memory or PSOs.
- **Unique materials** (not instances) each compile their own shaders. They bloat build size and PSO count and cause more first-use hitches.
- Use **Material Functions** for shared node logic. They're inlined, so they cost nothing extra by themselves and keep master materials maintainable.

### 2.2 Static switches create permutations

- Every **static switch** / *static component mask* parameter that an instance changes creates a **new shader permutation**, with its own compile, memory and PSO:
  - 5 switches → up to 32 combinations
  - × vertex factories (static mesh, skeletal, Nanite, instanced…)
  - × quality levels
  - × platforms
- **Rules:**
  - Use static switches for **features that genuinely differ per asset** (detail normal on/off, emissive on/off). Keep **≤ 4–6 per master material**.
  - For values that change per instance (colors, tiling, strengths), use normal parameters. They cost nothing extra.
  - Check actual usage with the **Material Analyzer** and merge instances that use rare combinations.
  - Pre-create "preset" parent instances (for example `MI_Master_Opaque_Detail`) and parent other instances to them, so combinations don't multiply.
- **Quality Switch** and **Feature Level Switch** nodes also create permutations. Only add branches that really differ.

### 2.3 Usage flags

- *Details → Usage* checkboxes (Used with Skeletal Mesh, Niagara Sprites, Instanced Static Meshes, Nanite, Spline Meshes…) each add a vertex factory permutation.
- For master materials, turn off **Automatically Set Usage in Editor** and tick only the usages you need. Otherwise applying a material to a new mesh type silently adds shaders.

---

## 3. Pixel shader cost

### 3.1 Instruction and sample budgets (base pass, SM6 Platform Stats)

| Material type | Instructions (pixel) | Texture samples |
|---|---|---|
| Common prop / architecture | ≤ 150–200 | ≤ 6–8 |
| Hero asset / character | ≤ 300 | ≤ 10–12 |
| Landscape (with RVT) | ≤ 200 at the landscape; the layer blend is paid once in the RVT | ≤ 8 + RVT |
| Foliage (masked) | ≤ 120 | ≤ 4 |
| Translucent (glass, water) | ≤ 150, keep the screen coverage small | ≤ 6 |
| Particles (translucent/additive) | ≤ 60–80 (overdraw multiplies this) | ≤ 2–3 |
| UI | ≤ 50 | ≤ 2 |

These are starting budgets. The real cost is instructions × **pixels covered** × **overdraw**, so a 400-instruction material on a small hero prop can be cheaper than a 150-instruction material covering the whole screen as a ground plane.

### 3.2 Reduce pixel work

- **Move math to the vertex shader.**
  - UV transforms (tiling, panning, rotation) → **Customized UVs**, or the **Vertex Interpolator** node. They run per vertex, not per pixel.
  - Per-object values (object position, bounds, distance to camera at object level) → vertex shader or Per Instance Custom Data.
- **Bake into textures:** noise, gradients, curvature, AO and complex masks. One texture sample is cheaper than a procedural *Noise* node, which is one of the most expensive nodes.
- **`Lerp` / `If` evaluate both inputs.** Material graphs don't skip the unused branch. A distance-based lerp between a cheap and an expensive layer still pays for both. For features that are on or off per asset, use **static switches**. For per-platform or per-quality differences, use **Quality Switch**.
- **Parameters vs constants:** constants and static parameters are folded by the compiler, and regular parameters aren't. Parameters are fine; just don't expose parameters for values that never change.
- **Free or near-free:** `Saturate`/`Clamp` 0–1, `OneMinus`, multiplying by constants. **More expensive:** `Power` with non-constant exponents, `Noise`, `SceneTexture` / `SceneColor` reads, `DepthFade`, *Parallax Occlusion Mapping* (limit steps and use it only close up), `Custom` HLSL loops.
- **Fully Rough** (material property) skips the specular calculation for surfaces that don't need it (for example matte background props).
- **Detail textures:** a second normal/albedo layer should be a static-switch feature, not always on in the master.
- **Normal map math:** `BlendAngleCorrectedNormals` is more expensive than a simple `RNM`/*add + normalize*. Use the cheap blend for small details.

### 3.3 Shading models

The cost roughly goes from cheapest to most expensive:

**Unlit** < **Default Lit** < **Clear Coat / Two Sided Foliage / Subsurface** < **Subsurface Profile / Cloth / Hair / Eye**

- Use the specialized models only where they're visible (skin, eyes, car paint). Avoid **Substrate** unless you need its layering, and profile it if it's on.

---

## 4. Blend modes, masked, translucency, WPO and PDO

**Blend mode cost:** **Opaque** < **Masked** < **Translucent / Additive / Modulate**

- **Masked:**
  - Breaks early depth rejection (costs extra on non-Nanite geometry).
  - Forces Nanite's **programmable raster**, which costs about 20–30% more raster time for foliage (Epic's figure).
  - Use real geometry (opaque) where you can. Keep the masked area small, and use **Dithered LOD transitions** only where needed.
- **Translucent:**
  - Every layer covering a pixel pays the full shader cost (**overdraw**). Check the *Quad Overdraw* view and keep ≤ 2–3 layers.
  - **Lighting mode costs:**
    - *Volumetric NonDirectional* (cheapest lit): use it for particles and smoke.
    - *Volumetric Directional*: more expensive than NonDirectional.
    - *Surface TranslucencyVolume*: glass that needs a surface look.
    - *Surface ForwardShading* (most expensive): hero glass only.
  - **Unlit** for most VFX: bake lighting into the texture or use vertex color.
  - Particles: use the *Render After DOF* / separate translucency passes, and avoid huge full-screen sprites.
- **Two-sided:** doubles the shaded faces, and with Nanite it takes the programmable raster path. Use it only for thin geometry (leaves, cloth, paper).
- **World Position Offset (WPO):**
  - Invalidates **VSM** shadow pages.
  - Forces programmable raster in Nanite.
  - Always set **WPO Disable Distance** on meshes and foliage types that use it.
  - Set the material's **Max World Position Offset Displacement**, which prevents bounds clipping.
  - Turn off *Evaluate World Position Offset* on meshes that don't need it.
- **Pixel Depth Offset (PDO):** disables early-Z and is costly with Nanite. Avoid it except for small blending tricks. For terrain blending, prefer RVT-based blending.
- **Emissive:** it's cheap to render, but **don't light scenes with emissive surfaces** under Lumen. It causes noise (see `Common_Bugs_Guide.md` section 9.2).

---

## 5. Materials with Nanite, Lumen and VSM

- **Nanite material bins:**
  - Nanite shades one material bin at a time, so fewer **unique materials visible on screen** means a faster base pass.
  - Instances of the same parent with the same static permutation can share work better than completely different materials.
  - Keep **≤ 3 material slots per mesh**.
- **Nanite programmable raster** is triggered by masked, WPO, PDO and two-sided materials, and costs more raster time. Use opaque wherever possible.
- **Lumen:**
  - The Lumen surface cache captures materials at low resolution, so fine albedo detail doesn't affect GI cost.
  - Very bright or very saturated albedo (> ~0.9 or pure colors) causes unrealistic bounce and hot spots. Keep albedo in the physically plausible range (roughly 0.04–0.9 in linear), per PBR guidelines.
- **VSM:**
  - WPO invalidation (section 4).
  - **Masked** materials in shadow passes also run the opacity mask per shadow texel. Simplify the opacity mask logic (one texture sample), because it runs in every shadow pass too.
- **Landscape materials:**
  - ≤ 4 paint layers per component, and blend once into a **Runtime Virtual Texture** that the landscape and nearby meshes sample.
  - Use *Landscape Layer Blend* with shared samplers (`120FPS_Guide.md` section 17).

---

## 6. Texture formats and compression

### 6.1 Compression settings: what to use

| Texture | Compression Settings | GPU format (PC) | sRGB |
|---|---|---|---|
| Base color, no alpha | **Default** | BC1 (0.5 B/px), or **BC7** via *Compression Quality* / `TC_BC7` for high-quality color | **On** |
| Base color + alpha (opacity) | **Default** | BC3 (1 B/px), or BC7 | On |
| **Normal map** | **Normalmap** | **BC5** (1 B/px, 2 channels, Z rebuilt in the shader) | **Off** |
| Packed masks (ORM: AO, Roughness, Metallic) | **Masks** | BC1 / BC7 (linear) | **Off** |
| Single channel (height, mask, opacity) | **Alpha** | **BC4** (0.5 B/px) | Off |
| Grayscale that must stay uncompressed (rare) | Grayscale | G8 / G16, **uncompressed, large** | Off |
| HDRI / sky / emissive HDR | **HDRCompressed** | **BC6H** (1 B/px) | n/a |
| HDR requiring full float precision (rare) | HDR | RGBA16F (**8 B/px**, huge) | n/a |
| UI | **UserInterface2D** | RGBA8 uncompressed (**4 B/px**) | On |
| Vector displacement | VectorDisplacementmap | RGBA8 uncompressed | Off |

**Memory math** (including the full mip chain, ~1.33×):

| Size | BC1 / BC4 | BC3 / BC5 / BC7 / BC6H | RGBA8 (UI) | RGBA16F (HDR) |
|---|---|---|---|---|
| 1024² | 0.7 MB | 1.3 MB | 5.3 MB | 10.7 MB |
| 2048² | 2.7 MB | 5.3 MB | 21.3 MB | 42.7 MB |
| 4096² | 10.7 MB | 21.3 MB | 85.3 MB | 170.7 MB |

**Common mistakes:**
- **sRGB on for data textures** (normals, roughness, masks). This gives wrong lighting and wasted precision. **Only color textures are sRGB.**
- **A normal map not set to *Normalmap*.** It gets sRGB and BC1/BC3 → banding and wrong shading.
- An **alpha channel you don't need.** An RGBA base color doubles memory (BC1 → BC3). Remove unused alpha in the source file.
- **Using Grayscale for masks.** It's uncompressed, so it's 2–8× larger than BC4 (*Alpha*).
- **Big UI textures.** UserInterface2D is uncompressed. Keep UI textures small and atlased, and use SVG/vector widgets or slices (9-slice brushes).
- **HDR (uncompressed) for skies.** Use HDRCompressed (BC6H) unless you can see banding.

### 6.2 Disk size: Oodle Texture

- UE5 compresses textures with **Oodle Texture**, which supports **RDO (rate-distortion optimization)** for smaller packages and downloads at almost no visual cost.
- Set it up in *Project Settings → Texture Encoding*, and per texture with *Lossy Compression Amount*.
- This affects **download size and load time**, not VRAM.

---

## 7. Texture resolution, mips and texture groups

### 7.1 Resolution and texel density

- Pick a **texel density** target and keep it consistent. For example:
  - **1024 px/m** (10.24 px/cm) for first/third person at 1080p–1440p
  - **512 px/m** for large or background surfaces
- Keep a consistent density across assets, so no prop looks blurry next to a sharp one.
- **Typical max sizes:**

  | Asset | Max size |
  |---|---|
  | Small props | 512–1024 |
  | Medium props | 1024–2048 |
  | Hero props / characters | 2048 (4096 only for full-screen hero surfaces, preferably as Virtual Textures) |
  | Tiling materials | 1024–2048 (tiling hides the resolution) |
  | Masks / ORM | Can often be **half** the base color size |
  | Normal maps | Same as base color. Lowering them first is the most visible reduction |

- **Reduce in the engine, not in the source:** set *Maximum Texture Size* or *LOD Bias* on the texture, or better, per **Texture Group** (section 7.3). The source stays at full resolution for future platforms.
- **Use power-of-two sizes** (512, 1024, 2048…). UE 5.1+ can mip non-power-of-two textures, but power-of-two is still the safest choice for compression, streaming and all platforms.

### 7.2 Mips and filtering

- **Every texture on 3D surfaces needs mips.**
  - *NoMipmaps* causes shimmering and aliasing at distance, and the texture **can't stream**. It always keeps full resolution in memory.
  - Only UI and some lookup textures should use *NoMipmaps*.
- *Mip Gen Settings*: *FromTextureGroup* (default). Use *Sharpen* only when distant mips look too soft.
- **Never Stream:** only for UI and small, always-needed textures. On world textures it pins full-resolution memory.

### 7.3 Texture groups: control size per category and per platform

- Assign every texture to the right **Texture Group**:
  - `World`, `WorldNormalMap`, `WorldSpecular`
  - `Character`, `CharacterNormalMap`, `CharacterSpecular`
  - `Weapon`
  - `Vehicle`
  - `Effects`
  - `UI`
  - `Skybox`
  - …
- Groups set the max size, LOD bias and filtering **per platform** (and per device profile), so you can lower, say, `World` textures on a low-memory platform without touching assets.
- Groups are defined in the device profiles (`BaseDeviceProfiles.ini` → your `DefaultDeviceProfiles.ini`). Example override in `DefaultDeviceProfiles.ini`:

  ```ini
  [Windows DeviceProfile]
  ; Copy the full +TextureLODGroups list for your engine version from
  ; Engine/Config/BaseDeviceProfiles.ini first; entries are matched by Group.
  +TextureLODGroups=(Group=TEXTUREGROUP_World,MinLODSize=1,MaxLODSize=2048,LODBias=0,MinMagFilter=aniso,MipFilter=point,MipGenSettings=TMGS_SimpleAverage)
  ```

  Always check the exact syntax against your engine's `BaseDeviceProfiles.ini`. It varies between versions.

---

## 8. Streaming and virtual textures

### 8.1 Texture streaming

- The streaming pool per tier is set in `DefaultScalability.ini` (`r.Streaming.PoolSize`) and capped to VRAM by `r.Streaming.LimitPoolSizeToVRAM=1` (see `Config/`).
- **"Texture Streaming Pool Over Budget":** reduce texture sizes (groups, max sizes). Don't just raise the pool on 8 GB cards (`120FPS_Guide.md` section 13).
- **Build Texture Streaming** (*Build → Build Texture Streaming*) computes each mesh's UV density, so the engine streams the right mip. Without it the streamer guesses and loads mips that are too big or too small.
- **Mip pop-in when the camera cuts:** pre-stream around cuts (for example `UTexture2D::SetForceMipLevelsToBeResident` briefly), or use `r.Streaming.Boost` in cinematics.

### 8.2 Streaming Virtual Textures (SVT)

- **What they are:** only the visible tiles of a texture are resident (fixed-size pages). This is ideal for:
  - **large unique textures** (4K–8K hero assets, UDIM characters, big decals, terrain maps)
  - projects with huge texture variety
- **What they cost:**
  - a small per-sample overhead (page-table lookup)
  - a feedback pass
  - fixed VT pool memory
- **Don't** convert small or heavily tiling textures to VT. Regular streaming handles those better.
- Watch the VT pool (`r.VT.*`, *Project Settings → Virtual Textures*). An undersized pool causes blurry, flickering tiles.

### 8.3 Runtime Virtual Textures (RVT)

- RVTs cache **material output** (for example a landscape layer blend) into a virtual texture that's rendered on demand. Complex blending then runs once per texel page instead of every pixel every frame.
- Main uses: **landscape shading**, blending meshes into the terrain, and decal-like projections.
- Size the RVT resolution and tile count to what's visible, and use the *Streaming Low Mips* option for large worlds.

---

## 9. Sampling: packing, samplers, atlases and arrays

- **Channel packing:**
  - **ORM** (R = AO, G = Roughness, B = Metallic) in one BC1/BC7 texture replaces three samples.
  - Put an extra mask in the alpha channel only if it's needed. Adding alpha increases the size (BC1 → BC3/BC7). A separate BC4 can be cheaper.
- **Shared samplers:**
  - A shader has a limit of **16 samplers**.
  - Set *Sampler Source* to **Shared: Wrap** or **Shared: Clamp** on texture sample nodes, so many textures use one sampler. This is required for landscape and large master materials.
  - It doesn't reduce texture memory, but it lifts the limit and lowers overhead.
- **Atlases:**
  - Combine small UI or decal textures into atlases, which means fewer textures, draw state changes and PSOs.
  - Use **flipbooks** for animated VFX.
- **Texture 2D Arrays:** for many same-size layers (terrain types, decals), one array + an index replaces many texture objects and samplers.
- **Reuse:** tiling textures and trim sheets shared across many assets are cached better (less bandwidth) than a unique texture per asset.

---

## 10. Budgets

Use these as starting budgets for the hardware tiers in `120FPS_Guide.md`.

| Item | Tier A (8 GB, High) | Tier B (6–8 GB, Medium) |
|---|---|---|
| Texture streaming pool | 2.5 GB | 1.6 GB |
| Largest regular texture | 2048 (4096 as VT for hero surfaces) | Same assets; group LOD bias does the rest |
| Unique materials visible on screen | ≤ 150 | ≤ 150 |
| Master materials in the project | ≤ 10–15 | Same |
| Static switches per master | ≤ 4–6 | Same |
| Shader permutations per master (Platform Stats) | Keep the total shader count low. Investigate any master above ~200 | Same |
| BasePass time (`stat gpu`) | ≤ 1.6 ms (with Nanite) | ≤ 1.6 ms at a lower internal resolution |
| Translucency time | ≤ 0.5 ms | ≤ 0.5 ms |

---

## 11. Audit workflow and automation

1. **Weekly texture audit:**
   - Open *Statistics → Texture Stats* in the heaviest level and sort by memory. Check each of the top 50 for:
     - the right compression setting
     - sRGB matching its purpose
     - a sensible max size
     - mips present
     - the right group
   - Fix them in bulk with the **Property Matrix** (select assets → right-click → *Asset Actions → Edit Selection in Property Matrix*).
2. **Material audit:**
   - Use the Material Analyzer on each master: remove unused switch combinations and check the permutation count.
   - Use the Shader Complexity view in each level. Anything red on large screen areas needs work.
3. **Naming convention** makes automatic checks possible:
   - `T_Name_D` (base color), `T_Name_N` (normal), `T_Name_ORM`, `T_Name_M` (mask), `T_Name_E` (emissive)
   - `M_` masters, `MI_` instances, `MF_` functions
4. **Data Validation plugin:** write validators that fail on:
   - normal maps (`_N`) not set to Normalmap
   - data textures with sRGB on
   - textures over the size limit for their folder or type
   - world textures with NoMipmaps
   - materials that aren't instances of an approved master
   
   Run them in CI (see `Common_Bugs_Guide.md` section 18).
5. **Import presets:** use the Interchange import pipeline (5.x) or an editor utility to set compression, sRGB and group automatically at import, based on the file suffix.

---

## 12. Checklist

**Materials**
- [ ] Every surface uses an instance of an approved master material.
- [ ] ≤ 4–6 static switches per master. Rare combinations removed (Material Analyzer).
- [ ] *Automatically Set Usage in Editor* off on masters, and only the needed usages ticked.
- [ ] Instruction and sample budgets met (section 3.1). No `Noise` node in shipping materials.
- [ ] UV math moved to Customized UVs or Vertex Interpolators.
- [ ] Opaque by default. Masked or two-sided only where needed. No PDO on Nanite.
- [ ] WPO meshes have *WPO Disable Distance* and *Max WPO Displacement* set.
- [ ] Particles are unlit or Volumetric NonDirectional, with overdraw ≤ 2–3 layers.
- [ ] No scene lighting from emissive (Lumen).

**Textures**
- [ ] Correct compression: Normalmap / Masks / Alpha (BC4) / HDRCompressed / Default.
- [ ] sRGB only on color textures.
- [ ] No unused alpha channels.
- [ ] Power-of-two sizes, mips on everything except UI.
- [ ] Texture group assigned, and max sizes enforced per group or platform.
- [ ] ORM channel packing, shared samplers in large materials.
- [ ] *Build Texture Streaming* run, and `stat streaming` not over budget.
- [ ] Virtual textures only for large unique textures. RVT for landscape.

---

## 13. Sources

- [Epic – Guidelines for Optimizing Rendering for Real-Time](https://dev.epicgames.com/documentation/unreal-engine/guidelines-for-optimizing-rendering-for-real-time-in-unreal-engine?lang=en-US)
- [Epic – Viewport Modes (Shader Complexity, Quad Overdraw)](https://dev.epicgames.com/documentation/en-us/unreal-engine/viewport-modes-in-unreal-engine)
- [Epic – Streaming Virtual Texturing](https://dev.epicgames.com/documentation/unreal-engine/streaming-virtual-texturing-in-unreal-engine)
- [Epic – Texture Streaming Configuration](https://dev.epicgames.com/documentation/unreal-engine/texture-streaming-configuration-in-unreal-engine?lang=en-US)
- [Epic – Texture Compression Settings (4.27)](https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-compression-settings?application_version=4.27)
- [Epic – Textures Best Practices in Fortnite](https://dev.epicgames.com/documentation/fortnite/textures-best-practices-in-fortnite)
- [techarthub – Your Guide to Texture Compression in Unreal Engine](https://techarthub.com/your-guide-to-texture-compression-in-unreal-engine/)
- [techarthub – Fixing "Texture Streaming Pool Over Budget"](https://techarthub.com/fixing-texture-streaming-pool-over-budget-in-unreal/)
- [Kai Mallari – Texture Compression, Bit Depth and Image Formats for UE5](https://www.kaimallari.com/texture-optimization-compression-bit-depth-image-format-for-unreal-engine)
- [Chris McCole – Material Optimization in UE4/5](https://www.chrismccole.com/blog/material-optimization-in-ue4-ue5)
- [Chris McCole – Mips and custom texture groups](https://www.chrismccole.com/blog/mips-in-unreal-engine-4-ue4)
- [Kseniia Shestakova – Shader complexity and optimisation](https://kseniia-shestakova.medium.com/materials-compilation-shader-complexity-and-optimisation-f60be9a9357a)
- [Nikhil Maurya – Texture Groups and Mips in Unreal Engine](https://medium.com/@GroundZer0/understanding-textures-texture-groups-and-mips-in-unreal-engine-0f06eafc8cc5)
- [Two Neurons – UE5 Power of Two and Mips](https://www.twoneuronsstudio.com/2023/02/05/ue5-tutorial-power-of-two-and-mips/)
