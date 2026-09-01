# Ashen Duel

## Objective

Build a complete, polished, browser-native 3D third-person boss-combat game called **Ashen Duel** with Three.js. Its shared gameplay reference is the familiar lock-on, stamina management, dodge timing, healing, attack commitment, and readable boss-pattern loop of **Elden Ring**. Use original names, characters, arena, attacks, animation, effects, sounds, icons, and interface assets.

The player enters a ruined circular arena and fights one guardian boss. The boss has two phases and at least four distinct telegraphed attacks across the fight. The player wins by reducing the boss to zero health and loses by dying. There are no additional levels, menus, or progression systems to hide an incomplete duel.

## Operational completion contract

The feature lists below define the intended submission and its quality criteria. They do not require exhaustive self-proof. Complete the goal when all of the following operational checks pass:

- `npm run build` succeeds and emits the static production bundle to `dist/`.
- The production build loads at 1440 x 900 and 390 x 844 with a visible, nonblank, interactive 3D scene, no horizontal overflow beyond 2 CSS pixels, and no uncaught page exception or `console.error` during the checked flow.
- One brief smoke check at each viewport confirms that the game can enter its active play state, one primary control changes observable game state, and restart returns to a valid initial state.

Keep these checks bounded. Rerun a failed check only after a relevant fix, and stop once it passes. Do not create an autopilot or repeatedly run full victories, losses, missions, matches, races, services, nights, courses, quests, fights, or puzzle solutions solely to prove completion. Those paths, feature completeness, balance, polish, and game feel are evaluated after submission; shortcomings affect the result, not whether the agent must continue self-testing. Report only the checks actually run.

## Target game systems

- Third-person movement, collision, orbit camera, manual recentering, and lock-on with a visible target marker.
- Stamina that drains for attacks and dodge, prevents unaffordable actions, pauses regeneration briefly after use, and regenerates at a readable rate.
- Light attack, slower heavy attack with higher damage, dodge with a short invulnerability window, hit reactions, and actions that cannot all be canceled instantly.
- Three limited healing charges with an interruptible or punishable use animation and no healing above maximum health.
- One boss with pursuit, spacing, target facing, damage, stagger or reaction feedback, death, and at least four attacks: a quick strike, delayed heavy strike, area attack, and gap closer or projectile.
- A clear transition below 50% boss health that changes timing, combinations, reach, or arena pressure rather than only changing color.
- Player health and stamina, boss health and phase, heal count, lock state, action prompts, victory, failure, and restart UI.
- Desktop keyboard/pointer controls and usable phone move, camera, lock, light, heavy, dodge, and heal controls.
- Minimum input convention: forward movement must respond to either W or Up Arrow on desktop, and the primary phone movement surface must occupy the lower-left control region.

## Execution checkpoints

1. Establish arena, player locomotion, collision, camera, lock-on, and responsive input.
2. Implement stamina, player actions, hit windows, invulnerability, damage, healing, and feedback.
3. Implement the boss state machine, four attacks, telegraphs, recovery windows, phase transition, and balance.
4. Complete HUD, start/win/loss/restart flow, visual identity, lighting, effects, camera response, and sound if used.
5. Build once after the final relevant change, then run the bounded operational smoke checks at 1440 x 900 and 390 x 844. Fix only observed build, startup, blank-frame, input, restart, exception, or layout failures before completing.

## Quality targets

- Damage occurs only during defined attack windows and respects dodge invulnerability.
- Telegraph, active, and recovery phases are visually distinguishable.
- Lock-on never makes the camera unusable at arena edges or when characters cross.
- Stamina and healing decisions matter, but the initial state permits a fair win.
- Touch controls remain reachable and do not resize or shift during combat.

- At both evaluated viewports, horizontal page overflow stays within 2 CSS pixels and the tested flow emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `health`: finite number from 0 to 100;
- `stamina`: finite number from 0 to 100;
- `healsRemaining`: integer from 0 to 3;
- `bossHealth`: finite number from 0 to 100;
- `bossPhase`: `1` or `2`;
- `bossPhaseReached`: `1` or `2`, recording the highest phase actually entered during the run;
- `lockedOn`: boolean;
- `seed`: `55213`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the production build result and the two bounded viewport smoke checks honestly. Full win/loss or end-to-end playthrough evidence is neither required nor requested.
