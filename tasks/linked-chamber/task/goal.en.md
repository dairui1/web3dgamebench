# Linked Chamber

## Objective

Build a complete, polished, browser-native 3D first-person spatial puzzle called **Linked Chamber** with Three.js. Its shared gameplay reference is the familiar paired-portal traversal, redirected momentum, cube, floor switch, and exit-door puzzle loop of **Portal 2**. Use original names, room geometry, device design, materials, sounds, writing, and interface assets.

Create one authored test chamber containing a start platform, a lower pit, at least four marked portal-compatible wall surfaces spanning at least two different surface normals, one carryable energy cube, one weighted floor switch, and a locked exit. The intentional solution must make the player traverse the linked pair, redirect momentum between differently oriented portals, pass the cube through a portal, keep the switch pressed with that cube, and reach the exit.

## Operational completion contract

Implement the game described below. The Goal is complete when `npm run build` succeeds and emits `dist/`.

Do not write or run browser automation, automated runtime checks, autopilots, or full playthroughs. Runtime behavior, responsiveness, feature completeness, balance, polish, and game feel are evaluated after submission. Report only the build you actually ran.

## Target game systems

- First-person movement, collision, gravity, jump, pointer-lock look, touch-look, and safe respawn after falling out of the chamber.
- Two distinct portal controls that place blue and amber portals only on marked compatible surfaces, reject invalid hits, and replace the previous portal of the same color.
- Each placed portal must show a camera-correct render-target view through its paired portal that updates as the player camera moves. One non-recursive render layer is sufficient; a static image, opaque color, or unrelated secondary-camera view is not.
- Player and cube can cross a linked portal in both directions. Position, facing, and momentum are transformed consistently; a cooldown or directional crossing test prevents oscillation.
- One cube that can be picked up, carried visibly, released, dropped, passed through portals, and placed on the weighted switch.
- A switch that responds to cube weight, visibly powers the door, and releases if the cube is removed. The exit wins only while open.
- Crosshair, portal validity feedback, portal status, interaction prompt, switch-to-door connection, objective, victory, failure/recovery, and restart UI.
- Desktop keyboard and pointer controls plus usable phone move/look, jump, interact, blue portal, and amber portal controls.
- Minimum input convention: forward movement must respond to either W or Up Arrow on desktop, and the primary phone movement surface must occupy the lower-left control region.

## Execution checkpoints

1. Establish the chamber, player controller, collision, gravity, camera, fall recovery, and responsive input.
2. Implement valid portal placement, paired rendering, portal transforms, and robust player traversal.
3. Implement cube carrying and traversal, switch, powered door, authored solution, victory, and restart.
4. Improve spatial cues, materials, lighting, portal edges, connection feedback, interaction animation, and UI clarity.
5. After the final relevant change, run `npm run build` once. If it succeeds and emits `dist/`, stop; post-submission evaluation handles runtime behavior.

## Quality targets

- Portal views correspond to the paired location and do not remain stale after camera movement.
- Traversal does not trap the player inside geometry, reverse controls unexpectedly, or cause immediate ping-pong teleportation.
- Invalid surfaces are unambiguously different from valid portal surfaces.
- The cube remains reachable after reasonable mistakes, or the chamber offers an explicit reset.
- Touch controls can place both portals and manipulate the cube without UI overlap.

- At 1440 x 900 and 390 x 844, horizontal page overflow stays within 2 CSS pixels and the runtime emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `bluePortalPlaced`: boolean;
- `amberPortalPlaced`: boolean;
- `portalTraversals`: non-negative integer;
- `cubePortalTraversals`: non-negative integer;
- `cubeHeld`: boolean;
- `cubeOnSwitch`: boolean;
- `doorOpen`: boolean;
- `seed`: `64891`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report only the production build result; do not create additional automated verification.
