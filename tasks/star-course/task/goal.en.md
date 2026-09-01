# Star Course

## Objective

Build a complete, polished, browser-native 3D platform game called **Star Course** with Three.js. Its shared gameplay reference is the familiar free-running, analog-feeling movement, follow camera, coins, enemies, moving platforms, recovery, and goal-star structure of **Super Mario 64**. Use original names, character design, level geometry, enemies, collectibles, sounds, textures, and interface assets.

Create one compact course with three connected sections: a grassy opening, a moving-platform ravine, and a small summit tower. The player must collect at least eight of twelve coins, complete a skill-based defeat interaction with at least one of two enemies, cross a required moving-platform transfer, reach the summit, and collect the goal star. Falling costs one of three lives and respawns at the latest checkpoint; losing all lives fails the run.

## Operational completion contract

The feature lists below define the intended submission and its quality criteria. They do not require exhaustive self-proof. Complete the goal when all of the following operational checks pass:

- `npm run build` succeeds and emits the static production bundle to `dist/`.
- The production build loads at 1440 x 900 and 390 x 844 with a visible, nonblank, interactive 3D scene, no horizontal overflow beyond 2 CSS pixels, and no uncaught page exception or `console.error` during the checked flow.
- One brief smoke check at each viewport confirms that the game can enter its active play state, one primary control changes observable game state, and restart returns to a valid initial state.

Keep these checks bounded. Rerun a failed check only after a relevant fix, and stop once it passes. Do not create an autopilot or repeatedly run full victories, losses, missions, matches, races, services, nights, courses, quests, fights, or puzzle solutions solely to prove completion. Those paths, feature completeness, balance, polish, and game feel are evaluated after submission; shortcomings affect the result, not whether the agent must continue self-testing. Report only the checks actually run.

## Target game systems

- Third-person movement with acceleration and deceleration, facing, slope handling, gravity, grounded checks, air control, variable jump height, and a forgiving coyote or jump-buffer window.
- An orbiting follow camera with collision or obstruction handling, manual adjustment, and automatic recentering that does not fight the player.
- Twelve placed coins with pickup feedback, score, and persistence during a life. The summit star remains unavailable until at least eight coins are collected, and no more than seven coins are reachable without completing the moving-platform ravine and the required enemy interaction.
- At least three moving platforms with predictable paths, correct player carrying, and no tunneling or instant crushing. The only route to the summit includes at least one timed transfer between moving platforms.
- Two patrolling enemies with readable contact danger and a stomp or equivalent skill-based defeat interaction. At least one such defeat is required for the star to unlock.
- One nonlethal environmental hazard, one bottomless-fall region, three lives, and at least two checkpoints including the start.
- Current coins, lives, checkpoint feedback, star requirement, objective, victory, failure, and restart UI.
- Desktop keyboard/pointer controls plus usable phone movement, camera, jump, and optional action controls.
- Minimum input convention: forward movement must respond to either W or Up Arrow on desktop, and the primary phone movement surface must occupy the lower-left control region.

## Execution checkpoints

1. Establish the character controller, collision, camera, responsive input, and a greybox route through all three sections.
2. Implement coins, enemies, hazards, lives, fall recovery, checkpoints, moving platforms, and goal requirements.
3. Tune movement, camera, platform timing, enemy fairness, complete state flow, and restart behavior.
4. Replace the greybox feel with authored geometry, landmarks, materials, lighting, particles, and clear feedback.
5. Build once after the final relevant change, then run the bounded operational smoke checks at 1440 x 900 and 390 x 844. Fix only observed build, startup, blank-frame, input, restart, exception, or layout failures before completing.

## Quality targets

- Jumps are predictable and the camera keeps intended landing areas visible.
- Moving platforms carry the player without visible sliding caused by missing parent-relative motion.
- Falling or taking damage cannot trap the player in repeated immediate deaths.
- Coin, moving-platform, enemy, and star requirements are clear; victory cannot occur with fewer than eight coins, without the required platform transfer, or without one skill-based enemy defeat.
- Touch controls remain stable and leave enough screen area to judge platform depth.

- At both evaluated viewports, horizontal page overflow stays within 2 CSS pixels and the tested flow emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `coinsCollected`: integer from 0 to 12;
- `coinsTotal`: `12`;
- `lives`: integer from 0 to 3;
- `checkpoint`: non-negative integer;
- `enemiesDefeated`: integer from 0 to 2;
- `movingPlatformTransfers`: non-negative integer counting completed transfers from one moving platform to another;
- `starUnlocked`: boolean;
- `seed`: `73693`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the production build result and the two bounded viewport smoke checks honestly. Full win/loss or end-to-end playthrough evidence is neither required nor requested.
