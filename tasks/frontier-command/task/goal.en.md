# Frontier Command

## Objective

Build a complete, polished, browser-native 3D real-time strategy game called **Frontier Command** with Three.js. Its shared gameplay reference is the familiar unit selection, resource gathering, base construction, unit production, command, and enemy-base assault loop of **Warcraft III**. Use original names, factions, units, buildings, terrain, sounds, icons, and interface assets.

The player begins with one keep and three workers on a compact battlefield containing wood and ore. Gather resources, construct one barracks, train at least three soldiers, repel an enemy raid, and destroy the opposing keep. The player wins when the enemy keep is destroyed and loses when their own keep is destroyed.

## Operational completion contract

The feature lists below define the intended submission and its quality criteria. They do not require exhaustive self-proof. Complete the goal when all of the following operational checks pass:

- `npm run build` succeeds and emits the static production bundle to `dist/`.
- The production build loads at 1440 x 900 and 390 x 844 with a visible, nonblank, interactive 3D scene, no horizontal overflow beyond 2 CSS pixels, and no uncaught page exception or `console.error` during the checked flow.
- One brief smoke check at each viewport confirms that the game can enter its active play state, one primary control changes observable game state, and restart returns to a valid initial state.

Keep these checks bounded. Rerun a failed check only after a relevant fix, and stop once it passes. Do not create an autopilot or repeatedly run full victories, losses, missions, matches, races, services, nights, courses, quests, fights, or puzzle solutions solely to prove completion. Those paths, feature completeness, balance, polish, and game feel are evaluated after submission; shortcomings affect the result, not whether the agent must continue self-testing. Report only the checks actually run.

## Target game systems

- Elevated perspective camera with edge or key panning, drag panning, bounded zoom, map boundaries, and touch gestures or explicit phone camera controls.
- Click/tap selection, drag-box multi-selection on desktop, visible selected state, selection information, and right-click or explicit action commands for move, gather, build, and attack.
- Three starting workers that can gather from at least four wood nodes and three ore nodes, carry limited resources, return them to the keep, and resume assigned work.
- Grid-valid barracks placement with visible preview, blocked/affordable feedback, construction time, resource cost, and cancellation or safe rejection of invalid placement.
- A barracks queue that trains soldiers for a resource cost and visible duration. At least three trained soldiers are required to make the final assault practical.
- Friendly and enemy units with movement, target acquisition, attack range, cooldown, damage, health, death, basic separation, and obstacle-aware navigation.
- An enemy base with one keep, two defenders, and one timed raid against the player. The enemy keep must not be vulnerable before the match begins.
- Wood, ore, population, selection, build actions, production queue, health bars, current objective, warnings, victory, failure, and restart UI.
- Desktop pointer/keyboard controls and usable phone selection, camera, move/attack, gather, build, and production controls.
- Minimum input convention: camera-forward pan must respond to either W or Up Arrow on desktop; phone camera pan must work from a direct gesture on the battlefield or an explicit visible control.

## Execution checkpoints

1. Establish battlefield, camera, selection, commands, navigation grid, responsive input, and both bases.
2. Implement workers, resource nodes, carrying, depositing, economy UI, and stable repeated gathering.
3. Implement barracks placement/construction, production queue, soldiers, combat, enemy defenders, and timed raid.
4. Complete balance, victory/loss/restart, action feedback, health and selection UI, authored terrain, landmarks, materials, and effects.
5. Build once after the final relevant change, then run the bounded operational smoke checks at 1440 x 900 and 390 x 844. Fix only observed build, startup, blank-frame, input, restart, exception, or layout failures before completing.

## Quality targets

- Commands produce immediate visible acknowledgement and units reach reasonable legal destinations.
- Resources cannot be gained without a worker completing gather and deposit steps.
- Buildings cannot overlap units, resources, blockers, other buildings, or map boundaries.
- Enemy attacks create pressure without arriving before the player can form a basic response.
- Phone controls expose every required command without relying on right-click or hover.

- At both evaluated viewports, horizontal page overflow stays within 2 CSS pixels and the tested flow emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `camera`: `{ x, y, z }` with finite numbers;
- `wood`: non-negative integer;
- `ore`: non-negative integer;
- `selectedUnits`: non-negative integer;
- `workersAlive`: integer from 0 to 3;
- `soldiersAlive`: non-negative integer;
- `soldiersTrained`: non-negative integer counting completed barracks production;
- `barracksBuilt`: boolean;
- `raidResolved`: boolean that becomes true only after the timed enemy raid has occurred and no raid attacker remains;
- `playerKeepHealth`: finite number from 0 to 100;
- `enemyKeepHealth`: finite number from 0 to 100;
- `seed`: `91373`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the production build result and the two bounded viewport smoke checks honestly. Full win/loss or end-to-end playthrough evidence is neither required nor requested.
