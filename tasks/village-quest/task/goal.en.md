# Village Quest

## Objective

Build a complete, polished, browser-native 3D third-person quest RPG called **Village Quest** with Three.js. Its shared gameplay reference is the familiar NPC quest, target combat, loot, objective tracking, and turn-in loop of **World of Warcraft**. This is a compact solo vertical slice, not a networked MMO. Use original names, characters, creatures, locations, story, icons, audio, and interface assets.

The player arrives in a small village, speaks to the warden, accepts a quest, travels to a nearby ruin, defeats three corrupted creatures, collects the dropped relic, and returns to the warden for a reward. Victory requires an explicit quest turn-in, not merely defeating enemies.

## Completion contract

Complete the goal only when all of the following are true:

- The entire accept, travel, fight, loot, return, and turn-in sequence is playable and clearly communicated.
- Third-person movement, camera, NPC interaction, dialogue, targeting, abilities, enemy behavior, drops, quest state, and reward all function.
- The village and ruin read as distinct authored places connected by a navigable route.
- The production build succeeds and the full quest chain has been played at both required viewports.

Do not stop after building an RPG scene or a combat demo. Continue until the full quest contract can be completed without guessing.

## Required game systems

- Third-person movement with collision, an orbiting follow camera, readable player facing, and click/tap or key-based interaction.
- One friendly quest-giver with approach cue, dialogue panel, accept action, in-progress dialogue, and completion/reward dialogue.
- Nearest-target or explicit target selection with a visible target frame and range feedback.
- A basic attack plus two abilities: one damage ability with cooldown and one heal or defensive ability with cooldown and resource cost.
- Three hostile creatures near the ruin with aggro range, pursuit, attacks, damage reactions, defeat state, and one deterministic relic drop after all required kills.
- Quest tracker with stages `available`, `accepted`, `creatures-defeated`, `relic-collected`, `ready-to-turn-in`, and `complete`.
- Health, ability resource, cooldowns, target health, objective count, loot pickup, reward presentation, victory, failure, and restart.
- Desktop keyboard/pointer controls and usable phone move, camera, target, interact, attack, and ability controls.

## Execution checkpoints

1. Establish village, route, ruin, player movement, camera, collision, and responsive input.
2. Implement the NPC dialogue and quest state machine from availability through acceptance.
3. Implement targeting, abilities, enemies, combat feedback, defeat, relic drop, and collection.
4. Complete return and turn-in behavior, reward, UI, failure/restart, environment polish, and readable landmarks.
5. Build and play the entire quest at 1440 x 900 and 390 x 844; verify every quest transition and recovery path.

## Quality gates

- The quest tracker and world cues agree on the current required action.
- Enemies cannot attack through solid walls or continue damaging the player after defeat.
- The relic cannot be collected before its drop condition, and the quest cannot complete without returning to the warden.
- Dialogue, target frames, action controls, and the world remain usable without UI overlap on phone.
- Page visibility pauses combat and cooldown progression safely.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `player`: `{ x, y, z }` with finite numbers;
- `health`: finite number from 0 to 100;
- `resource`: non-negative finite number;
- `questStage`: `available`, `accepted`, `creatures-defeated`, `relic-collected`, `ready-to-turn-in`, or `complete`;
- `enemiesDefeated`: integer from 0 to 3;
- `relicCollected`: boolean;
- `targetId`: string or `null`;
- `seed`: `46349`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report the build result and an end-to-end quest playtest at desktop and phone sizes honestly.
