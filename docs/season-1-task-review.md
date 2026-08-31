# Web3DGameBench Season 1 Task Review

Status: **draft for human review**. None of these tasks belongs to a runnable season yet.

Signal Drift remains an immutable `Pilot 0` artifact. The proposed official season contains ten recognizable 3D game archetypes. Each task has one canonical English goal contract for candidate runs and one Chinese mirror for review. Goal mode must be activated by the harness outside the task prompt; the candidate prompt itself must never instruct a model to invoke `/goal`.

| # | Task | Familiar reference | Core completion event | English | 中文 |
|---|---|---|---|---|---|
| 1 | Canyon Strike | Ace Combat | Destroy the strike package and exit through extraction | [EN](../tasks/canyon-strike/task/goal.en.md) | [中文](../tasks/canyon-strike/task/goal.zh-CN.md) |
| 2 | Bombsite Retake | Counter-Strike 2 | Secure the site and defuse the planted device | [EN](../tasks/bombsite-retake/task/goal.en.md) | [中文](../tasks/bombsite-retake/task/goal.zh-CN.md) |
| 3 | First Night | Minecraft | Gather, craft, build, place the beacon, and survive nightfall | [EN](../tasks/first-night/task/goal.en.md) | [中文](../tasks/first-night/task/goal.zh-CN.md) |
| 4 | Village Quest | World of Warcraft | Accept, complete, and turn in one quest chain | [EN](../tasks/village-quest/task/goal.en.md) | [中文](../tasks/village-quest/task/goal.zh-CN.md) |
| 5 | Ashen Duel | Elden Ring | Read and defeat a multi-phase boss | [EN](../tasks/ashen-duel/task/goal.en.md) | [中文](../tasks/ashen-duel/task/goal.zh-CN.md) |
| 6 | Linked Chamber | Portal 2 | Use paired portals and a cube to reach the exit | [EN](../tasks/linked-chamber/task/goal.en.md) | [中文](../tasks/linked-chamber/task/goal.zh-CN.md) |
| 7 | Star Course | Super Mario 64 | Traverse the course and collect the goal star | [EN](../tasks/star-course/task/goal.en.md) | [中文](../tasks/star-course/task/goal.zh-CN.md) |
| 8 | Turbo Circuit | Mario Kart | Complete three laps against three racers | [EN](../tasks/turbo-circuit/task/goal.en.md) | [中文](../tasks/turbo-circuit/task/goal.zh-CN.md) |
| 9 | Frontier Command | Warcraft III | Gather, build, train, and destroy the enemy keep | [EN](../tasks/frontier-command/task/goal.en.md) | [中文](../tasks/frontier-command/task/goal.zh-CN.md) |
| 10 | Dinner Rush | Overcooked | Prepare and deliver the required orders before closing | [EN](../tasks/dinner-rush/task/goal.en.md) | [中文](../tasks/dinner-rush/task/goal.zh-CN.md) |

## Goal contract policy

- The harness activates its native persistent-goal mechanism externally, then supplies the exact canonical English contract unchanged.
- No fixed wall-clock or token limit is embedded in a task. Completion is evidence-based.
- A candidate must not stop at a visual prototype. It completes only after the full win/loss loop, required controls, production build, and desktop/phone playtests pass.
- Milestones are execution checkpoints, not permission to omit later work.
- Classic game names establish a shared interaction reference only. Every submission must use original names, geometry, maps, characters, audio, and other assets.
- Chinese files are review mirrors and are not sent alongside English files during a scored run.
