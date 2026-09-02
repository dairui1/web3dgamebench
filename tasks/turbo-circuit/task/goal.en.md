# Turbo Circuit

## Objective

Build a complete, polished, browser-native 3D arcade kart racing game called **Turbo Circuit** with Three.js. Its shared gameplay reference is the familiar colorful circuit, drift-to-boost, item pickup, rival racers, lap, rank, and finish structure of **Mario Kart**. Use original names, characters, karts, track, item designs, sounds, textures, and interface assets.

Create one closed circuit with three laps, three AI rivals, at least eight checkpoints, two shortcuts or alternate lines, off-road slowdown, boost pads, and item gates. The player must finish the race; final rank determines the result, with first place treated as victory and lower ranks as a completed loss that can be restarted immediately.

## Operational completion contract

Implement the game described below. The Goal is complete when `npm run build` succeeds and emits `dist/`.

Do not write or run browser automation, automated runtime checks, autopilots, or full playthroughs. Runtime behavior, responsiveness, feature completeness, balance, polish, and game feel are evaluated after submission. Report only the build you actually ran.

## Target game systems

- Chase-camera kart handling with acceleration, top speed, braking/reverse, steering that scales sensibly with speed, lateral grip, collision response, and frame-rate-independent physics.
- A hold-and-release drift with visible charge stages and a short boost whose strength reflects successful drift duration.
- One continuous three-lap track with at least eight ordered checkpoints, wrong-way detection, lap validation, guardrails or recovery, off-road slowdown, and two deliberate alternate lines or shortcuts.
- Three visually distinct AI racers using the same track progression, with speed variation, obstacle recovery, basic avoidance, and no teleporting except explicit stuck recovery.
- Item gates deterministically expose both held item types during a full race: a forward speed burst and a dropped slow-field hazard. The HUD shows the held item and a clear use control; a high-quality completed run should support using each type at least once.
- At least two boost pads, collision and overtake feedback, live rank, lap, checkpoint direction, speed, drift charge, item, race timer, countdown, finish result, and restart UI.
- Desktop keyboard controls plus usable phone steering, accelerator, brake, drift, and item controls.
- Minimum input convention: acceleration must respond to either W or Up Arrow on desktop, and the phone accelerator must be a visible hold control in the lower-right control region.

## Execution checkpoints

1. Establish track, kart controller, chase camera, collisions, checkpoints, lap logic, responsive input, and road recovery.
2. Implement drift charge and boost, off-road behavior, boost pads, items, and clear driving feedback.
3. Implement three AI racers, ranking, countdown, finish order, victory/loss, and restart.
4. Improve track landmarks, geometry, lighting, materials, particles, vehicle animation, speed feedback, and HUD readability.
5. After the final relevant change, run `npm run build` once. If it succeeds and emits `dist/`, stop; post-submission evaluation handles runtime behavior.

## Quality targets

- Lap progress cannot advance by reversing across one checkpoint or skipping the ordered route.
- Drifting changes handling and produces an earned boost rather than acting as an always-on speed button.
- AI racers neither remain permanently stuck nor ignore the course rules.
- A player who remains idle or completes the race without earning a drift boost must lose to at least one rival; AI pace cannot be a stationary or deliberately trivial win condition.
- Track direction and upcoming corners remain readable at racing speed.
- Touch controls remain fixed, reachable, and do not cover rank, lap, or the near road.

- At 1440 x 900 and 390 x 844, horizontal page overflow stays within 2 CSS pixels and the runtime emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `countdown`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `lap`: integer from 1 to 3;
- `checkpoint`: non-negative integer;
- `rank`: integer from 1 to 4;
- `speed`: non-negative finite number;
- `driftCharge`: finite number from 0 to 1;
- `driftBoostsEarned`: non-negative integer;
- `heldItem`: `boost`, `slow-field`, or `null`;
- `boostItemsUsed`: non-negative integer;
- `slowFieldsUsed`: non-negative integer;
- `finishCrossed`: boolean that becomes true only after the player crosses the validated final-lap finish line;
- `raceSeconds`: non-negative finite number;
- `seed`: `82939`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report only the production build result; do not create additional automated verification.
