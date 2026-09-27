# Optimizing Blueprints and C++ in Unreal Engine 5

This is a practical guide to making gameplay code cheaper on the CPU, in both Blueprint and C++. It fits the frame budgets in [`120FPS_Guide.md`](120FPS_Guide.md): the game thread has **≤ 6.5 ms** per frame at 120 fps, so every ticking actor, loop and allocation counts.

Other guides in this repo cover related topics:
- [`120FPS_Guide.md`](120FPS_Guide.md): rendering, content budgets, physics, animation and actor counts.
- [`Common_Bugs_Guide.md`](Common_Bugs_Guide.md): correctness (GC crashes, lifecycle, replication). Fast code that crashes isn't an optimization.

---

## Contents

0. [Rules before optimizing](#0-rules-before-optimizing)
1. [Measure: profiling code](#1-measure-profiling-code)
2. [Blueprint optimization](#2-blueprint-optimization)
3. [When and how to move Blueprint logic to C++](#3-when-and-how-to-move-blueprint-logic-to-c)
4. [C++ optimization](#4-c-optimization)
5. [Multithreading](#5-multithreading)
6. [Networking code](#6-networking-code)
7. [Before / after patterns](#7-before--after-patterns)
8. [Build configuration](#8-build-configuration)
9. [Checklist and budgets](#9-checklist-and-budgets)
10. [Sources](#10-sources)

---

## 0. Rules before optimizing

1. **Profile first.** Epic's own guidance is to profile with Unreal Insights and fix the biggest bottlenecks before converting anything. Guessing wastes time on code that costs 0.01 ms.
2. **Profile a Test or Shipping-like build.** In the editor and in Development builds, Blueprint and C++ both run slower, and the editor adds its own ticking. PIE numbers can be 2× off.
3. **Fix the algorithm before micro-optimizing.** Not running code (events instead of Tick, caching instead of searching) beats running faster code. The order that pays off most:
   - **Don't run it:** use events instead of polling, and turn off ticks.
   - **Run it less often:** timers, tick intervals, significance.
   - **Do less work:** caching, better data structures, early-outs.
   - **Do the work faster:** C++, better memory layout, threads.
4. **Measure again after every change.** Keep the change only if the numbers improved.

---

## 1. Measure: profiling code

### 1.1 Unreal Insights (main tool)

- Launch the build (or editor) with:
  ```
  -trace=default,cpu,frame,bookmark,task -statnamedevents
  ```
  `-statnamedevents` is what makes **Blueprint function and event names** show up in the timing view. Without it you only see `BlueprintTime` blocks.
- In the Timing view, look at the **Game Thread** track. Sort the Timers panel by *Exclusive time* to find the biggest costs.
- Useful commands: `stat game` (tick, Blueprint time), `stat unit`, `dumpticks` (lists every registered tick function), `stat namedevents`.

### 1.2 Add your own scopes in C++

```cpp
#include "ProfilingDebugging/CpuProfilerTrace.h"

void UInventoryComponent::RebuildCache()
{
    TRACE_CPUPROFILER_EVENT_SCOPE(UInventoryComponent::RebuildCache); // shows in Insights
    // ...
}

// Named stat counters also show in "stat MyGame":
DECLARE_STATS_GROUP(TEXT("MyGame"), STATGROUP_MyGame, STATCAT_Advanced);
DECLARE_CYCLE_STAT(TEXT("AI Think"), STAT_AIThink, STATGROUP_MyGame);

void AMyAI::Think()
{
    SCOPE_CYCLE_COUNTER(STAT_AIThink);
    // ...
}
```

- Add scopes to every system you own (AI, inventory, abilities, spawning) **before** you need them. Then any profile immediately tells you whose code is slow.
- `CSV_SCOPED_TIMING_STAT` + `csvprofile start/stop` let you track the cost of systems over a whole play session (see `120FPS_Guide.md` section 23).

### 1.3 What "slow" means at 120 fps

| Scope | Budget (Tier B CPU, see the 120 fps guide) |
|---|---|
| Whole game thread | ≤ 6.5 ms |
| All gameplay tick + Blueprint time | ≤ 2.0 ms |
| One system (AI, inventory, abilities…) | ≤ 0.5 ms |
| One actor's tick | ≤ 5–10 µs (×300 actors = 1.5–3 ms) |
| One-off event (open a menu, pick up an item) | ≤ 1 ms, or it's a hitch |

---

## 2. Blueprint optimization

### 2.1 How Blueprint costs work

Blueprints compile to **bytecode run by a virtual machine**. The overhead is **per node executed**, not per line of logic. A node that calls a heavy C++ function (a trace, a spawn) costs about the same as in C++. A graph of 200 small math nodes costs 200 VM steps. This means:

- **Few nodes calling engine functions** → Blueprint is fine.
- **Many nodes per frame** (loops, math, per-tick logic across many actors) → expensive. This is the case to move to C++ (section 3).
- Where Blueprint is weakest (per Epic): tight loops, large data processing, many instances ticking, and anything that needs threads.

### 2.2 Tick

- Turn **Start with Tick Enabled** off by default (Class Defaults), and enable tick only while it's needed (`Set Actor Tick Enabled`).
- Replace polling ("every tick, check if X changed") with **events**: Event Dispatchers, OnComponentBeginOverlap, OnRep, Gameplay Message Subsystem, or input events.
- Periodic checks → **Set Timer by Event / Function** at 0.1–0.5 s instead of Tick.
- If it really must tick: set **Tick Interval** (for example 0.1 s) on actors and components that don't need every frame.
- **Timelines** tick while playing. For hundreds of actors, drive curves from a timer or from C++ instead of one Timeline component each.

### 2.3 Pure nodes: the hidden repeat cost

A **pure** node (no execution pins, e.g. *Get All Actors of Class*, *Get Actor Location*, your own pure functions) runs **again for every node that uses its output**, including **every iteration of a loop** that reads it.

```
BAD:  [Get All Actors Of Class] ──(array)──► [For Each Loop]      // the search re-runs on each iteration
GOOD: [Get All Actors Of Class] ─► [Set LocalActors] ─► [For Each Loop (LocalActors)]
```

- **Cache the results of pure nodes in local variables** before loops and before using them several times.
- For your own functions: only mark trivial getters **Pure**. Anything heavier should be a normal (impure) function, so it runs exactly once where you call it.

### 2.4 Expensive nodes to avoid in hot paths

| Node | Why | Instead |
|---|---|---|
| **Get All Actors of Class / with Tag / with Interface** | Iterates actors in the world | Cache once, or have actors **register** themselves with a manager/subsystem (section 7.1) |
| **For Each Loop** over big arrays every frame | Every iteration runs multiple VM nodes (it's a macro) | Move the loop to C++, or process the array in chunks across frames |
| **Find / Contains** on large arrays | Linear search | Use a **Map** or **Set** variable |
| **Spawn Actor** in combat | Construction, registration, BeginPlay | Pooling (`120FPS_Guide.md` section 18) |
| **Line traces** in loops every tick | Physics queries | Time-slice them, or batch them in C++ async traces (`120FPS_Guide.md` section 21.5) |
| **String building** (Append, Format Text, To String) each frame | Allocations | Update text on change only |
| **Print String** in gameplay logic | Costs in Development, easy to leave in | Use logs with categories, and remove them from hot paths |
| **Construction Script** with loops or spawns | Runs in the editor on every change, and at spawn | Keep it trivial, or bake the result |
| **Get Component by Class** each tick | Searches components | Cache the reference in BeginPlay |

### 2.5 Arrays and structs: copies vs references

- **Array → Get (a copy)** copies the element (a whole struct). Use **Get (a ref)** when you modify it or when it's a large struct.
- **Function inputs:** tick **Pass-by-Reference** for array and struct parameters. Otherwise every call copies the whole array.
- Use **Set Members in Struct** instead of break → modify → make → set, which copies the struct several times.
- Don't return big arrays from functions that are called often. Keep the data in a variable and read it by reference.

### 2.6 Graph structure

- **Functions** compile once. **Macros** are pasted inline wherever they're used, so large macros bloat graphs. Use functions for reusable logic.
- **Local variables** in functions are cheaper and safer than temporary member variables.
- **Early-outs:** put the cheapest check first (a *Branch* on a bool before a trace or search).
- **Interfaces and Event Dispatchers** instead of cast chains. Casts are cheap at runtime, but casting to *Blueprint* classes creates **hard references** that load whole asset trees (see `Common_Bugs_Guide.md` section 5.2). Casting to a **C++ base class** is free of that load.
- **Sequence** nodes don't run things in parallel. They're sequential, the same as chaining.

### 2.7 Memory and load-time cost of Blueprints

- Check each important Blueprint with the **Size Map** and **Reference Viewer**. A character Blueprint that references every weapon, VFX and sound loads all of them.
- Store references to heavy content as **soft references** and load them async when needed.
- Store static game data (items, stats, tuning) in **Data Assets / Data Tables**, not in Blueprint default values spread over many classes.

### 2.8 Animation and UI Blueprints

- **Anim Blueprints:** use *Blueprint Thread Safe Update Animation* + **Property Access**, keep the Event Graph empty, and turn on *Warn About Blueprint Usage* to keep the fast path (`120FPS_Guide.md` section 19.4).
- **UMG:** **no property bindings** (they run every frame). Update widgets from events. Use Invalidation Boxes and Slate global invalidation (`120FPS_Guide.md` section 12.1).

---

## 3. When and how to move Blueprint logic to C++

### 3.1 Move it when the profiler shows one of these

- A Blueprint function or event is **> 0.1 ms per frame** in Insights.
- Logic runs **every frame on many instances** (projectiles, AI, pickups).
- **Loops** over more than ~100 elements per frame, or nested loops.
- **Math-heavy** code (steering, procedural generation, grid or pathfinding helpers).
- Anything that should run on **worker threads** (Blueprint can't).

Keep **high-level, one-off, designer-tuned logic** in Blueprint (quest flow, level scripting, UI flow, ability sequencing). The VM overhead doesn't matter there, and iteration speed does.

### 3.2 The hybrid pattern: C++ base, Blueprint on top

```cpp
UCLASS(Abstract, Blueprintable)
class MYGAME_API AProjectileBase : public AActor
{
    GENERATED_BODY()
public:
    // Hot path in C++: movement, hit tests, pooling.
    virtual void Tick(float DeltaSeconds) override;

    // Designers react to events in Blueprint. Called rarely, so VM cost doesn't matter.
    UFUNCTION(BlueprintImplementableEvent, Category="Projectile")
    void OnImpact(const FHitResult& Hit);

    // C++ default behavior that Blueprints can override if needed.
    UFUNCTION(BlueprintNativeEvent, Category="Projectile")
    float ComputeDamage(AActor* Target) const;

    // Tuning stays visible and editable in Blueprint/Data Assets.
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Projectile", meta=(ClampMin="0"))
    float Speed = 5000.f;
};
```

### 3.3 Designing C++ functions for Blueprint callers

- **Batch APIs:** expose `FindTargetsInRadius(Origin, Radius, OutTargets)` rather than making Blueprint loop over actors and call `IsTargetValid` 500 times. Each call from Blueprint into C++ costs one VM step, so reduce the number of crossings, not the work inside.
- **Heavy getters are `BlueprintCallable`, not `BlueprintPure`**, because pure functions re-run for every connected pin (section 2.3).
- Take structs and arrays as `const T&` inputs. Use `UPARAM(ref)` for in/out parameters, to avoid copies.
- Return small results. Keep large data in a property that Blueprint reads by reference.

---

## 4. C++ optimization

### 4.1 Containers (`TArray`, `TMap`, `TSet`)

```cpp
// Reserve when you know the size: one allocation instead of many regrowths.
TArray<FHitResult> Hits;
Hits.Reserve(ExpectedCount);

// Emplace constructs in place (no temporary copy).
Names.Emplace(TEXT("Sword"));

// Reset() keeps the memory for reuse next frame. Empty() frees it.
ScratchArray.Reset();

// Order doesn't matter? RemoveAtSwap is O(1), RemoveAt shifts every later element.
Enemies.RemoveAtSwap(Index);

// Small, short-lived arrays: stack storage, no heap allocation up to N elements.
TArray<AActor*, TInlineAllocator<16>> NearbyActors;

// Iterate by reference. Copying each FStruct is a hidden cost.
for (const FInventoryItem& Item : Items) { /* ... */ }
```

| Need | Use |
|---|---|
| Lookup by key / "contains?" on large collections | `TMap` / `TSet` (O(1)), not `TArray::Find` (O(n)) |
| Keep order, iterate a lot | `TArray` (contiguous, cache-friendly) |
| Sorted data with binary search | `TArray` + `Algo::BinarySearch` / `Algo::LowerBound` |
| Fixed small max size | `TInlineAllocator<N>` or `TFixedAllocator<N>` |
| Per-frame temporary memory | Member scratch arrays with `Reset()`, or `TMemStackAllocator` / `FMemMark` |

### 4.2 Strings and names

- **`FName`** for identifiers, tags, socket and bone names, and map keys. Comparing two FNames is an integer compare with no allocation. Create `static const FName` for constants instead of constructing names every call:
  ```cpp
  static const FName MuzzleSocket(TEXT("Muzzle"));
  ```
- **`FString`** allocates. Keep it out of per-frame code. Pass it as `const FString&`, and avoid `FString::Printf` and concatenation in hot paths.
- **`FText`** is for player-facing text only. It's the most expensive of the three.
- **Logging:** `UE_LOG` still formats its string when the category is enabled. Use `Verbose` / `VeryVerbose` for spammy logs, and don't log in per-frame code in Shipping-like builds. (`UE_LOG` is compiled out in Shipping by default, but it isn't in Development or Test.)

### 4.3 Passing and returning data

- Pass structs and containers by `const T&`. Pass small types (`int32`, `float`, `FVector`, pointers) by value.
- Return by value: the compiler elides the copy (RVO). Use `MoveTemp(X)` when handing over an object you no longer need.
- Mark cheap accessors `const` and `FORCEINLINE` in headers only when a profile shows call overhead. Heavy inlining bloats code.

### 4.4 Engine calls that are more expensive than they look

| Call | Cost | Instead |
|---|---|---|
| `UGameplayStatics::GetAllActorsOfClass`, `TActorIterator` | Iterates the world's actors | A registry subsystem (section 7.1) |
| `FindComponentByClass` / `GetComponents` each frame | Searches the component array | Cache in `BeginPlay` / `PostInitializeComponents` |
| `LoadObject` / `StaticLoadObject` / synchronous `TSoftObjectPtr::LoadSynchronous` at runtime | Blocks the game thread (hitch) | Async load (`FStreamableManager::RequestAsyncLoad`) ahead of time |
| `SpawnActor` / `Destroy` | Construction, registration, GC | Pooling |
| `SetActorLocation` with sweep, many times per frame | Physics sweep + overlap update | One sweep per frame per mover, or teleport when collision isn't needed |
| `GetWorld()->LineTrace…` in loops | Physics query each | Async traces, time-slicing (`120FPS_Guide.md` section 21.5) |
| `Cast<>` | **Cheap** (class hierarchy check) | Fine to use; don't "optimize" it away |
| `IsValid()` | **Cheap** | Always use it (correctness first) |

### 4.5 Tick in C++

```cpp
AMyActor::AMyActor()
{
    PrimaryActorTick.bCanEverTick = true;          // false if the class never needs Tick
    PrimaryActorTick.bStartWithTickEnabled = false; // enable only when active
    PrimaryActorTick.TickInterval = 0.1f;          // 10 Hz is enough for most gameplay checks
    PrimaryActorTick.TickGroup = TG_PrePhysics;    // pick the right group; use prerequisites for ordering
}
```

- `SetActorTickEnabled(false)` or `SetComponentTickEnabled(false)` whenever the object goes idle.
- **Batch many similar objects** in one `UTickableWorldSubsystem` that loops over a tight array. It's much cheaper than hundreds of individual tick functions (section 7.2).
- Use `AddTickPrerequisiteActor` / `AddTickPrerequisiteComponent` for ordering, instead of doing work a frame late and patching over it.

### 4.6 Data layout and memory access

- The CPU is fastest on **contiguous memory**. `TArray<FMyStruct>` beats `TArray<UMyObject*>`, because following pointers to scattered UObjects causes cache misses.
- **Plain data → `USTRUCT`, not `UObject`.** Structs have no GC cost, no per-object header, and can live in arrays. Use UObjects only when you need reflection lifetime, instancing or Blueprint subclasses.
- **Structure of Arrays (SoA)** for large simulations: store `Positions[]`, `Velocities[]` and `Health[]` in separate arrays when a pass touches only one or two fields. This is the idea behind **Mass Entity**. For thousands of agents, use Mass instead of rolling your own (`120FPS_Guide.md` section 18).
- Keep **hot fields together** at the start of a struct and cold data (debug names, rarely used config) elsewhere.

### 4.7 Math

- Compare distances with **squared** values: `FVector::DistSquared(A, B) < Radius * Radius` avoids a `sqrt`.
- Normalize once, and reuse `GetSafeNormal()` results.
- Hoist constant work out of loops: trig on fixed angles, divisions by constants (multiply by the precomputed reciprocal), matrix/transform builds.
- Use `FMath` helpers (`FMath::InvSqrt`, `FMath::Clamp`, `FMath::IsNearlyZero`). They map to fast, platform-tuned code.
- Vectorized math (`VectorRegister`, `VectorLoad`, ...) only for proven hot loops, after profiling.

### 4.8 Delegates and events

- **Native delegates** (`DECLARE_DELEGATE`, `DECLARE_MULTICAST_DELEGATE`) are cheaper than **dynamic delegates** (`DECLARE_DYNAMIC_MULTICAST_DELEGATE`), which go through reflection. Use dynamic delegates only when Blueprint needs to bind to them.
- Broadcasting a multicast delegate with many listeners every frame adds up. Broadcast on change, not per tick.

### 4.9 Memory allocation in hot paths

- **No `new` / `NewObject` / `MakeShared` in per-frame code.** Pre-allocate and reuse (scratch arrays, pools).
- Reuse `FHitResult` arrays and query params across calls instead of constructing them every call.
- Watch **`stat memory`** and Insights' memory trace (`-trace=memory`) for allocation spikes.

---

## 5. Multithreading

The game thread is usually the 120 fps bottleneck. Moving **pure computation** to workers is the biggest win C++ offers over Blueprint.

### 5.1 The rule

**Don't touch UObjects, actors, components or the world from worker threads.** Copy the input data into plain structs on the game thread, compute on workers, and apply the results back on the game thread.

### 5.2 ParallelFor for data-parallel loops

```cpp
#include "Async/ParallelFor.h"

// Game thread: gather plain data.
TArray<FAgentData> Agents = GatherAgentData();          // positions, velocities, targets (no UObjects)
TArray<FVector> NewVelocities;
NewVelocities.SetNumUninitialized(Agents.Num());

// Workers: independent per-element work.
ParallelFor(Agents.Num(), [&](int32 Index)
{
    NewVelocities[Index] = ComputeSteering(Agents[Index]);  // pure function, no shared writes
});

// Game thread: apply.
ApplyVelocities(NewVelocities);
```

- It's only worth it when the total work is at least ~0.1 ms. For tiny loops, the threading overhead is bigger than the gain.
- Each index writes only its own output slot. No shared mutable state, and no locks inside the loop.

### 5.3 Background tasks (UE::Tasks)

```cpp
#include "Tasks/Task.h"

TWeakObjectPtr<UMyMapGenerator> WeakThis = this;
UE::Tasks::Launch(UE_SOURCE_LOCATION, [WeakThis, Seed = Seed, Params = Params]()
{
    FGridResult Result = GenerateGrid(Seed, Params);        // heavy, pure computation

    AsyncTask(ENamedThreads::GameThread, [WeakThis, Result = MoveTemp(Result)]() mutable
    {
        if (UMyMapGenerator* Self = WeakThis.Get())          // object may be gone
        {
            Self->ApplyGrid(MoveTemp(Result));               // UObject work back on game thread
        }
    });
});
```

- Good candidates: procedural generation, pathfinding over custom grids, save-game serialization, AI utility scoring, big sorts, and parsing.
- For long-running services (a network socket, a streaming worker), use `FRunnable`.

---

## 6. Networking code

- **Push model:** mark properties dirty only when they change (`MARK_PROPERTY_DIRTY_FROM_NAME`), so the server doesn't compare every replicated property every frame. With `bIsPushBased = true` in `FDoRepLifetimeParams`.
- **Replication conditions:** `COND_OwnerOnly`, `COND_SkipOwner`, `COND_InitialOnly` to send only what each client needs.
- **Quantized types:** `FVector_NetQuantize` / `FVector_NetQuantize10` for positions and directions (fewer bits).
- Lower `NetUpdateFrequency` for slow-changing actors. Use dormancy for static ones (`120FPS_Guide.md` section 18.4).
- **Fewer RPCs:** send state changes (replicated properties) instead of per-frame RPCs, and batch several events into one RPC.

---

## 7. Before / after patterns

### 7.1 Replace "Get All Actors of Class" with a registry

```cpp
// EnemyRegistrySubsystem.h
UCLASS()
class MYGAME_API UEnemyRegistrySubsystem : public UWorldSubsystem
{
    GENERATED_BODY()
public:
    void Register(AEnemy* Enemy)   { Enemies.AddUnique(Enemy); }
    void Unregister(AEnemy* Enemy) { Enemies.RemoveSwap(Enemy); }

    // C++ callers: no copy.
    const TArray<TObjectPtr<AEnemy>>& GetEnemiesRef() const { return Enemies; }

    // Blueprint callers get a copy of the pointer list (cheap: pointers only).
    UFUNCTION(BlueprintCallable, Category="Enemies")
    TArray<AEnemy*> GetEnemies() const
    {
        TArray<AEnemy*> Out;
        Out.Reserve(Enemies.Num());
        for (AEnemy* Enemy : Enemies) { Out.Add(Enemy); }
        return Out;
    }

private:
    UPROPERTY()
    TArray<TObjectPtr<AEnemy>> Enemies;
};

// AEnemy::BeginPlay -> GetWorld()->GetSubsystem<UEnemyRegistrySubsystem>()->Register(this);
// AEnemy::EndPlay   -> ...->Unregister(this);
```

**Before:** every AI calls *Get All Actors of Class (Enemy)* every tick, which scans the whole world.
**After:** a list lookup that's always ready.

### 7.2 Replace 500 ticking actors with one manager

**Before:** 500 pickups, each with `Tick` doing a bob animation and a distance check.

**After:** pickups register with a `UTickableWorldSubsystem`. The subsystem:
1. Updates the bob offset for all of them in one loop, over a `TArray<FPickupData>`.
2. Runs the distance check every 0.2 s against squared distances.
3. Enables a pickup's own logic only when the player is near.

Typically 5–10× cheaper, and all of it shows up as one entry in Insights.

### 7.3 Blueprint loop with a pure search

**Before:** *For Each Loop* whose array input is wired straight from *Get All Actors with Tag*, so the search runs on every iteration.
**After:** call the search once, store the result in a local variable, loop over the local (section 2.3). Better still, use the registry from 7.1.

### 7.4 Distance checks

```cpp
// Before
if (FVector::Dist(A, B) < 1000.f)
// After: no sqrt
if (FVector::DistSquared(A, B) < FMath::Square(1000.f))
```

---

## 8. Build configuration

- **Always profile Test or Shipping-like builds.** Development builds keep checks, stats and logging.
- **Debugging optimized code:** wrap a function in `UE_DISABLE_OPTIMIZATION` / `UE_ENABLE_OPTIMIZATION` (older engines: `PRAGMA_DISABLE_OPTIMIZATION`) to debug it. **Never commit** those macros. A forgotten one silently slows that code in every build.
- **Shipping target settings** (`MyGame.Target.cs`):
  ```csharp
  if (Configuration == UnrealTargetConfiguration.Shipping)
  {
      bAllowLTCG = true;            // link-time code generation: cross-module inlining
      bUseLoggingInShipping = false;
  }
  ```
  LTCG makes linking slower, so use it only for Shipping.
- `check()` / `checkSlow()` are compiled out in Shipping, but `ensure()` and `verify()` expressions still run. Don't put expensive expressions inside them.
- Keep **unity builds** on (the default) for build speed. Occasionally build with them off in CI (`bUseUnityBuild = false`) to catch missing includes.

---

## 9. Checklist and budgets

**Blueprint**
- [ ] Tick off by default. Timers and events instead of polling.
- [ ] No *Get All Actors of Class* / *Get Component by Class* in Tick or loops. Results cached or taken from a registry.
- [ ] Pure node results cached before loops.
- [ ] Arrays and structs passed by reference. *Get (a ref)* for in-place edits.
- [ ] No per-frame string building, no Print String in gameplay paths.
- [ ] Anim BPs thread-safe, no UMG property bindings.
- [ ] Size Map checked: no hard references to heavy unrelated content.

**C++**
- [ ] Hot functions have `TRACE_CPUPROFILER_EVENT_SCOPE`.
- [ ] No allocations in per-frame code (`Reserve`, `Reset`, inline allocators, pooling).
- [ ] `TMap` / `TSet` for lookups, iteration by `const&`, `RemoveAtSwap` where order doesn't matter.
- [ ] `FName` / `static const FName` for identifiers. No `FString` work per frame.
- [ ] Components and actors cached, not searched per frame.
- [ ] Ticks disabled or batched, with a sensible `TickInterval`.
- [ ] Heavy pure computation on workers (`ParallelFor`, `UE::Tasks`), UObjects touched only on the game thread.
- [ ] No leftover `UE_DISABLE_OPTIMIZATION`.

**Budgets (Tier B, 120 fps)**
- [ ] Gameplay tick + Blueprint time ≤ 2.0 ms
- [ ] Each owned system ≤ 0.5 ms
- [ ] No single event > 1 ms
- [ ] ≤ 300 ticking objects

---

## 10. Sources

- [Epic – Coding in Unreal Engine: Blueprint vs. C++](https://dev.epicgames.com/documentation/unreal-engine/coding-in-unreal-engine-blueprint-vs-cplusplus?lang=en-US)
- [Epic – Developer Guide to Tracing](https://dev.epicgames.com/documentation/en-us/unreal-engine/developer-guide-to-tracing-in-unreal-engine)
- [Epic – TArray: Arrays in Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine/array-containers-in-unreal-engine)
- [Epic blog – Optimizing TArray Usage for Performance](https://www.unrealengine.com/en-US/blog/optimizing-tarray-usage-for-performance)
- [Tom Looman – Unreal Engine C++ Complete Guide](https://tomlooman.com/unreal-engine-cpp-guide/)
- [Tom Looman – Game Optimization on a Budget](https://tomlooman.com/unreal-engine-optimization-talk/)
- [Coconut Lizard – Strings and Other Things](https://www.coconutlizard.co.uk/blog/strings-and-other-things/)
- [rick.me.uk – C++ Profiling in Unreal Engine 5](https://www.rick.me.uk/posts/2024/12/cpp-profiling-in-unreal-engine-5/)
- [Unrealcode.net – Mass: Cache Concepts and Optimization](https://www.unrealcode.net/MASS_001.html)
- [UhiyamaLab – Blueprint Performance Optimization and Criteria for C++ Migration](https://uhiyama-lab.com/en/notes/ue/blueprint-performance-optimization-nativize/)
- [SpongeHammer – UE5 Blueprint vs C++ performance](https://www.spongehammer.com/unreal-engine-5-blueprint-vs-cpp-performance/)
