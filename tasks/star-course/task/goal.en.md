# Star Course

## Objective

Build a complete, polished, browser-native 3D platform game called **Star Course** with Three.js. Its shared gameplay reference is the familiar free-running, analog-feeling movement, follow camera, coins, enemies, moving platforms, recovery, and goal-star structure of **Super Mario 64**. Use original names, character design, level geometry, enemies, collectibles, sounds, textures, and interface assets.

Create one compact course with three connected sections: a grassy opening, a moving-platform ravine, and a small summit tower. The player must collect at least eight of twelve coins, cross the course, defeat or avoid two enemies, reach the summit, and collect the goal star. Falling costs one of three lives and respawns at the latest checkpoint; losing all lives fails the run.

## Completion contract

Complete the goal only when all of the following are true:

- Movement, camera, jump behavior, platforms, coins, enemies, checkpoints, lives, goal unlock, victory, failure, and restart all function.
- The course is intentionally laid out and can be read as a route through three distinct spatial sections.
- Movement has controllable acceleration, air steering, reliable landing, and feedback appropriate for a character platformer.
- The production build succeeds and the course has been completed at both required viewports.

Do not stop after making a character jump between boxes. Continue until route design, movement feel, camera behavior, hazards, and progression form a complete course.

## Required game systems

- Third-person movement with acceleration and deceleration, facing, slope handling, gravity, grounded checks, air control, variable jump height, and a forgiving coyote or jump-buffer window.
- An orbiting follow camera with collision or obstruction handling, manual adjustment, and automatic recentering that does not fight the player.
- Twelve placed coins with pickup feedback, score, and persistence during a life. The summit star remains unavailable until at least eight coins are collected.
- At least three moving platforms with predictable paths, correct player carrying, and no tunneling or instant crushing.
- Two patrolling enemies with readable contact danger and a stomp or equivalent skill-based defeat interaction.
- One nonlethal environmental hazard, one bottomless-fall region, three lives, and at least two checkpoints including the start.
- Current coins, lives, checkpoint feedback, star requirement, objective, victory, failure, and restart UI.
- Desktop keyboard/pointer controls plus usable phone movement, camera, jump, and optional action controls.

## Execution checkpoints

1. Establish the character controller, collision, camera, responsive input, and a greybox route through all three sections.
2. Implement coins, enemies, hazards, lives, fall recovery, checkpoints, moving platforms, and goal requirements.
3. Tune movement, camera, platform timing, enemy fairness, complete state flow, and restart behavior.
4. Replace the greybox feel with authored geometry, landmarks, materials, lighting, particles, and clear feedback.
5. Build and complete the course at 1440 x 900 and 390 x 844; test every checkpoint, all moving platforms, life loss, resize, and victory.

## Quality gates

- Jumps are predictable and the camera keeps intended landing areas visible.
- Moving platforms carry the player without visible sliding caused by missing parent-relative motion.
- Falling or taking damage cannot trap the player in repeated immediate deaths.
- Coin and star requirements are clear, and victory cannot occur with fewer than eight coins.
- Touch controls remain stable and leave enough screen area to judge platform depth.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `coinsCollected`: integer from 0 to 12;
- `coinsTotal`: `12`;
- `lives`: integer from 0 to 3;
- `checkpoint`: non-negative integer;
- `enemiesDefeated`: integer from 0 to 2;
- `starUnlocked`: boolean;
- `seed`: `73693`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result and a full course completion at desktop and phone sizes honestly.
