# Canyon Strike

## Objective

Build a complete, polished, browser-native 3D game called **Canyon Strike** with Three.js. Create an original arcade air-combat mission whose shared gameplay reference is the recognizable third-person flight, targeting, missile, and mission structure of **Ace Combat**. Do not reproduce its names, aircraft, story, maps, interface artwork, audio, or other protected assets.

The player must fly through a mountain canyon, destroy three ground emplacements and two airborne interceptors, then cross an extraction gate. The mission is won only after every target is destroyed and extraction is reached. It is lost if the aircraft is destroyed, hits terrain at lethal speed, or the mission timer expires.

## Operational completion contract

Implement the game described below. The Goal is complete when `npm run build` succeeds and emits `dist/`.

Do not write or run browser automation, automated runtime checks, autopilots, or full playthroughs. Runtime behavior, responsiveness, feature completeness, balance, polish, and game feel are evaluated after submission. Report only the build you actually ran.

## Target game systems

- Third-person chase camera with stable horizon cues and convincing speed.
- Pitch, yaw, roll, throttle, bounded acceleration, and frame-rate-independent movement.
- Rapid-fire cannon plus limited lock-on missiles. A visible lock sequence must precede a guided missile shot.
- Three distinguishable ground targets and two interceptors with readable attacks or evasive behavior.
- Terrain, canyon walls, route landmarks, target placement, and an extraction gate that form a coherent mission path.
- Health, impact feedback, weapon cooldown/ammunition, mission timer, target counter, radar or directional target cues, and current objective.
- Desktop keyboard controls and usable phone controls, such as a virtual flight stick plus weapon and throttle controls.
- Minimum input convention: banking left must respond to either Left Arrow or A on desktop, and the primary phone flight stick must occupy the lower-left control region.
- Pause on page visibility loss. Audio is optional and may start only after interaction.

## Execution checkpoints

1. Establish the canyon, aircraft controller, camera, collisions, and desktop/phone input.
2. Implement both weapons, lock-on behavior, all enemy types, health, and mission state transitions.
3. Build the complete target sequence, extraction requirement, HUD, feedback, and restart flow.
4. Improve spatial composition, lighting, effects, enemy readability, and sense of speed.
5. After the final relevant change, run `npm run build` once. If it succeeds and emits `dist/`, stop; post-submission evaluation handles runtime behavior.

## Quality targets

- The aircraft and targets are immediately legible against the environment.
- Steering is controllable, collisions are fair, and the camera does not induce avoidable confusion.
- The HUD communicates mission-critical information without covering the flight path.
- Victory requires the specified actions in order; it cannot occur through waiting or a debug shortcut.
- The page resizes without resetting the mission or breaking input.

- At 1440 x 900 and 390 x 844, horizontal page overflow stays within 2 CSS pixels and the runtime emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `health`: finite number from 0 to 100;
- `missiles`: non-negative integer;
- `targetsDestroyed`: integer from 0 to 5;
- `targetsTotal`: `5`;
- `extracted`: boolean that becomes true only after all five targets are destroyed and the aircraft crosses the extraction gate;
- `missionSecondsRemaining`: non-negative finite number;
- `seed`: `19031`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report only the production build result; do not create additional automated verification.
