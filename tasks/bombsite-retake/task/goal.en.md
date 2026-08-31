# Bombsite Retake

## Objective

Build a complete, polished, browser-native 3D tactical first-person shooter called **Bombsite Retake** with Three.js. Its shared gameplay reference is the familiar bomb-retake loop of **Counter-Strike 2**, but every name, map, weapon model, sound, texture, character, and interface asset must be original.

The player enters a compact industrial site as the responding operator. A device is already planted and defended by two enemy bots. Reach the site through either of two viable routes, survive the firefight, secure the area, and hold the interact control long enough to defuse before the 90-second timer expires. Killing both defenders does not replace the defuse step.

## Completion contract

Complete the goal only when all of the following are true:

- Start, tactical play, win, loss, and immediate restart form one reliable loop.
- First-person movement, aiming, firing, reload, damage, enemy behavior, planted-device timing, and hold-to-defuse interaction all work.
- The map supports meaningful cover and two approaches rather than a flat shooting gallery.
- The production build succeeds and the complete loop has been played at both required viewports.

Do not stop after producing a room with targets. Continue until the objective pressure, weapon feedback, bot readability, and responsive controls make it feel like a compact tactical round.

## Required game systems

- First-person camera, collision-aware movement, walk, sprint, crouch, jump, pointer-lock aiming, and touch-look support.
- One readable rifle with hitscan fire, magazine and reserve ammunition, reload timing, recoil or spread, muzzle feedback, impact feedback, and no firing while reloading.
- Two bots that patrol or hold different angles, detect the player by range and line of sight, take cover or reposition, fire with telegraphed accuracy, and can be defeated.
- One authored bombsite with two approach routes, occluding cover, recognizable landmarks, spawn protection from immediate fire, and no unreachable positions.
- A planted device with escalating audio or visual urgency, 90-second countdown, interaction range, interrupted hold progress, and clear defuse completion.
- Health, ammo, timer, enemies alive, defuse progress, hit direction, crosshair, current objective, victory, and failure UI.
- Desktop keyboard and mouse controls plus usable phone twin-stick controls and explicit fire, reload, crouch, and interact buttons.

## Execution checkpoints

1. Establish the map, collision, camera, movement, both routes, and desktop/phone input.
2. Implement the rifle, damage, two bots, line-of-sight behavior, cover, and fair combat.
3. Implement the planted-device timer, hold-to-defuse logic, complete state flow, HUD, and restart.
4. Improve weapon feel, spatial audio or visual cues, lighting, materials, impacts, and tactical readability.
5. Build and play complete winning and losing rounds at 1440 x 900 and 390 x 844; fix clipping, overlap, deadlocks, and input traps.

## Quality gates

- The player can identify the site, timer pressure, enemies, cover, and interaction state without guessing.
- Bots pose a threat without firing through solid geometry or using perfect unavoidable aim.
- The player cannot defuse from outside the interaction zone, while dead, or after the timer expires.
- Pointer lock has a visible recovery path; touch controls do not obscure the crosshair or critical HUD.
- Resize and page visibility changes preserve valid state and do not create phantom input.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `health`: finite number from 0 to 100;
- `ammo`: non-negative integer;
- `reserveAmmo`: non-negative integer;
- `enemiesAlive`: integer from 0 to 2;
- `bombSecondsRemaining`: non-negative finite number;
- `defuseProgress`: finite number from 0 to 1;
- `seed`: `28417`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result and both a successful-defuse and a failure-path playtest honestly.
