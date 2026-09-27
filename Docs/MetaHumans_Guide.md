# Using MetaHumans in Games Without Losing Performance

MetaHumans are built for cinematic quality by default. A single hero MetaHuman at LOD0 (strand hair, 8 face LODs driven by RigLogic, subsurface skin, high-resolution textures) can cost more than an entire game scene. This guide shows how to keep MetaHumans in a real-time game, including the 120 fps targets in [`120FPS_Guide.md`](120FPS_Guide.md), across UE 5.3–5.8. Notes that apply only to 5.8 are marked **[5.8]**.

Related guides:
- [`120FPS_Guide.md`](120FPS_Guide.md) section 19: animated meshes, cloth, hair and crowds in general.
- [`Materials_Textures_Guide.md`](Materials_Textures_Guide.md): texture sizes, groups, streaming.
- [`Code_Optimization_Guide.md`](Code_Optimization_Guide.md): Anim Blueprint thread safety, tick batching.

---

## Contents

0. [What a MetaHuman costs](#0-what-a-metahuman-costs)
1. [Measure](#1-measure)
2. [Choose the right quality when creating or assembling](#2-choose-the-right-quality)
3. [LODs and the LODSync component](#3-lods-and-the-lodsync-component)
4. [Hair and grooms](#4-hair-and-grooms)
5. [Face animation and RigLogic](#5-face-animation-and-riglogic)
6. [Body, clothing and components](#6-body-clothing-and-components)
7. [Materials and textures](#7-materials-and-textures)
8. [Crowds](#8-crowds)
9. [Budgets](#9-budgets)
10. [Checklist](#10-checklist)
11. [Sources](#11-sources)

---

## 0. What a MetaHuman costs

| Part | Cost | Where it shows up |
|---|---|---|
| **Face** skeletal mesh (up to **8 LODs**) + **RigLogic** facial rig | CPU for rig evaluation and animation, GPU for skinning and many joints | Game thread / animation workers, `stat anim` |
| **Body** parts (body, torso, legs, feet: **4 LODs**) | Several skeletal mesh components per character | Draw calls, skinning, render thread |
| **Grooms** (hair, eyebrows, eyelashes, beard, peach fuzz) as **strands** | **Very high GPU** (strand rasterization, deep shadows, possibly simulation) | `stat gpu` → *HairStrands* passes |
| **Materials** (subsurface skin, refractive eyes, teeth, hair) | Expensive shading models | *BasePass*, subsurface passes |
| **Textures** (up to 8K for faces, depending on export settings) | **VRAM** | `stat streaming`, Texture Stats |
| **Cloth** (Chaos cloth on garments) | CPU | `stat anim`, Insights |

Every one of these has a cheaper option: LODs, hair cards, lower rig LODs, merged meshes, smaller textures. The work is **choosing per character and per distance**.

---

## 1. Measure

- `stat gpu` / `ProfileGPU`: look for *HairStrands* (visibility, rasterization, shadows), *BasePass*, *SubsurfaceScattering*, *ShadowDepths*.
- `stat anim`, and Unreal Insights with `-statnamedevents`: RigLogic, Anim BP evaluation, and cloth, per character.
- **Show → Visualize → Groom:** hair geometry type (strands, cards or meshes) and LOD per groom.
- **LOD Coloration** view, or the LODSync component's *Forced LOD*: confirm distant MetaHumans really switch to low LODs.
- `stat streaming`, Texture Stats: MetaHuman texture memory per character.

Test with the **real crowd count** of your worst scene, not one MetaHuman in an empty level.

---

## 2. Choose the right quality

Most of the cost is decided **before the character is in the level**:

- **Pick the export or assembly quality per character role.** MetaHuman Creator and the in-engine assembly (5.6+) offer game-optimized and cinematic options, and a choice of **texture resolution**. For example:
  - **Hero** (player, main companions): full LOD set, 4K face textures maximum, strands allowed.
  - **Named NPCs:** 2K textures, cards for hair.
  - **Background NPCs:** use crowd tooling (section 8), not full MetaHumans.
- **[5.8] Unbaked texture control and Mesh-to-MetaHuman** give more art control without baking. Keep the performance-optimized options for in-game characters.
- **Don't ship the cinematic version to gameplay.** If cutscenes need the cinematic version, keep **two variants** of the character (gameplay and cinematic) and swap for cutscenes.

---

## 3. LODs and the LODSync component

A MetaHuman actor has a **LODSync** component. It switches all parts (face, body, grooms) together instead of each part choosing its own LOD.

| LODSync setting | Default | Recommendation |
|---|---|---|
| **Num LODs** | 8 (-1 = calculate from components) | Leave it |
| **Forced LOD** | -1 (automatic) | Keep -1 in gameplay. **Never force LOD 0/1 on many MetaHumans** (Epic warns this hurts performance). Force LOD 0 only for close-up cutscene shots |
| **Min LOD** | 0 | Raise it for NPCs so they never use LOD0 (e.g. 1 or 2) |
| **Custom LOD Mapping** | — | Map the body's 4 LODs to the face's 8, so the body switches once for every two overall changes (Epic's example) |
| **Sync option per component** | Drive / Passive / Disabled | The face usually *drives*. Set cheap attachments to *Passive* |

More rules:
- **Face DNA LOD count must match the face skeletal mesh LOD count** at runtime (after per-platform Min/Max LOD). If you need fewer LODs for an actor, use LODSync's **Custom LOD Mapping** instead of editing the DNA.
- **Per-platform / per-quality Min LOD** on the face, body and groom assets keeps LOD0 out of memory on lower tiers.
- `r.SkeletalMeshLODBias` per tier (already in this repo's scalability files) shifts all MetaHumans to lower LODs on Medium and Low.
- **LOD screen sizes:** make sure distant characters (> 15–20 m) are at LOD 3+ for the face. Check with LOD Coloration.

---

## 4. Hair and grooms

Grooms are usually the **single biggest GPU cost** of a MetaHuman.

| Geometry | Cost | Use |
|---|---|---|
| **Strands** | Very high | Hero character, close-ups, **High/Epic only** |
| **Cards** | Medium | Default for gameplay, and all NPCs |
| **Meshes** | Low | Distant characters, Low tier, crowds |

- **Groom LODs:** strands at LOD0 only, cards from LOD1, meshes from LOD3+ (or earlier on Medium).
- **Force cards globally on lower tiers:**
  ```
  r.HairStrands.UseCardsInsteadOfStrands 1
  ```
  This doesn't affect mesh-based hair. To scale it with quality presets, add it to **every tier** of a scalability group so it doesn't leak between presets (see `Config/README.md`). For example, in `DefaultScalability.ini`:
  ```ini
  [ShadingQuality@0]
  r.HairStrands.UseCardsInsteadOfStrands=1
  [ShadingQuality@1]
  r.HairStrands.UseCardsInsteadOfStrands=1
  [ShadingQuality@2]
  r.HairStrands.UseCardsInsteadOfStrands=0
  [ShadingQuality@3]
  r.HairStrands.UseCardsInsteadOfStrands=0
  [ShadingQuality@Cine]
  r.HairStrands.UseCardsInsteadOfStrands=0
  ```
  If you add it, update `Tools/gen_scalability_120fps.py` too (add the row to the ShadingQuality group) and run `Tools/validate_configs.py`. Test switching presets at runtime: some groom setups only pick up the change when the component is recreated.
- **Per-platform groom Min LOD** in the Groom Asset editor (*Add (+)* per platform).
- **Remove peach fuzz** (the facial fuzz groom) on NPCs. It's invisible at gameplay distances. Consider the same for eyelashes and eyebrows as strands, and use card versions instead.
- **Hair simulation** (Niagara groom physics): turn it off on NPCs and distant characters. Keep it only on the hero, and only at LOD0.
- **Hair shadows:** strand deep shadows are expensive. Cards and meshes use regular shadows. Make sure distant characters' grooms aren't casting strand shadows.

---

## 5. Face animation and RigLogic

RigLogic turns facial animation controls into joint transforms every frame. It's a CPU cost that grows with the **number of animated faces**.

- **Only animate faces that are visible and close:**
  - Face component `VisibilityBasedAnimTickOption = OnlyTickPoseWhenRendered`.
  - Stop face animation beyond ~10–15 m. A neutral face (or body-only animation) is enough at distance.
- **Rig LOD follows face LOD.** Lower face LODs drive fewer joints, so good LOD switching (section 3) is also the main RigLogic optimization.
- **Anim BP nodes with LOD Threshold:** set **LOD Threshold** on the RigLogic / face post-process nodes and on expensive nodes (Control Rig, IK), so they only run at close LODs.
- **Budget the animation:** use the **Animation Budget Allocator** (`a.Budget.*`, enabled in the 120 fps profile) and URO for NPC bodies (`120FPS_Guide.md` section 19.4).
- **Thread-safe Anim BPs:** use *Blueprint Thread Safe Update Animation* + Property Access in custom face and body Anim BPs.
- **Live Link / MetaHuman Animator** are for **capture**. Bake the result into animation sequences for the shipping game, and don't run live solving at runtime unless it's a feature.
- **Dialogue-heavy games:** play face animation only for the speaking character and its listener. Everyone else uses idle loops at a lower LOD or update rate.

---

## 6. Body, clothing and components

- A MetaHuman body is **several skeletal mesh components** (body, torso, legs, feet, plus clothing). Each one is a separate skinning job and draw.
  - Make sure they use a **Leader Pose Component** (the body drives the rest), not separate Anim BPs or Copy Pose.
  - **For NPCs, merge body parts and clothing into one skeletal mesh** (Skeletal Mesh Merge, or a character customization system that bakes merged meshes). Fewer components means less CPU, fewer draws and less skinning.
- **Cloth:** Chaos cloth on garments costs roughly **1–3 ms per character** on consumer CPUs with default settings (`120FPS_Guide.md` section 19.6).
  - Keep it on the hero only, ≤ 300 simulated vertices, and self-collision off.
  - Turn it off on LOD2+ and on NPCs.
- **Physics asset:** use a simplified asset for ragdolls and hit detection (≤ 12–15 bodies).
- **Shadows:** capsule shadows for distant characters, and *Cast Shadow* off on small attachments.
- **GPU skin cache:** it's on in this repo's base config. With many MetaHumans on screen, watch `r.SkinCache.SceneMemoryLimitInMB`. Characters that don't fit fall back to the slower path.

---

## 7. Materials and textures

- **Skin (Subsurface Profile), eyes (refractive) and teeth** are expensive shading models. MetaHuman materials already switch to simpler versions at lower LODs, so keep that LOD setup intact and **don't force high-LOD materials** onto low LODs.
- **Texture resolution by role** (section 2): 4K maximum for hero faces, 2K for named NPCs, 1K or lower for background characters. Assign **Character** texture groups (`Materials_Textures_Guide.md` section 7.3) so per-platform limits apply.
- **VRAM:** a character exported at 8K face textures uses far more memory than the same character at 2K. On 8 GB cards, budget MetaHuman texture memory explicitly (section 9).
- **Streaming:** run *Build Texture Streaming* so faces stream the right mips. Pre-stream hero faces before cutscenes to avoid blurry close-ups (`Materials_Textures_Guide.md` section 8.1).
- **Lumen:** skin and hair look depends on good lighting, not higher material quality. Use key lights and rim lights (`Lighting_PostProcess_Guide.md` section 3) rather than more expensive materials.

---

## 8. Crowds

Full MetaHuman actors don't scale to crowds. Use one of these:

| Approach | Engine version | How it works |
|---|---|---|
| **[5.8] MetaHuman Collections / MetaHuman Crowd plugin** (**experimental**) | 5.8 | Builds crowds from collections of modular MetaHuman parts (head, body, hair, clothing), composed by hand or procedurally in Blueprint. Uses **Mass** for orchestration. Characters near the camera are full MetaHuman actors, and farther ones switch to **Instanced Skinned Meshes (ISKM)**, rendered with Nanite where available. Epic cites hundreds on mobile and thousands on high-end platforms |
| **Mass + vertex animation textures** | 5.x | Distant crowd members are instanced static meshes with baked animation (AnimToTexture plugin), and only nearby characters are real skeletal meshes (`120FPS_Guide.md` section 18.2) |
| **Animation Sharing** | 5.x | Many actors share a few animation instances |
| **Low-LOD MetaHumans** | 5.x | For small groups (≤ 10–20): Min LOD 3+, cards/mesh hair, merged meshes, no face animation, budgeted Anim BPs |

For 5.8 Collections:
- It's **experimental**, so prototype with it and measure on Tier B hardware.
- Keep a Mass + vertex animation fallback until it's production-ready.
- Community tests report ~50–60 fps with 1,000 characters **in the editor with recording software running** (not a controlled benchmark). Measure your own scenes with the test plan in `120FPS_Guide.md` section 23.

---

## 9. Budgets

Starting budgets for the 120 fps profile (Tier A = High, Tier B = Medium, see `120FPS_Guide.md` section 1):

| Item | Tier A High @ 120 | Tier B Medium @ 120 |
|---|---|---|
| MetaHumans at face LOD0–1 on screen | ≤ 1–2 (hero, close-up) | ≤ 1 |
| MetaHumans at LOD2–4 on screen | ≤ 8 | ≤ 5 |
| Characters with strand hair | 1 (hero, High/Epic only) | 0 (cards) |
| Faces animating with RigLogic | ≤ 3–4 | ≤ 2 |
| Characters with simulated cloth | ≤ 2 | ≤ 1 |
| MetaHuman texture memory (total) | ≤ 600 MB | ≤ 400 MB |
| More characters than this | Crowd system (section 8) | Crowd system |

Measure each MetaHuman's GPU and CPU cost in your own scene with `ProfileGPU` and Insights, then scale the counts.

---

## 10. Checklist

- [ ] Each character exported or assembled at the quality its role needs. No cinematic variants in gameplay.
- [ ] LODSync: Forced LOD -1 in gameplay, Min LOD raised for NPCs, Custom LOD Mapping for the body.
- [ ] Face DNA LOD count matches the face mesh LOD count after per-platform Min LOD.
- [ ] Strands only for the hero on High/Epic. Cards or meshes everywhere else (`r.HairStrands.UseCardsInsteadOfStrands` per tier if needed).
- [ ] Peach fuzz removed on NPCs, hair simulation off on NPCs.
- [ ] Face animation only for visible, close, speaking characters. LOD Threshold on RigLogic and expensive nodes.
- [ ] Leader Pose Component. NPC bodies and clothing merged into one mesh where possible.
- [ ] Cloth only on the hero, LOD-limited.
- [ ] Texture resolution by role, Character texture groups, texture streaming built.
- [ ] Crowds via the MetaHuman Crowd plugin (5.8, experimental) or Mass + vertex animation, not full actors.

---

## 11. Sources

- [Epic – Controlling MetaHuman Levels of Detail (LODs) in Unreal Engine](https://dev.epicgames.com/documentation/metahuman/controlling-metahuman-levels-of-detail-lods-in-unreal-engine)
- [Epic – MetaHuman 5.8 Release Notes](https://dev.epicgames.com/documentation/metahuman/metahuman-5-8-release-notes-in-unreal-engine)
- [MetaHuman – MetaHuman 5.8 is now available](https://www.metahuman.com/news/metahuman-5-8-is-now-available)
- [Epic – Unreal Engine 5.8 is now available](https://www.unrealengine.com/news/unreal-engine-5-8-is-now-available)
- [80.lv – What's new in MetaHuman in UE 5.8](https://80.lv/articles/populate-your-ue5-8-worlds-with-metahuman-crowds)
- [GamesBeat – MetaHuman 5.8 crowds](https://gamesbeat.com/epic-games-launches-metahuman-5-8-to-create-real-time-game-character-crowds/)
- [note.com (Gaku) – Testing the MetaHuman Crowd plugin](https://note.com/creator_gaku/n/n61bbff67b601?hl=en)
- [StraySpark – MetaHuman Crowd in UE 5.8](https://www.strayspark.studio/blog/metahuman-crowd-ue5-8-guide)
- [James Roha – MetaHuman 5.6 / 5.7 Pipeline Reference](https://medium.com/@Jamesroha/metahuman-5-6-5-7-pipeline-reference-170d302b078e)
