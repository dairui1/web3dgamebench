# Linked Chamber

## Objective

Build a complete, polished, browser-native 3D first-person spatial puzzle called **Linked Chamber** with Three.js. Its shared gameplay reference is the familiar paired-portal traversal, redirected momentum, cube, floor switch, and exit-door puzzle loop of **Portal 2**. Use original names, room geometry, device design, materials, sounds, writing, and interface assets.

Create one authored test chamber containing a start platform, a lower pit, at least four marked portal-compatible wall surfaces, one carryable energy cube, one weighted floor switch, and a locked exit. The player must place a blue and an amber portal, travel through the linked pair, retrieve and transport the cube, keep the switch pressed, and reach the exit.

## Completion contract

Complete the goal only when all of the following are true:

- Portal placement, paired views, player traversal, cube traversal, carrying, switch behavior, door state, falling recovery, victory, and restart all function.
- The chamber has one intentional solution that requires portals and the cube; walking directly to the exit cannot solve it.
- Portal transforms preserve a sensible exit orientation and momentum without repeated re-entry loops.
- The production build succeeds and the complete puzzle has been solved at both required viewports.

Do not stop after drawing portal-colored rectangles. Continue until linked space, traversal, object interaction, and the puzzle solution work together.

## Required game systems

- First-person movement, collision, gravity, jump, pointer-lock look, touch-look, and safe respawn after falling out of the chamber.
- Two distinct portal controls that place blue and amber portals only on marked compatible surfaces, reject invalid hits, and replace the previous portal of the same color.
- Each placed portal must show a live or convincingly updated view through its paired portal rather than an opaque flat color.
- Player and cube can cross a linked portal in both directions. Position, facing, and momentum are transformed consistently; a cooldown or directional crossing test prevents oscillation.
- One cube that can be picked up, carried visibly, released, dropped, passed through portals, and placed on the weighted switch.
- A switch that responds to cube weight, visibly powers the door, and releases if the cube is removed. The exit wins only while open.
- Crosshair, portal validity feedback, portal status, interaction prompt, switch-to-door connection, objective, victory, failure/recovery, and restart UI.
- Desktop keyboard and pointer controls plus usable phone move/look, jump, interact, blue portal, and amber portal controls.

## Execution checkpoints

1. Establish the chamber, player controller, collision, gravity, camera, fall recovery, and responsive input.
2. Implement valid portal placement, paired rendering, portal transforms, and robust player traversal.
3. Implement cube carrying and traversal, switch, powered door, authored solution, victory, and restart.
4. Improve spatial cues, materials, lighting, portal edges, connection feedback, interaction animation, and UI clarity.
5. Build and solve the full chamber at 1440 x 900 and 390 x 844; test invalid placement, repeated crossing, cube drops, resize, and recovery.

## Quality gates

- Portal views correspond to the paired location and do not remain stale after camera movement.
- Traversal does not trap the player inside geometry, reverse controls unexpectedly, or cause immediate ping-pong teleportation.
- Invalid surfaces are unambiguously different from valid portal surfaces.
- The cube remains reachable after reasonable mistakes, or the chamber offers an explicit reset.
- Touch controls can place both portals and manipulate the cube without UI overlap.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `bluePortalPlaced`: boolean;
- `amberPortalPlaced`: boolean;
- `portalTraversals`: non-negative integer;
- `cubeHeld`: boolean;
- `cubeOnSwitch`: boolean;
- `doorOpen`: boolean;
- `seed`: `64891`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result and an end-to-end puzzle solve at desktop and phone sizes honestly.
