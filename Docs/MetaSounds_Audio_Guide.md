# Optimizing MetaSounds and Game Audio in Unreal Engine 5

This is a practical guide to keeping audio cheap and reliable: MetaSound graphs, voice counts, concurrency, decoding, streaming, spatialization and effects. It covers UE 5.3–5.8.

At 120 fps the game thread has **≤ 6.5 ms** per frame (see [`120FPS_Guide.md`](120FPS_Guide.md)). Audio mostly runs on its own threads, but it still competes for CPU cores, memory and load time. Badly set up audio also causes hitches and stuck sounds.

Related guides:
- [`120FPS_Guide.md`](120FPS_Guide.md) section 22: audio basics.
- [`Code_Optimization_Guide.md`](Code_Optimization_Guide.md): gameplay code that triggers sounds.
- [`Common_Bugs_Guide.md`](Common_Bugs_Guide.md): general debugging.

---

## Contents

0. [How audio cost works](#0-how-audio-cost-works)
1. [Measure](#1-measure)
2. [MetaSound graph optimization](#2-metasound-graph-optimization)
3. [MetaSound lifetime: stopping sounds correctly](#3-metasound-lifetime)
4. [Parameters and gameplay integration](#4-parameters-and-gameplay-integration)
5. [Voices, concurrency and virtualization](#5-voices-concurrency-and-virtualization)
6. [Sound waves: compression, streaming and loading](#6-sound-waves-compression-streaming-and-loading)
7. [Spatialization, attenuation and occlusion](#7-spatialization-attenuation-and-occlusion)
8. [Effects: submixes, reverb and buses](#8-effects-submixes-reverb-and-buses)
9. [Engine audio settings](#9-engine-audio-settings)
10. [Common MetaSound and audio bugs](#10-common-metasound-and-audio-bugs)
11. [Budgets](#11-budgets)
12. [Checklist](#12-checklist)
13. [Sources](#13-sources)

---

## 0. How audio cost works

| Cost | Driven by | Thread |
|---|---|---|
| **Voice rendering** (MetaSound graphs, sound cues, decoding) | Number of **playing voices** × cost per voice (graph size, decoders, per-voice effects) | Audio render thread + async decode/render tasks |
| **Mixing and effects** | Submix effects (reverb, EQ, compressors, convolution), source effects, buses | Audio render thread |
| **Spatialization** | Panning (cheap) vs HRTF/binaural (more expensive) per voice | Audio render thread |
| **Gameplay-side audio** | Spawning audio components, setting parameters every tick, **occlusion traces**, concurrency evaluation | **Game thread** |
| **Memory and loading** | Decompressed or retained audio, sound banks, stream cache size | Memory, IO |

**Key facts about MetaSounds** (from Epic):
- Every MetaSound graph compiles to an **optimized, non-virtual C++ object**, with data passed between nodes by reference.
- Each MetaSound **renders asynchronously** from the main mixer, in parallel with other MetaSounds.

MetaSounds are efficient per node. The cost comes from **how many are playing** and **how heavy each graph is**.

---

## 1. Measure

| Tool | Use |
|---|---|
| `stat audio` | Active sounds and voices, audio thread time |
| `au.Debug.Sounds 1` | On-screen list of playing sounds |
| **Audio Insights** plugin (5.4+) | Active voices, virtual voices, MetaSound and submix activity, CPU per source over time |
| Unreal Insights | Audio render thread timing, game-thread audio calls (spawn, parameter set, occlusion traces) |
| `stat startfile` / `stat stopfile` | Capture stats over a session |
| `memreport -full` | Audio memory (sound waves, stream cache) |

**Test in the worst case:** a big fight with many weapons, impacts, footsteps and ambient loops, not a quiet corridor.

---

## 2. MetaSound graph optimization

### 2.1 Keep per-voice graphs lean

- **Heavy DSP doesn't belong in a per-voice graph.** Reverb, convolution, compressors, big delays and complex filters inside a MetaSound run **once for every voice playing it**. Ten gunshots mean ten reverbs. Move them to a **submix** or **audio bus**, which runs once for everyone (section 8).
- **Few Wave Players per voice.** Each Wave Player decodes audio. Layering 6 samples into every footstep costs 6 decoders per footstep. Pre-mix layers into fewer files when the layers don't need independent control.
- **Avoid giant graphs.** A graph with hundreds of nodes and many inputs costs more to build and to run. Split reusable parts into **MetaSound Patches**, and keep the number of exposed inputs manageable (a rule of thumb: ~30 or fewer).
- **Constructor pins** (the diamond-shaped pins) are **evaluated once** when the sound starts and can't change afterwards. Use them for settings that don't change during playback: sample selection, fixed filter types, seeds. The graph can be simplified at build time.
- **Random and variation logic:** use *Random Get* / *Array Random* with constructor inputs to pick samples. Don't run per-block random logic unless you need continuous variation.

### 2.2 Presets and patches instead of copies

- **MetaSound Presets:** many variants (e.g. per weapon) that share one parent graph and only change input defaults. One graph to maintain and optimize.
- **MetaSound Patches:** reusable sub-graphs (a shared "footstep layer" or "impact tail"). Fix or optimize once, and it improves everywhere.
- Don't duplicate a MetaSound Source just to change a sample or a volume. Use a preset or an input.

### 2.3 Block rate and latency

- MetaSounds process audio in **blocks**. `au.MetaSound.BlockRate` sets how many blocks per second are rendered (default **100**, i.e. 10 ms blocks).
- A **lower** block rate means larger blocks: **less CPU overhead but more latency**. One published tuning uses **28** on lower-end machines. Treat that as a starting point to test, not a rule.
- Keep the default for music and rhythm features that need tight timing (Quartz). Only consider lowering it if the audio render thread is proven to be the bottleneck.

### 2.4 Warm-up and first-play hitches

- The first time a MetaSound plays, its graph is built. For sounds that must play instantly in combat (weapons, UI), **preload and warm them up** during loading.
- Recent engine versions add **operator caching** so this build doesn't repeat. Check *Project Settings → MetaSounds* in your engine version for precache options.
- Keep MetaSound assets **loaded** (hard references from the weapon or character that plays them, or asset manager bundles) instead of loading on first play, which is a sync load (see `Common_Bugs_Guide.md` section 14.3).

---

## 3. MetaSound lifetime

The most common MetaSound bug is a **voice that never ends**.

- A MetaSound **Source** keeps playing until it's stopped or its graph triggers **On Finished**. For one-shots (the **UE.Source.OneShot** interface), connect the end of playback (for example the Wave Player's *On Finished*, or the end of an envelope) to the **On Finished** output.
- If you don't, the sound goes silent but the **voice stays alive**, using a voice slot, CPU, and possibly a concurrency slot, until something stops it. After a few minutes of combat, new sounds start getting culled.
- **Looping sounds** (ambience, engines): stop them explicitly (`AudioComponent->Stop()` / *Fade Out*) when the owner is destroyed or out of range. Set *Auto Destroy* on spawned audio components.
- **Check:** after a big fight, `stat audio` / Audio Insights should return to the baseline voice count. A number that only goes up is a leak.

---

## 4. Parameters and gameplay integration

- **Set parameters on change, not every tick.** `SetFloatParameter` / `SetIntParameter` / `SetTriggerParameter` send a message to the audio thread. Hundreds of calls per frame from Blueprint ticks add game-thread cost for nothing. Update only when the value changes meaningfully (for example speed changed by more than 2%).
- Use **Parameter Interfaces** so gameplay code talks to many MetaSounds through the same named inputs (e.g. `Speed`, `Surface`), instead of per-asset logic.
- **Spawning audio components:**
  - `PlaySoundAtLocation` / `SpawnSoundAtLocation` for fire-and-forget one-shots.
  - Reuse a **persistent audio component** for sounds the actor plays repeatedly (engine, footsteps), instead of spawning a new one each time.
- **Distance gating on the gameplay side:** don't even trigger sounds that are far outside the attenuation range (a footstep 200 m away). It saves spawn and concurrency work before the audio engine culls them.
- **Quartz** for music and rhythm-synced gameplay: sample-accurate scheduling instead of timers.

---

## 5. Voices, concurrency and virtualization

### 5.1 Voice limit

- The base config sets **`AudioMaxChannels=64`** (`Config/DefaultEngine.ini`, Windows section). That's the maximum number of *real* voices. Everything above it is culled or virtualized.
- For 120 fps on 6-core CPUs, **32–64** real voices is a sensible range. More voices mean more CPU on the audio threads, which the game thread shares cores with.

### 5.2 Sound Concurrency: the main tool

Create **Sound Concurrency** assets per category and assign them to sounds (or via Sound Classes):

| Category | Max count (example) | Resolution rule |
|---|---|---|
| Gunfire (per weapon type) | 6–8 | Stop Farthest then Oldest |
| Impacts / bullet hits | 8–10 | Stop Quietest |
| Footsteps | 6 | Stop Farthest |
| Explosions | 4 | Stop Oldest |
| Voice lines | 2–3 (+ priority) | Prevent New / priority-based |
| UI | 4 | Stop Oldest |
| Ambient loops | 8–12 | Stop Quietest |

- Use **Retrigger Time** (minimum time between identical sounds) to stop 20 identical impact sounds in one frame.
- Use **Volume Scaling** (duck older instances) for dense repeated sounds instead of playing them all at full volume.

### 5.3 Virtualization

- **Virtualization** keeps inaudible looping sounds (out of range) tracked without rendering them, and resumes them when they're audible again.
- Set the **Virtualization Mode** in the sound's attenuation or advanced settings:
  - Use *Play when Silent* only for loops that must stay in sync (music-driven ambience).
  - Most loops should be allowed to virtualize.
- **Priority:** give important sounds (player weapon, dialogue, critical cues) higher priority, so they win when the voice limit is reached.

---

## 6. Sound waves: compression, streaming and loading

| Asset type | Compression | Loading |
|---|---|---|
| Very frequent short SFX (footsteps, UI clicks, small impacts) | **ADPCM** (cheap to decode, ~4× smaller than PCM) or PCM for the most critical | Load on init, keep resident |
| Common SFX (weapons, impacts) | Default codec (Bink Audio / Ogg / Opus, depending on version and platform) at a sensible quality | Retain on load / prime |
| Long ambience loops | Default codec | **Stream** |
| Music, long dialogue | Default codec, lower quality where acceptable | **Stream** (force streaming, seekable if you need to jump) |

- **Decoding costs CPU**, and compressed formats cost more to decode than PCM/ADPCM. Many decoders at once (section 2.1) add up.
- **Stream caching:** enable **Stream Caching** (*Project Settings → Platforms → Windows → Audio → Stream Caching*) and give it a cache size in the platform settings. Long sounds then stream in chunks instead of loading fully into memory.
- **Sample rate:** 48 kHz is the base config. Most SFX sound the same at lower **per-asset sample rate overrides** (for example 24–32 kHz for low-frequency rumbles, cloth and footsteps), which saves memory and decode time.
- **Mono vs stereo:** 3D-positioned sounds should be **mono**. Stereo 3D sounds cost more to spatialize and often sound wrong.
- **Loading:** reference sounds through the objects that use them (weapon data assets). Avoid loading big sound banks for a whole level if only a few are used. Check with the Size Map.

---

## 7. Spatialization, attenuation and occlusion

- **Attenuation assets:** share a few **Sound Attenuation** assets (Small / Medium / Large / Huge) instead of per-sound overrides. Tight *Falloff Distance* = fewer audible voices.
- **Spatialization method:**
  - **Panning** (cheap) for most sounds.
  - **HRTF / binaural** only for key positional sounds, or when the platform or player enables it (for headphones).
- **Occlusion** (*Enable Occlusion* on attenuation) runs **line traces on the game thread** for each sound, at an *Occlusion Trace Interval*.
  - Enable it only for sounds where it matters (enemy footsteps, gunfire).
  - Use an **interval of 0.1–0.2 s**, not every frame.
  - Trace on a dedicated audio/visibility channel (`120FPS_Guide.md` section 21.3).
- **Focus and air absorption:** cheap. Use them freely.
- **Reverb send per source:** send sounds to shared reverb submixes (section 8) rather than adding reverb inside each sound.

---

## 8. Effects: submixes, reverb and buses

- **Put effects on submixes, not per voice.** One reverb on a "World" submix serves every sound routed to it. A reverb inside each MetaSound runs once per voice.
- **Convolution reverb** is expensive. Use one or two for key spaces (cathedral, cave) on a submix, and use the algorithmic reverb (or Audio Volumes with reverb settings) elsewhere.
- **Source effect chains:** keep them short. They run per voice.
- **Audio Buses** (and MetaSound audio bus nodes): route several sounds into one processing chain (for example all weapons into one compressor).
- **Audio Modulation** plugin (Control Buses and Modulators) for global volume and ducking, instead of updating many sounds from gameplay code.
- **Submix analysis** (envelope following, spectrum analysis) for gameplay or UI costs CPU. Enable it only on the submixes you read.

---

## 9. Engine audio settings

From `Config/DefaultEngine.ini` (`[/Script/WindowsTargetPlatform.WindowsTargetSettings]`):

| Setting | Base config | Notes |
|---|---|---|
| `AudioSampleRate` | 48000 | Standard. Lower only on very weak platforms |
| `AudioCallbackBufferFrameSize` | 1024 | Bigger = less CPU overhead, more latency. 512 for latency-sensitive games if the CPU allows |
| `AudioNumBuffersToEnqueue` | 1 | Low latency. Raise to 2 if you get crackling on weak CPUs |
| `AudioMaxChannels` | 64 | Real voice limit (section 5.1) |
| `AudioNumSourceWorkers` | 4 | Source processing spread over worker threads. With 6-core CPUs, 4 is a good balance |

Change these only after measuring. Crackling means the audio render thread is missing deadlines: first reduce voice count and per-voice effects, then raise the buffer size.

---

## 10. Common MetaSound and audio bugs

| Symptom | Cause | Fix |
|---|---|---|
| Voices keep increasing over time, and new sounds stop playing | One-shot MetaSounds never trigger **On Finished**, or loops aren't stopped | Section 3 |
| Sound plays late or first shot is silent | First-play graph build or sync load | Preload and warm up (section 2.4) |
| Crackling or dropouts | Audio render thread overloaded, or buffer too small | Fewer voices and per-voice effects, bigger buffer (section 9) |
| Sound cut off unexpectedly | Concurrency or voice limit culled it (low priority) | Raise priority, adjust concurrency rules |
| Parameter changes ignored | Wrong input name or type, or set before the sound starts | Match the input names exactly. Set parameters after `Play`, or use `SetParameters` on the component before playing, depending on your setup |
| Looping sound restarts when coming back in range | Virtualization mode set to restart | Use a virtualization mode that keeps the loop in sync |
| Positional sound feels wrong or is too loud at distance | Stereo asset used in 3D, or attenuation not set | Mono sources, shared attenuation presets |
| Game-thread spikes during firefights | Occlusion traces on every sound, or audio components spawned per shot | Occlusion only where needed at 0.1–0.2 s, reuse components (sections 4, 7) |

---

## 11. Budgets

Starting budgets for the 120 fps targets (Tier A / Tier B CPUs, see `120FPS_Guide.md` section 1):

| Item | Tier A (6C/12T, i5-12400 class) | Tier B (Ryzen 5 3600 class) |
|---|---|---|
| Real voices (`AudioMaxChannels`) | 48–64 | 32–48 |
| Voices with per-voice DSP beyond simple filters | ≤ 10 | ≤ 6 |
| Convolution reverbs active | ≤ 2 | ≤ 1 |
| Sounds with occlusion traces | ≤ 20 at 0.1–0.2 s interval | ≤ 12 |
| Game-thread audio cost (spawns, parameters, traces) | ≤ 0.3 ms | ≤ 0.3 ms |
| Resident audio memory | ≤ 200–300 MB | ≤ 200 MB |

---

## 12. Checklist

**MetaSounds**
- [ ] One-shot MetaSounds trigger **On Finished**. Loops are stopped explicitly.
- [ ] No reverb, convolution or big compressors inside per-voice graphs. They're on submixes or buses.
- [ ] Few Wave Players per voice. Layers pre-mixed where possible.
- [ ] Presets for variants, Patches for shared logic. Constructor pins for values that don't change.
- [ ] Combat-critical MetaSounds preloaded and warmed up.
- [ ] Block rate left at the default unless the audio thread is proven to be the bottleneck.

**Gameplay and voices**
- [ ] Parameters set on change, not per tick. Persistent components for repeated sounds.
- [ ] Concurrency assets per category with sensible max counts, rules and retrigger times.
- [ ] Priorities set, loops allowed to virtualize.
- [ ] Voice count returns to the baseline after combat (no leaks).

**Assets and settings**
- [ ] ADPCM/PCM for very frequent short SFX. Streaming + stream caching for long audio.
- [ ] 3D sounds are mono. Per-asset sample rate overrides where they're inaudible.
- [ ] Shared attenuation presets. Occlusion only where needed, at 0.1–0.2 s.
- [ ] Engine audio settings measured, not guessed.

---

## 13. Sources

- [Epic – MetaSounds: The Next Generation Sound Sources](https://dev.epicgames.com/documentation/unreal-engine/metasounds-the-next-generation-sound-sources-in-unreal-engine?lang=en-US)
- [Epic – MetaSounds Relative Render Cost (roadmap)](https://portal.productboard.com/epicgames/1-unreal-engine-public-roadmap/c/1733-metasounds-relative-render-cost)
- [Zuko Media – UE5 MetaSound Performance + Latency Tips](https://zukomedia.com/articles/unrealengine5-metasound-performance-tips/)
- [Unreal Community Wiki – MetaSounds](https://unrealcommunity.wiki/metasounds-d660ee)
- [SFX Engine – Unreal Engine Audio System Explained](https://sfxengine.com/blog/unreal-engine-audio-system-explained)
- [ElectricWave – UE5 Audio Implementation: MetaSounds Case Study](https://electricwave.eu/unreal-engine-5-audio-implementation-metasounds/)
- [AES PNW – Interactive Audio and MetaSounds in UE5](https://www.aes-media.org/sections/pnw/pnwrecaps/2023/may2023/index.htm)
- [Epic Forums – High CPU load with MetaSound Patch](https://forums.unrealengine.com/t/high-cpu-core-load-while-passing-metasound-patch/2135355)
