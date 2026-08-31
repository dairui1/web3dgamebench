# First Night

## Objective

Build a complete, polished, browser-native 3D voxel survival game called **First Night** with Three.js. Its shared gameplay reference is the familiar exploration, block breaking and placement, crafting, shelter building, and day-to-night survival loop of **Minecraft**. Use original names, world generation, geometry, textures, sounds, creatures, recipes, and interface assets.

Generate a deterministic compact voxel island. The player must gather at least three wood and three stone, craft a signal beacon, build a small enclosed shelter, place the beacon on its roof, and remain alive until dawn. Night introduces two hostile creatures. Victory requires both a placed beacon and survival through the night; death from damage or falling ends the run.

## Completion contract

Complete the goal only when all of the following are true:

- The player can explore, select blocks, break and collect them, place blocks, manage a hotbar, craft the beacon, build, survive combat, and reach dawn.
- The seeded world is a coherent navigable place with terrain, resources, landmarks, boundaries, and changing light.
- Ready, playing, paused, won, lost, and restart states work without corrupting inventory or terrain.
- The production build succeeds and a full gather-to-dawn run has been played at both required viewports.

Do not stop after rendering a voxel landscape. Continue until the world supports the complete survival and construction objective.

## Required game systems

- A deterministic voxel island at least 24 x 24 blocks in footprint with height variation, soil, stone, trees, crystal deposits, and a visible safe spawn area.
- First-person or close third-person movement with gravity, jumping, terrain collision, grounded checks, and safe recovery from nonlethal falls.
- Raycast block targeting with visible selection, timed breaking, resource drops, inventory counts, placement on valid neighboring faces, and prevention of placing inside the player.
- A hotbar containing collected block types, a beacon recipe that consumes exactly three wood and three stone, and a clear crafting interaction.
- A day-dusk-night-dawn cycle with readable sky and lighting changes. Night spawns exactly two hostile creatures that pursue and damage the player but cannot attack through walls.
- A basic player attack, health, damage feedback, resource counts, selected slot, objective checklist, time-of-day indicator, and restart flow.
- Desktop keyboard and mouse controls plus usable phone move/look, jump, break, place, attack, slot, and craft controls.
- Minimum input convention: forward movement must respond to either W or Up Arrow on desktop, and the primary phone movement surface must occupy the lower-left control region.

## Execution checkpoints

1. Establish deterministic voxel generation, meshing, movement, gravity, collision, camera, and responsive input.
2. Implement targeting, breaking, drops, inventory, hotbar, placement rules, and the beacon recipe.
3. Implement the day-night timeline, hostile creatures, combat, shelter-relevant collision, win/loss logic, and restart.
4. Improve terrain composition, materials, sky, lighting, particles, interaction feedback, and HUD clarity.
5. Build and play a complete gather, craft, build, defend, and dawn sequence at 1440 x 900 and 390 x 844.

## Quality gates

- The player always knows which block is targeted, what was collected, what is selected, and what remains for the objective.
- Breaking and placement modify the world consistently and do not create invisible collision leftovers.
- Creatures navigate well enough to threaten an exposed player but walls provide meaningful protection.
- The beacon cannot be placed before it is crafted; dawn alone cannot trigger victory. A valid shelter must contain at least two horizontally adjacent standable interior cells, each with two air blocks of headroom, enclosed from the outside at body height by solid player-placed walls and covered by player-placed roof blocks. The beacon must be supported directly by that roof. A block-count threshold without this spatial enclosure is not valid.
- Restart restores the original seeded terrain, inventory, beacon, shelter, creatures, health, and time-of-day state.
- Touch controls permit the full objective without requiring hover, right-click, or a physical keyboard.

- At both evaluated viewports, horizontal page overflow stays within 2 CSS pixels and the tested flow emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `health`: finite number from 0 to 100;
- `timeOfDay`: finite number from 0 to 1;
- `inventory`: `{ wood, stone, crystal }` with non-negative integers;
- `selectedSlot`: non-negative integer;
- `blocksBroken`: non-negative integer;
- `blocksPlaced`: non-negative integer;
- `beaconCrafted`: boolean;
- `beaconPlaced`: boolean;
- `shelterValid`: boolean;
- `shelterCellCount`: non-negative integer counting standable interior cells that satisfy the enclosure test;
- `dawnReached`: boolean that becomes true only when the day-night cycle enters dawn;
- `hostilesAlive`: integer from 0 to 2;
- `seed`: `37199`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result and a successful full-night playtest at desktop and phone sizes honestly.
