# Frontier Command

## Objective

Build a complete, polished, browser-native 3D real-time strategy game called **Frontier Command** with Three.js. Its shared gameplay reference is the familiar unit selection, resource gathering, base construction, unit production, command, and enemy-base assault loop of **Warcraft III**. Use original names, factions, units, buildings, terrain, sounds, icons, and interface assets.

The player begins with one keep and three workers on a compact battlefield containing wood and ore. Gather resources, construct one barracks, train at least three soldiers, repel an enemy raid, and destroy the opposing keep. The player wins when the enemy keep is destroyed and loses when their own keep is destroyed.

## Completion contract

Complete the goal only when all of the following are true:

- Camera navigation, selection, commands, gathering, carrying, depositing, building placement and construction, production, combat, enemy behavior, victory, failure, and restart all function.
- Units navigate around static blockers and each other well enough to obey orders without permanent clumping or deadlock.
- The economic and combat loop requires genuine gathering and production; the starting force cannot immediately win.
- The production build succeeds and complete winning and losing matches have been played at both required viewports.

Do not stop after placing units on terrain. Continue until the player can execute a complete RTS build-and-attack plan with readable feedback.

## Required game systems

- Elevated perspective camera with edge or key panning, drag panning, bounded zoom, map boundaries, and touch gestures or explicit phone camera controls.
- Click/tap selection, drag-box multi-selection on desktop, visible selected state, selection information, and right-click or explicit action commands for move, gather, build, and attack.
- Three starting workers that can gather from at least four wood nodes and three ore nodes, carry limited resources, return them to the keep, and resume assigned work.
- Grid-valid barracks placement with visible preview, blocked/affordable feedback, construction time, resource cost, and cancellation or safe rejection of invalid placement.
- A barracks queue that trains soldiers for a resource cost and visible duration. At least three trained soldiers are required to make the final assault practical.
- Friendly and enemy units with movement, target acquisition, attack range, cooldown, damage, health, death, basic separation, and obstacle-aware navigation.
- An enemy base with one keep, two defenders, and one timed raid against the player. The enemy keep must not be vulnerable before the match begins.
- Wood, ore, population, selection, build actions, production queue, health bars, current objective, warnings, victory, failure, and restart UI.
- Desktop pointer/keyboard controls and usable phone selection, camera, move/attack, gather, build, and production controls.

## Execution checkpoints

1. Establish battlefield, camera, selection, commands, navigation grid, responsive input, and both bases.
2. Implement workers, resource nodes, carrying, depositing, economy UI, and stable repeated gathering.
3. Implement barracks placement/construction, production queue, soldiers, combat, enemy defenders, and timed raid.
4. Complete balance, victory/loss/restart, action feedback, health and selection UI, authored terrain, landmarks, materials, and effects.
5. Build and play complete winning and losing matches at 1440 x 900 and 390 x 844; test blocked paths, invalid building placement, depleted resources, resize, and unit recovery.

## Quality gates

- Commands produce immediate visible acknowledgement and units reach reasonable legal destinations.
- Resources cannot be gained without a worker completing gather and deposit steps.
- Buildings cannot overlap units, resources, blockers, other buildings, or map boundaries.
- Enemy attacks create pressure without arriving before the player can form a basic response.
- Phone controls expose every required command without relying on right-click or hover.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `camera`: `{ x, y, z }` with finite numbers;
- `wood`: non-negative integer;
- `ore`: non-negative integer;
- `selectedUnits`: non-negative integer;
- `workersAlive`: integer from 0 to 3;
- `soldiersAlive`: non-negative integer;
- `barracksBuilt`: boolean;
- `playerKeepHealth`: finite number from 0 to 100;
- `enemyKeepHealth`: finite number from 0 to 100;
- `seed`: `91373`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result and complete win/loss match playtests at desktop and phone sizes honestly.
