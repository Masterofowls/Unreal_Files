# Avoiding Common Bugs and Errors in Unreal Engine 5

This is a practical guide to the bugs, crashes and errors that nearly every Unreal project runs into, and how to prevent them. It covers UE 5.x in C++ and Blueprint.

Each section is organized the same way: **symptom → cause → prevention → fix**. If you're chasing a specific problem, start with the [symptom index](#0-symptom-index). If you're setting up a new project, read sections 1–4 first, because most of the other bugs start there.

Support files in this repo:
- `Config/DefaultEditorPerProjectUserSettings.ini`: safe Live Coding defaults for the whole team (section 2).
- `Templates/UE.gitattributes`: Git LFS setup with file locking (section 1).
- `Docs/120FPS_Guide.md`: performance problems (stutter, low fps) are covered there, not here.

---

## Contents

0. [Symptom index](#0-symptom-index)
1. [Project setup and source control](#1-project-setup-and-source-control)
2. [C++ build and editor workflow](#2-c-build-and-editor-workflow)
3. [Object lifetime and memory: the #1 crash source](#3-object-lifetime-and-memory)
4. [Initialization order and lifecycle](#4-initialization-order-and-lifecycle)
5. [Blueprint pitfalls](#5-blueprint-pitfalls)
6. [Renaming and moving assets and code](#6-renaming-and-moving-assets-and-code)
7. [Gameplay logic bugs](#7-gameplay-logic-bugs)
8. [Multiplayer and replication](#8-multiplayer-and-replication)
9. [Rendering and visual bugs](#9-rendering-and-visual-bugs)
10. [Physics and collision bugs](#10-physics-and-collision-bugs)
11. [Animation bugs](#11-animation-bugs)
12. [UI (UMG) bugs](#12-ui-umg-bugs)
13. [Level streaming and World Partition](#13-level-streaming-and-world-partition)
14. [Packaging and cooking errors](#14-packaging-and-cooking-errors)
15. [Crashes: diagnosing and reading them](#15-crashes)
16. [Engine upgrades and plugins](#16-engine-upgrades-and-plugins)
17. [Debugging toolkit](#17-debugging-toolkit)
18. [Prevention checklist](#18-prevention-checklist)
19. [Sources](#19-sources)

---

## 0. Symptom index

| Symptom | Most likely cause | Section |
|---|---|---|
| Random crash, `Access violation reading location 0x...` | Dangling UObject pointer with no `UPROPERTY` | 3.1 |
| Object becomes null "by itself" after a while | Garbage collected: nothing holds a `UPROPERTY` reference | 3.1, 3.3 |
| `Accessed None trying to read property` (Blueprint) | Reference not set, destroyed, or not loaded yet | 5.1, 4 |
| Blueprint variables reset, components missing or with blank details | Hot Reload or Live Coding reinstancing corruption | 2.1 |
| Blueprint won't open / "may crash" after a C++ rename | Missing Core Redirect | 6.2 |
| Works in the editor (PIE), broken in the packaged build | Editor-only code/assets, soft refs not loaded, map not cooked | 14.3 |
| `Unknown Cook Failure` | Real error is earlier in the log | 14.1 |
| `unresolved external symbol` (linker error) | Missing module in `Build.cs` or missing `MODULE_API` | 2.3 |
| Works in single player, broken for clients | Code assumes authority; RPC not owned | 8 |
| Client disconnects under load | Spamming reliable RPCs | 8.2 |
| Character rubber-bands when speed changes | Movement change without prediction | 8.4 |
| Input doesn't work after respawn or level change | Enhanced Input mapping context not re-added | 7.3 |
| Game speed depends on frame rate | Missing `DeltaTime`, per-frame logic | 7.1 |
| Jitter far from the world origin | Float precision, LWC misuse | 7.2 |
| Objects tunnel through walls | No sweep / CCD for fast movers | 10.1 |
| Overlap or hit events don't fire | Missing *Generate Overlap Events* / *Simulation Generates Hit Events*, wrong responses | 10.2 |
| Montage doesn't play | Missing slot node in the Anim BP | 11.1 |
| Light leaking indoors (Lumen) | Walls too thin, bad SDF | 9.2 |
| Flickering or blocky shadows (VSM) | Page pool overflow, WPO invalidation | 9.3 |
| Ghosting or smearing behind moving objects | Missing velocities (TSR) | 9.4 |
| `GPU crashed or D3D device removed` | VRAM exhausted, driver timeout (TDR), shader bug | 15.3 |
| Save file breaks after an update | No save versioning, saved object pointers | 7.4 |
| Widget disappears or crashes later | Widget not referenced, garbage collected | 12 |
| Actor reference null in World Partition | Target cell not loaded | 13 |
| Lost work, merge conflicts on `.uasset` | Binary assets without locking | 1.2 |

---

## 1. Project setup and source control

### 1.1 Never commit generated folders

`Saved/`, `Intermediate/`, `DerivedDataCache/`, `Binaries/` (unless you distribute binaries to artists), `.vs/`, and `*.sln`. The repo's root `.gitignore` already covers these.

Committing them causes phantom build errors, stale DLLs being loaded, and huge repositories.

### 1.2 Binary assets can't be merged, so lock them

`.uasset` and `.umap` are binary. If two people edit the same asset, one person's work is lost. There's no merge.

- **Git:** use Git LFS with `lockable` (see `Templates/UE.gitattributes`). Run `git lfs lock <file>` before editing and unlock after pushing.
- **Perforce:** exclusive checkout (`+l`) on `.uasset` and `.umap` via the typemap.
- **Enable the editor's source control integration** (Revision Control, top-right of the editor). It shows who has an asset checked out and warns before you edit it.
- **World Partition maps:** use **One File Per Actor** (on by default). Each actor is its own file, so several people can work in one map.

### 1.3 Pin the engine version

- Keep `EngineAssociation` in the `.uproject` consistent across the team. Mixing 5.4 and 5.5 editors re-saves assets in a newer format that the older editor can't open.
- Upgrade the engine in a branch (section 16).

### 1.4 Keep the project path short (Windows)

- Put the project at something like `D:\Proj\MyGame`, not deep inside `Documents\...`.
- Cooking produces long paths, and Windows' 260-character `MAX_PATH` limit causes "file name too long" and "can't find file" cook errors.
- Also enable Windows long-path support on build machines.

### 1.5 Back up before risky operations

Commit, or copy `Content/` and `Config/`, before:
- an engine upgrade
- a mass rename or move
- Fix Up Redirectors on a large folder
- plugin installs
- reparenting Blueprints

A corrupted asset can only be fixed by rolling back.

---

## 2. C++ build and editor workflow

### 2.1 Live Coding and Hot Reload: the main cause of Blueprint corruption

**Symptoms:**
- Blueprint variables reset to defaults.
- Components that can't be removed and show a blank Details panel.
- Properties that won't save.
- Duplicate `REINST_` or `HOTRELOADED_` classes.
- Crashes on opening a Blueprint.

**Why:**
- *Hot Reload* (the old system) creates new class versions in memory and patches instances.
- *Live Coding with Reinstancing* can serialize temporary data into `.uasset` files, often with **no warning**.

**Prevention** (already set in `Config/DefaultEditorPerProjectUserSettings.ini`):

| Setting (*Editor Preferences → Live Coding*) | Value | Why |
|---|---|---|
| Enable Live Coding | **On** | Turning it off silently falls back to Hot Reload, which is worse |
| Enable Reinstancing | **Off** | Stops class-layout patching, the corruption path |
| Automatically Compile Newly Added C++ Classes | **Off** | New reflected types need a full build |

**The rule:**
- Live Coding (Ctrl+Alt+F11) is only for editing **function bodies in `.cpp` files**.
- For any change to a **header**, `UPROPERTY`, `UFUNCTION`, `USTRUCT`, a constructor, or adding or removing classes: **close the editor, build from the IDE, then reopen.**
- Never press *Build* in the IDE while the editor is open without Live Coding.

**Fix:** revert the corrupted Blueprint from source control. There's no reliable in-editor repair.

### 2.2 Unreal Header Tool (UHT) errors

| Error | Fix |
|---|---|
| `#include found after .generated.h file` | `#include "MyClass.generated.h"` must be the **last** include in the header |
| `Missing '*' in expression` / UCLASS parse errors | `GENERATED_BODY()` must be the first line inside the class body. Don't put reflected macros inside `#if` blocks (except `WITH_EDITORONLY_DATA` for properties) |
| `Unable to find 'class', 'delegate'...` | UCLASS/USTRUCT names need the correct prefix: `A` actors, `U` objects, `F` structs, `E` enums, `I` interfaces |
| `UPROPERTY` on unsupported type | Reflected properties can't be raw `TSharedPtr`, `std::` types, or nested containers (`TArray<TArray<>>`). Wrap them in a `USTRUCT` |
| Changes in the header not picked up | Stale `Intermediate/`. Close the editor, delete `Intermediate/` and `Binaries/`, regenerate project files, rebuild |

### 2.3 Linker and module errors

- **`unresolved external symbol`:**
  - Add the module that defines the symbol to `PublicDependencyModuleNames` or `PrivateDependencyModuleNames` in your `*.Build.cs` (for example `"EnhancedInput"`, `"UMG"`, `"Niagara"`, `"AIModule"`, `"GameplayTags"`).
  - If the symbol is from *your* other module, mark the class `MYMODULE_API`.
- **Circular includes:** use forward declarations (`class UMyComponent;`) in headers and include in the `.cpp`. Include what you use (IWYU).
- **Editor code in a runtime module:** anything using `UnrealEd`, `Slate` editor widgets or `GEditor` must be in an **Editor** module, or inside `#if WITH_EDITOR`. Otherwise the editor builds fine and **packaging fails** (section 14).
- **Plugin loading phase:** a module that other modules use during startup needs `"LoadingPhase": "PreDefault"` or earlier in the `.uplugin` / `.uproject`.

### 2.4 Clean rebuild recipe (for "impossible" build states)

1. Close the editor and IDE.
2. Delete `Binaries/`, `Intermediate/`, `Saved/` (keep `Saved/Config` if you want local settings) and `.vs/`. Do the same inside each project plugin.
3. Right-click the `.uproject` → *Generate Visual Studio project files*.
4. Build `Development Editor` from the IDE, then open the editor.

---

## 3. Object lifetime and memory

Unreal's garbage collector (GC) only knows about references it can **see**. Most "random" crashes come from references it couldn't see.

### 3.1 Always hold UObject pointers in a UPROPERTY

```cpp
// BAD: invisible to GC. The object can be collected, the pointer dangles -> crash.
AActor* Target;

// GOOD: visible to GC, keeps the object alive, and is nulled when an actor is destroyed.
UPROPERTY()
TObjectPtr<AActor> Target;

// GOOD for observers/caches: doesn't keep it alive, never dangles.
TWeakObjectPtr<AActor> WeakTarget;
if (AActor* T = WeakTarget.Get()) { /* safe to use T this frame */ }
```

- Containers too: `UPROPERTY() TArray<TObjectPtr<UItem>> Items;`, and the same for `TMap` and `TSet`.
- Use **`TObjectPtr`** for all UObject members (UE5 standard). It's **required** if you ever enable incremental GC.
- A **non-UObject** class (plain C++ or a Slate widget) that holds UObjects must derive from `FGCObject` and implement `AddReferencedObjects`, or use `TStrongObjectPtr`.
- **Static or global UObject pointers:** avoid them. If you really need one, `AddToRoot()` it, then `RemoveFromRoot()` on shutdown.

### 3.2 Check validity correctly

```cpp
if (IsValid(Target))                 // null + not pending destruction (garbage)
if (Target != nullptr)               // NOT enough: a destroyed actor can still be non-null this frame
if (WeakTarget.IsValid())            // for weak pointers
```

In Blueprints, use the **Is Valid** node or a *Validated Get*, not `!= None`.

### 3.3 Objects you create

- `NewObject<UMyObj>(Outer)`: the **outer** doesn't keep the object alive. Store it in a `UPROPERTY` or it gets collected.
- Call `CreateDefaultSubobject` **only in the constructor**. At runtime, use `NewObject` + `RegisterComponent()`.
- Widgets: `CreateWidget` result → store it in a `UPROPERTY` if you keep it (section 12).

### 3.4 Timers, delegates, lambdas and async work

| Pitfall | Safe pattern |
|---|---|
| Timer fires after the actor is destroyed | Use a member `FTimerHandle`. Call `GetWorldTimerManager().ClearAllTimersForObject(this)` in `EndPlay` |
| Delegate calls into a destroyed object | Bind with `AddUObject` / `AddDynamic` / `AddWeakLambda(this, ...)`, not `AddLambda([this]...)`. Call `RemoveAll(this)` in `EndPlay` |
| Lambda captures `this` for async work | Capture `TWeakObjectPtr<ThisClass> WeakThis = this;` and check it before use |
| Touching UObjects from a worker thread | UObjects are game-thread only. Compute on the worker, then `AsyncTask(ENamedThreads::GameThread, ...)` to apply the results |
| Dynamic delegate bound twice | `AddUniqueDynamic`, or remove before adding, to avoid double calls |
| `TSharedPtr` reference cycles (memory leak) | Make one side `TWeakPtr` |

### 3.5 Destroy semantics

- `Destroy()` marks the actor for destruction. It stays non-null until GC runs, so always use `IsValid()`.
- Do cleanup in **`EndPlay`**, not the destructor. The destructor runs later, on GC, and the world may already be gone.

---

## 4. Initialization order and lifecycle

**The rule:** the order in which *different* actors run `BeginPlay` is **not guaranteed**. Never assume another actor, controller, HUD or subsystem is fully initialized.

| Stage | Safe to do | Don't |
|---|---|---|
| **Constructor** (also runs for the CDO) | `CreateDefaultSubobject`, set default values | Use `GetWorld()` (null for the CDO), spawn actors, access other actors, run random or gameplay logic |
| `PostInitializeComponents` | Wire up your *own* components | Access other actors |
| **`BeginPlay`** | Gameplay start, timers, binding to your own components | Assume the controller, possession, PlayerState or other actors are ready |
| `EndPlay` | Clear timers, unbind delegates, release resources | Rely on other actors still existing |

Common traps:
- **GameMode exists only on the server.** Clients get `nullptr` from `GetAuthGameMode()`. Put shared data in **GameState** or **PlayerState**.
- **Pawn possession timing:**
  - Server: use `PossessedBy` or `OnPossess`.
  - Owning client: use `PawnClientRestart` or `OnRep_Controller`.
  - Don't set up input or HUD in the Pawn's `BeginPlay`, because the controller may not be assigned yet.
- **PlayerState** arrives later on clients. React in `OnRep_PlayerState`.
- **Construction script** runs in the editor on every move or property change: no heavy work, no random numbers without a seed, no spawning.
- **Level travel:** `GameInstance` and subsystems persist between levels, and actors don't (unless seamless travel keeps them). Store cross-level data in the GameInstance, a subsystem or a save game.
- **Subsystems:** prefer `UGameInstanceSubsystem` or `UWorldSubsystem` over singletons. They have a defined lifetime and initialization order (`Collection.InitializeDependency<>`).

---

## 5. Blueprint pitfalls

### 5.1 "Accessed None" errors

These are logged in PIE's Message Log. Every one of them is a real bug, even if the game seems to work.

- Use **Is Valid** / *Validated Get* before using references that can be empty or destroyed.
- Set references when the object is created (Spawn → promote to variable), not with *Get All Actors of Class* at random times.
- Treat Accessed None as a blocker: fix all of them before a milestone.

### 5.2 Hard references and cast chains

- Casting to a Blueprint class, or having a variable of that type, **loads that Blueprint and everything it references** whenever your Blueprint loads. A player BP that casts to every enemy BP loads every enemy, including meshes, sounds and VFX. The result is long load times, high memory use and circular dependencies.
- **Prevention:**
  - Communicate via **Blueprint Interfaces**, **Event Dispatchers**, **Gameplay Tags** or C++ base classes (casting to a C++ class is free).
  - Use **soft references** + async load for heavy content.
  - Check with the **Reference Viewer** and **Size Map** (right-click an asset).

### 5.3 Structs and enums

- **Blueprint-defined structs and enums** used by many assets are a known corruption risk when you change them (renaming or removing members, reordering). Symptoms: Blueprints fail to compile, and values reset to default.
- **Prevention:** define core data types (inventory items, stats, save data) as **C++ `USTRUCT`/`UENUM`**. Add members only at the end, and never rename without a Core Redirect.

### 5.4 Other Blueprint rules

- **No logic in the Level Blueprint** beyond level-specific scripting. It can't be reused and other code can't reference it.
- **`Delay` and other latent nodes** can't be used inside functions, and inside loops or Tick they don't wait the way you'd expect (a loop doesn't pause per iteration, and Tick keeps restarting the delay). Use timers.
- **Infinite loop detected:** there's a runaway loop, typically a `While` that never ends. The engine aborts after `MaximumLoopIterationCount` (1,000,000 by default). Fix the loop logic; don't raise the limit.
- **Tick in Blueprints:** turn it off by default (*Start with Tick Enabled* off). Most logic should be event-driven.
- **Event Dispatchers:** unbind on `EndPlay`. Bound dead objects are skipped, but listeners that are still alive keep getting calls you didn't expect.
- **Compile all Blueprints regularly** (section 18). A Blueprint that fails to compile often only fails loudly at cook time.

---

## 6. Renaming and moving assets and code

### 6.1 Assets: redirectors

- **Always rename and move assets inside the editor** (Content Browser), never in Windows Explorer or git. The editor updates references and leaves a **redirector** at the old path.
- Stale redirectors cause broken references, cook failures and "can't find file" errors. After moving things, right-click the folder → **Fix Up Redirectors**, then commit the moved assets **and** the deleted redirectors together.
- Deleting an asset: use **Delete → Replace References** to point users at a substitute, or you'll get a lot of `None` references.

### 6.2 C++: Core Redirects

Renaming a C++ class, property, function, struct or enum that Blueprints or saved assets use **breaks those assets**: Blueprints lose their parent class, and properties lose their values. Add redirects in `DefaultEngine.ini` (or the plugin's own ini) **in the same commit** as the rename:

```ini
[CoreRedirects]
; class rename
+ClassRedirects=(OldName="/Script/MyGame.OldEnemy",NewName="/Script/MyGame.Enemy")
; property rename inside a class
+PropertyRedirects=(OldName="/Script/MyGame.Enemy.Hp",NewName="/Script/MyGame.Enemy.Health")
; function rename (keeps Blueprint call nodes working)
+FunctionRedirects=(OldName="/Script/MyGame.Enemy.DoAttack",NewName="/Script/MyGame.Enemy.Attack")
; struct and enum renames
+StructRedirects=(OldName="/Script/MyGame.OldItemData",NewName="/Script/MyGame.ItemData")
+EnumRedirects=(OldName="/Script/MyGame.EOldState",NewName="/Script/MyGame.EState")
```

Then open and **re-save** the affected assets. Once everything is re-saved (and older saves no longer need to load), the redirects can be removed later.

### 6.3 Reparenting Blueprints

Reparenting a Blueprint to a new class can drop variables and components that existed in the old parent. Make a backup first, and compare the Details panel before and after.

---

## 7. Gameplay logic bugs

### 7.1 Frame-rate dependence

Your game will run at 30–240 fps (see the 120 fps guide), so anything per frame has to scale with time:

```cpp
// BAD: speed doubles at 120 fps vs 60 fps
Location += Direction * 5.f;
// GOOD
Location += Direction * SpeedCmPerSec * DeltaSeconds;
```

- Interpolation: `FMath::FInterpTo(Current, Target, DeltaSeconds, Speed)`. Don't use `Lerp(a, b, 0.1f)` every frame.
- Use **timers** instead of counting frames. Physics forces: `AddForce` is time-scaled, but `AddImpulse` is a one-shot, so don't call it every tick.
- Test at a **30 fps cap and uncapped** (`t.MaxFPS 30`, `t.MaxFPS 0`).

### 7.2 Floats, precision and Large World Coordinates (LWC)

- UE5 uses **double-precision** positions (`FVector` is double). Don't store world positions in `FVector3f` or `float`, or you'll get jitter far from the origin.
- Compare floats with a tolerance: `FMath::IsNearlyEqual(A, B)`, `Vector.Equals(Other, Tolerance)`.
- In materials, use the LWC-aware nodes (*Absolute World Position* is LWC-safe). Precision problems in WPO or noise far from the origin show up as flickering or swimming.

### 7.3 Input (Enhanced Input)

- **Input doesn't work** usually means the **Input Mapping Context** wasn't added for the local player.
  - Add it in `PawnClientRestart` (or `SetupPlayerInputComponent`) through `UEnhancedInputLocalPlayerSubsystem`, and **re-add it after respawn or possession changes**.
  - Also check the input action is bound in `SetupPlayerInputComponent` with the correct trigger.
- **Stuck in UI input mode:** after closing a menu, call `SetInputMode(FInputModeGameOnly())` and hide the cursor. Pair every mode change with its opposite.
- Test **gamepad and keyboard** plus UI focus on every menu. Losing gamepad focus is a common "soft lock".

### 7.4 Save games

- **Never save UObject pointers.** Save IDs, soft object paths (`FSoftObjectPath`), gameplay tags and plain values.
- Add a **version number** to your `USaveGame` and migrate old saves in code. Without versioning, any update breaks existing saves.
- Save **asynchronously** (`AsyncSaveGameToSlot`) to avoid a hitch. Write to a temp slot and swap, so a crash mid-save doesn't destroy the only save.

### 7.5 Other frequent logic bugs

- **Random numbers:** use `FRandomStream` with a seed for anything that needs to be reproducible (procedural generation, networked randomness).
- **Time dilation and pause:** timers and ticks respect global time dilation. UI animations and menus need to *Tick Even When Paused*, or use real time.
- **Text:** use `FText` for player-facing strings (it's localizable). `FString` concatenation for UI breaks localization.
- **Gameplay Tags:** add tags in *Project Settings → Gameplay Tags*, not ad hoc. A typo in `RequestGameplayTag` fails at runtime (and ensures in development builds).

---

## 8. Multiplayer and replication

**Rule 0:** Unreal is **server-authoritative**. Most multiplayer bugs come from code that silently assumes it runs on the server. The classic symptom is "works in single player, half of it breaks for clients". **Test with 2+ clients from day one** (*Play → Number of Players 2*, *Net Mode: Play as Client*).

### 8.1 Replication setup checklist

- The actor has `bReplicates = true`, and the component has `SetIsReplicatedByDefault(true)`.
- Every replicated property is declared `UPROPERTY(Replicated)` or `UPROPERTY(ReplicatedUsing=OnRep_X)` **and** registered in `GetLifetimeReplicatedProps` with `DOREPLIFETIME(...)`.
- **C++ `OnRep` functions don't run on the server** (Blueprint RepNotify does). If the server needs the same reaction, call `OnRep_X()` manually after changing the value on the server.
- **Only the server changes replicated values.** Changes on a client are local and get overwritten.
- The order of replicated properties and RPCs isn't guaranteed. Don't rely on property A arriving before property B.

### 8.2 RPCs

- **Server RPCs only work on actors owned by the calling client** (their PlayerController, Pawn or PlayerState, or an actor you gave them ownership of with `SetOwner`). Otherwise the RPC is **dropped silently** with no error.
- **Don't spam reliable RPCs.** When the reliable buffer overflows, the client is **disconnected**. Cosmetic events (sounds, VFX) should be **Unreliable** or driven by replicated state.
- **Validate** server RPC input (`WithValidation`). Never trust the client (for example "I hit this enemy for 9999").
- Use `HasAuthority()` for server-only logic and `IsLocallyControlled()` for owning-client logic (camera, UI, input). They are not the same thing.

### 8.3 Spawning and references

- Spawn replicated actors **on the server only**. Actors spawned on a client exist only on that client.
- Replicated pointers to actors can arrive **before the actor itself** exists on the client, so they're `nullptr` in the first `OnRep`. Handle null and re-check later, or react in the target's `BeginPlay`.

### 8.4 Movement

- Changing `MaxWalkSpeed` and similar settings on only one side, or without prediction, causes **rubber-banding**. Change movement state through `CharacterMovementComponent` **saved moves / compressed flags** (custom CMC), or on both server and owning client at the same time.
- Teleporting a character: call it on the server. Client-side teleports get corrected back.

### 8.5 Test under bad networks

Use **Network Emulation** (*Editor Preferences → Level Editor → Play → Network Emulation*, "Bad" profile), or `NetEmulation.PktLag 150`, `NetEmulation.PktLoss 5`. Bugs that never show up on LAN appear right away.

---

## 9. Rendering and visual bugs

### 9.1 Nanite

| Bug | Fix |
|---|---|
| WPO foliage **clips or disappears** at screen edges | Raise *Max World Position Offset Displacement* on the material (WPO bounds), or the mesh's bounds scale |
| Masked foliage looks thin at distance | *Preserve Area* on the Nanite settings (5.2+) |
| Mesh looks different with Nanite on/off | The fallback mesh is used for collision, Lumen or ray tracing. Set *Fallback Relative Error* / *Fallback Target* |
| Nanite not enabled on some meshes | Translucent materials, some deformers, and unsupported features prevent it. Check with Visualize → Nanite |

### 9.2 Lumen

| Bug | Fix |
|---|---|
| **Light leaking** through walls or corners | Walls ≥ 10 cm thick, closed geometry, raise *Distance Field Resolution Scale* on thin meshes, avoid single-sided planes as walls |
| **Noisy or splotchy GI** | Don't light rooms with emissive materials. Use real lights. Raise *Final Gather Quality* only in problem areas |
| GI lags behind lighting changes | Expected with surface cache update rates. For sudden changes (lights switched on), keep update speed at default and avoid toggling many lights at once |
| Dark interiors / objects missing from GI | Mesh has no distance field or poor surface cache cards. Check Visualize → Lumen → Surface Cache |

### 9.3 Virtual Shadow Maps

| Bug | Fix |
|---|---|
| **Flickering or blocky shadows**, "page pool overflow" warning | Raise `r.Shadow.Virtual.MaxPhysicalPages` (don't hide it with bias) |
| Shadows shimmer on foliage and cost a lot | WPO invalidation. Set WPO Disable Distance (120 fps guide, section 5) |
| Shadow acne or peter-panning | Adjust the light's *Shadow Bias* / *Shadow Slope Bias* and the VSM normal bias cvars in small steps |

### 9.4 TSR / temporal artifacts

- **Ghosting or smearing** usually means missing motion vectors:
  - Enable *Output Velocity* for WPO materials.
  - Particles and translucency don't write velocity. Use *Responsive AA* on those materials, or render them after DOF.
- **Moiré or shimmering** comes from high-frequency detail. Check texture mips are generated, and avoid sub-pixel detail in normal maps.

### 9.5 Other frequent visual bugs

- **Pink/black materials or `Failed to compile Material for platform PCD3D_SM6`:** open the material and fix the compile error. This is often a missing function or texture after a move, or a node removed in an engine upgrade. It also causes cook failures.
- **Auto exposure makes scenes too bright or dark:** set explicit *Min/Max EV100* in the Post Process Volume. Don't leave the default range across the whole game.
- **Z-fighting / flicker on coplanar surfaces:** offset the geometry, or use decals. Don't set the near clip plane too small.
- **"Texture streaming pool over budget" / blurry textures:** see the 120 fps guide, section 13.
- **Shader compiles take forever:** share the **Derived Data Cache** across the team (shared DDC or Unreal Cloud DDC), and keep static switch permutations low.

---

## 10. Physics and collision bugs

### 10.1 Tunneling (objects pass through walls)

- Moving with `SetActorLocation` **without a sweep** ignores collision. Use `bSweep=true` for movement that should be blocked.
- For fast simulated objects, enable **CCD** on that body. For bullets, use line traces or `ProjectileMovementComponent` (which sweeps), not physics bodies.

### 10.2 Events that don't fire

| Event | Requirements |
|---|---|
| **Overlap** | **Both** components have *Generate Overlap Events* on, and the responses are set to **Overlap** for each other's object type |
| **Hit** (physics) | *Simulation Generates Hit Events* on the simulating body, and the response is **Block** |
| Hit when moved by code | Movement uses a sweep (`bSweep=true`) |
| Trace misses | The target blocks **that trace channel**. Complex vs simple collision (`bTraceComplex`) matches what the mesh has |

### 10.3 Other physics bugs

- **Character gets stuck:** the capsule catches on complex geometry. Give stairs and ramps simple collision, check *Walkable Floor Angle* and *Max Step Height*, and avoid tiny collision gaps.
- **Physics explosion on spawn:** bodies spawned overlapping each other or a wall, or self-colliding ragdoll limbs. Spawn with *Adjust if possibly colliding*, and turn off collision between adjacent ragdoll bodies.
- **Jittery stacks / constraints:** increase solver iterations **on that body only**, give it realistic mass (not 0.01 or 10,000), and avoid extreme mass ratios (> 10:1) in joints.
- **Non-uniform scale on simulated meshes** distorts convex collision. Build correctly scaled assets instead.
- **Attached components with physics:** only the root simulates, unless children are *welded*. Simulating a child detaches it.

---

## 11. Animation bugs

| Bug | Cause | Fix |
|---|---|---|
| **Montage doesn't play** | The Anim BP has no **Slot** node for the montage's slot (e.g. `DefaultSlot`) | Add the Slot node in the AnimGraph, check the montage's slot name |
| Montage plays but no root motion | *Root Motion Mode* in the Anim BP class settings | Set *Root Motion from Montages Only* (or Everything) |
| **Notifies skipped** | URO or the budget allocator skip frames, or the character isn't rendered | Put gameplay-critical notifies on *Branching Point* montage notifies, or run the logic from gameplay code, not a cosmetic notify |
| **Thread-safety warnings / crashes** in the Anim BP | Accessing actors or components from a thread-safe function | Use **Property Access** to copy data in, not direct calls |
| **Foot sliding** | Speed and animation playback rate don't match | Stride warping / distance matching (Animation Warping plugin), or scale play rate |
| **Retargeted animation broken** | Different skeleton proportions or rest pose | IK Retargeter with matched retarget poses and chain mapping |
| **Additive animation looks wrong** | Wrong base pose type | Set *Additive Anim Type* and *Base Pose* correctly on the sequence |
| Root motion in multiplayer desyncs | Root motion from anything other than montages isn't replicated | Networked root motion only from montages |

---

## 12. UI (UMG) bugs

- **Widget disappears or crashes later:** a widget created with `CreateWidget` and not stored in a `UPROPERTY` (and not in the viewport) is garbage collected. Keep a reference.
- **Widgets created every time a menu opens and never removed** cause memory growth and duplicate event handling. Create once and show or hide it, or `RemoveFromParent` and clear the reference.
- **Property bindings** (the *Bind* dropdown) run **every frame**. Update the UI from events instead. It's faster and avoids stale-reference Accessed None errors.
- **Focus and input mode:** section 7.3. Always set keyboard/gamepad focus to a widget when a menu opens (`SetUserFocus` / `SetKeyboardFocus`).
- **Wrong layout at other resolutions:** anchor everything, check with *Preview Size* at 1080p, 1440p, 4K and ultrawide, and set the DPI scaling curve in *Project Settings → User Interface*.
- **Clicks go through the UI to the game:** widget visibility is *Visible* (hit-testable) vs *Not Hit-Testable*. Use input mode *Game and UI* correctly.

---

## 13. Level streaming and World Partition

- **References across streamed cells:** an actor in cell A holding a hard reference to an actor in cell B **forces B to load** (World Partition then groups them), or gets `nullptr` when B is unloaded. Use soft references or IDs and look the actor up when needed.
- **Always-loaded data:** gameplay-critical actors (managers, spawners, triggers the whole level needs) go in a **Data Layer** that's always loaded, or set *Is Spatially Loaded* off.
- **Streaming sources:** only the player loads cells by default. Cutscene cameras, AI far away and vehicles moving fast need their own **World Partition Streaming Source** component, or the world won't be loaded under them.
- **HLOD out of date** (holes or old buildings at distance): rebuild HLODs (*Build → Build HLODs*) after world changes, and in CI.
- **Level Instances / Packed Level Actors:** editing the source level updates every instance. Changes to one placed instance need *Break* first.
- **Sub-levels (non-WP):** loading them with `LoadStreamLevel` and using actors in them before *OnLevelLoaded / Shown* returns null references.

---

## 14. Packaging and cooking errors

### 14.1 How to find the real error

`Unknown Cook Failure` and `PackagingResults: Error` are summaries. The real error is **earlier in the log**:

1. Open the Output Log, or `Saved/Logs/` and the UAT log in `%APPDATA%\Unreal Engine\AutomationTool\Logs\` (Windows).
2. Search for **`Error:`** (and `LogCook: Error`, `LogInit: Error`). Fix the **first** one; later errors are often consequences.

### 14.2 Common causes

| Log shows | Fix |
|---|---|
| `Failed to compile Material for platform PCD3D_SM6` | Fix or delete that material (section 9.5) |
| `Couldn't find file` / `Failed to load` for an asset | Stale redirector or deleted asset still referenced: Fix Up Redirectors, *Reference Viewer* |
| Errors about `UnrealEd` / editor modules in a game target | Editor code in a runtime module (section 2.3) |
| Blueprint compile errors in the cook | Fix them (section 18: compile all Blueprints) |
| `Path too long` / file-not-found under `Saved/Cooked` | Short project path (section 1.4) |
| Plugin module missing on target | Plugin not enabled for that platform, or `Type: Editor` module used at runtime |
| Map missing in the packaged game | Add it to *Project Settings → Packaging → List of maps to include*, or cook it via the Asset Manager |
| SDK / toolchain errors | Install the exact Windows SDK / MSVC version from the engine's release notes |
| File access denied / locked | Close other editor instances, and exclude the project folders from antivirus real-time scanning |

### 14.3 Works in PIE, broken in the packaged build

The editor loads things a packaged build doesn't. The usual differences:

- **Soft references** are often already loaded in the editor. In a build they're `nullptr` until you load them. Always async-load before use.
- **Assets only referenced by string or path** aren't cooked. Reference them through the Asset Manager, a Data Asset, or *Additional directories to cook*.
- **`WITH_EDITOR` code paths**, editor-only data (`WITH_EDITORONLY_DATA`) and editor utility widgets don't exist in builds.
- **Initialization order** differs from PIE (no editor world, different load timing).
- **Config:** packaged builds read `Default*.ini` plus the user's `Saved/Config`. Editor-per-project settings don't apply.

**Prevention:** make a **packaged build weekly** (ideally in CI) and play it, not only PIE. Waiting until release finds a month of problems at once.

---

## 15. Crashes

### 15.1 Get usable callstacks

- Crash logs are in `Saved/Crashes/` and `Saved/Logs/`. **Keep the PDB (symbol) files** for every build you hand out (*Include Debug Files* for internal builds, or archive them separately).
- Reproduce in a **Development** build with `-log`, or attach the debugger (Rider / Visual Studio → *Attach to Process*).
- Use `check()` for "must never happen" (crashes in dev) and `ensure()` / `ensureMsgf()` for "shouldn't happen, keep running" (logs a callstack once).

### 15.2 Common crash signatures

| Crash text | Usual cause |
|---|---|
| `Access violation reading location 0x0000000000000xxx` (small address) | Null pointer. A missing `IsValid` check |
| `Access violation ... 0xFFFFFFFFFFFFFFFF` / garbage address | Dangling or uninitialized pointer (section 3.1), or an uninitialized member. Initialize every member in the header |
| `Assertion failed: IsValid(...)` / `IsValidIndex` | Out-of-range array access. Check `IsValidIndex(i)` |
| `Ran out of memory` / out of video memory | Memory leak or oversized content. Use `memreport -full` and the 120 fps guide memory budgets |
| Crash in `UObject::ProcessEvent` / on destroy | Calling into an object during or after destruction. Use weak pointers and unbind in EndPlay |
| Crash only in Shipping | Uninitialized variables (debug builds hide them), `check()` compiled out, and different timing |

### 15.3 GPU crash: "D3D device removed" / "GPU crashed"

- **Causes:**
  - Running out of **VRAM** (common on 8 GB cards with 4K textures).
  - A driver **timeout (TDR)** from a very long GPU frame, such as extreme settings or an infinite loop in a shader.
  - Driver bugs.
  - Unstable GPU overclocks on player machines.
- **Diagnose:**
  - Run with `-gpucrashdebugging`. On NVIDIA, use Aftermath (`r.GPUCrashDebugging=1`) to get the failing pass.
  - Compare against the VRAM budget in the 120 fps guide, section 2.4.
- **Prevent:** keep the texture pool and pages inside the VRAM budget, test on minimum-spec GPUs, and recommend current drivers.

---

## 16. Engine upgrades and plugins

- **Never upgrade mid-milestone.** Upgrade in a branch (or a copy), with a backup (section 1.5).
- **Before upgrading:** check that every marketplace/Fab plugin supports the new version. Missing plugin binaries block the project from opening.
- **After upgrading:**
  1. Rebuild C++ and fix **all deprecation warnings**. Deprecated APIs get removed in the next version.
  2. Compile all Blueprints.
  3. Fix material errors.
  4. **Resave** assets (`-run=ResavePackages`) so they're in the new format.
  5. Cook a build.
- Read the **release notes' "Upgrade notes"** section. CVars, config keys and defaults change between versions (this repo tags version-specific settings with `[5.x+]`).
- Keep third-party plugins in the project's `Plugins/` folder (not the engine) and under source control, so everyone has the same version.

---

## 17. Debugging toolkit

| Tool | Use it for |
|---|---|
| `UE_LOG` with your own log categories (`DECLARE_LOG_CATEGORY_EXTERN`) | Filterable logs. Set the verbosity per category with `Log LogMyGame Verbose` |
| **Visual Logger** (*Tools → Debug → Visual Logger*) | Recording AI and gameplay state over time with shapes in the world |
| **Gameplay Debugger** (apostrophe key `'`) | AI, perception, EQS, abilities of the actor you're looking at |
| **Blueprint debugger** (breakpoints, *Watch value*) | Stepping through Blueprint logic in PIE |
| **Rewind Debugger** | Scrubbing back through animation and gameplay |
| `showdebug` (`animation`, `input`, `camera`, `abilitysystem`) | On-screen state |
| `obj refs name=<ObjectName>` | Finding **what keeps an object alive** (memory leaks) |
| `memreport -full` | Memory by class and asset |
| **Networking Insights** / `net.*` stats | Replication bandwidth, RPC counts |
| **Collision Analyzer**, `show Collision` | Trace and collision debugging |
| **Chaos Visual Debugger** | Physics simulation recording |
| Unreal Insights | Timing, loading and memory traces (also see the 120 fps guide) |

---

## 18. Prevention checklist

**Every commit**
- [ ] No compile warnings added; the C++ build is clean.
- [ ] Changed Blueprints compile, and there are no new Accessed None errors in a test PIE session.
- [ ] Moved or renamed assets → Fix Up Redirectors, committed together.
- [ ] Renamed C++ types or properties → `[CoreRedirects]` in the same commit.
- [ ] Binary assets were locked before editing.

**Daily / CI**
- [ ] `UnrealEditor-Cmd.exe MyGame.uproject -run=CompileAllBlueprints`
- [ ] **Data Validation** plugin (*Validate Assets*) with your own validators (naming, texture sizes, missing references).
- [ ] Automation tests (*Tools → Session Frontend → Automation*): unit tests plus **Functional Tests** in test maps.
- [ ] Multiplayer smoke test: 1 listen server + 1 client with network emulation.

**Weekly**
- [ ] Cook and package a build, then **play it** (not just PIE).
- [ ] Memory check: `memreport -full` after 30 minutes of play (look for growth).
- [ ] Min-spec PC run (see the 120 fps guide tiers).

**Before a milestone or release**
- [ ] 0 Accessed None, 0 ensures, 0 Blueprint warnings in a full playthrough.
- [ ] Old saves load in the new build (save versioning).
- [ ] Crash reporter + symbols archived for this build.
- [ ] Soak test: 2+ hours of play without memory growth or crashes.

---

## 19. Sources

- [Epic – Unreal Object Handling](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-object-handling-in-unreal-engine)
- [Epic – Core Redirects](https://dev.epicgames.com/documentation/en-us/unreal-engine/core-redirects-in-unreal-engine)
- [Epic – Incremental Garbage Collection](https://dev.epicgames.com/documentation/unreal-engine/incremental-garbage-collection-in-unreal-engine?lang=en-US)
- [Epic – Collision Overview](https://dev.epicgames.com/documentation/unreal-engine/collision-in-unreal-engine---overview)
- [Epic – A Crash Course in Blueprint Replication](https://www.unrealengine.com/blog/crash-course-in-blueprints-replication)
- [Tom Looman – Unreal Engine C++ Complete Guide](https://tomlooman.com/unreal-engine-cpp-guide/)
- [nstar.dev – Live Coding is Dangerous by Default](https://blog.nstar.dev/Unreal-Engine/Live-Coding)
- [Unreal Community Wiki – Hot Reload and Live Coding](https://unrealcommunity.wiki/live-compiling-in-unreal-projects-tp14jcgs)
- [UE4 Guidebook – Preventing dangling actor pointer crashes](https://unreal.gg-labs.com/wiki-archives/common-pitfalls/how-to-prevent-crashes-due-to-dangling-actor-pointers)
- [Unreal Community Wiki – Core Redirects](https://unrealcommunity.wiki/core-redirects-jwjn8ogt)
- [X157 – UE5 Core Redirects](https://x157.github.io/UE5/Engine/Core-Redirects.html)
- [Unreal Directive – Core Redirectors](https://unrealdirective.com/articles/core-redirectors-what-you-need-to-know/)
- [Cedric Neukirchen – Multiplayer Compendium: RPCs](https://cedric-neukirchen.net/docs/multiplayer-compendium/remote-procedure-calls/)
- [WizardCell – Multiplayer Tips and Tricks](https://wizardcell.com/unreal/multiplayer-tips-and-tricks/)
- [Epic Forums – Unknown Cook Failure threads](https://forums.unrealengine.com/t/unknown-cook-failure/1841385)
