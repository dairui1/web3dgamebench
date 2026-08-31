# Ashen Duel

## Objective

Build a complete, polished, browser-native 3D third-person boss-combat game called **Ashen Duel** with Three.js. Its shared gameplay reference is the familiar lock-on, stamina management, dodge timing, healing, attack commitment, and readable boss-pattern loop of **Elden Ring**. Use original names, characters, arena, attacks, animation, effects, sounds, icons, and interface assets.

The player enters a ruined circular arena and fights one guardian boss. The boss has two phases and at least four distinct telegraphed attacks across the fight. The player wins by reducing the boss to zero health and loses by dying. There are no additional levels, menus, or progression systems to hide an incomplete duel.

## Completion contract

Complete the goal only when all of the following are true:

- Movement, camera, lock-on, stamina, light attack, heavy attack, dodge, healing, damage, boss AI, phase transition, victory, failure, and restart all function.
- Boss attacks can be learned from visible anticipation, avoided through positioning or correctly timed dodge, and punished during recovery.
- The duel is balanced well enough to be winnable without being trivial.
- The production build succeeds and both victory and failure paths have been played at both required viewports.

Do not stop after making two models exchange damage. Continue until timing, commitment, feedback, and pattern readability create an actual boss duel.

## Required game systems

- Third-person movement, collision, orbit camera, manual recentering, and optional lock-on with a visible target marker.
- Stamina that drains for attacks and dodge, prevents unaffordable actions, pauses regeneration briefly after use, and regenerates at a readable rate.
- Light attack, slower heavy attack with higher damage, dodge with a short invulnerability window, hit reactions, and actions that cannot all be canceled instantly.
- Three limited healing charges with an interruptible or punishable use animation and no healing above maximum health.
- One boss with pursuit, spacing, target facing, damage, stagger or reaction feedback, death, and at least four attacks: a quick strike, delayed heavy strike, area attack, and gap closer or projectile.
- A clear transition below 50% boss health that changes timing, combinations, reach, or arena pressure rather than only changing color.
- Player health and stamina, boss health and phase, heal count, lock state, action prompts, victory, failure, and restart UI.
- Desktop keyboard/pointer controls and usable phone move, camera, lock, light, heavy, dodge, and heal controls.

## Execution checkpoints

1. Establish arena, player locomotion, collision, camera, lock-on, and responsive input.
2. Implement stamina, player actions, hit windows, invulnerability, damage, healing, and feedback.
3. Implement the boss state machine, four attacks, telegraphs, recovery windows, phase transition, and balance.
4. Complete HUD, start/win/loss/restart flow, visual identity, lighting, effects, camera response, and sound if used.
5. Build and play repeated victory and failure attempts at 1440 x 900 and 390 x 844; fix unavoidable damage, animation/state deadlocks, and UI overlap.

## Quality gates

- Damage occurs only during defined attack windows and respects dodge invulnerability.
- Telegraph, active, and recovery phases are visually distinguishable.
- Lock-on never makes the camera unusable at arena edges or when characters cross.
- Stamina and healing decisions matter, but the initial state permits a fair win.
- Touch controls remain reachable and do not resize or shift during combat.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `health`: finite number from 0 to 100;
- `stamina`: finite number from 0 to 100;
- `healsRemaining`: integer from 0 to 3;
- `bossHealth`: finite number from 0 to 100;
- `bossPhase`: `1` or `2`;
- `lockedOn`: boolean;
- `seed`: `55213`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result, at least one victory playtest, and at least one deliberately tested failure path honestly.
