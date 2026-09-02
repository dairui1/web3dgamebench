# Web3DGameBench Season 1 Task Review

Status: **task contracts revised; all pre-revision plans and runs are invalid**. Season 1 must begin
again at Canyon Strike using a plan and smoke receipt generated after this revision. The official
rerun uses the repository-controlled Harbor matrix; historical parity-lab artifacts are not Season 1 evidence.

This review document does not define the execution matrix. `configs/seasons.toml` assigns all ten
tasks to `season-1`; its profile list, resolved through `configs/profiles.toml`, is the authoritative
harness and model set. Before any paid run, inspect the complete expansion with
`uv run web3dgamebench plan --season season-1`.

Signal Drift remains an immutable `Pilot 0` artifact. The official season contains ten recognizable 3D game archetypes. Each task has one canonical English goal contract for candidate runs and one Chinese mirror for review. Persistent execution control is activated by the harness outside the task prompt; the candidate prompt itself never instructs a model to invoke `/goal`.

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

## Differentiation rationale

Season 1 does not use ten variations of the same movement demo. Its critical paths span flight
physics, tactical combat, editable voxel state, quest state machines, boss telegraphs, paired
portal rendering and spatial transforms, precision platforming, racing AI, RTS economy and navigation, and concurrent
kitchen workflows. Each task couples several systems and defines a causally valid win path as a
quality target. Candidate completion requires only a successful production build; desktop and phone
runtime admission, deterministic evaluation, private playtest judging, and human preference
then measure feature completeness and game effect. A polished scene or a fabricated runtime object
therefore cannot earn a strong semantic judgment merely by passing admission.

After the private matrix closes, retain per-task admission rate, rubric evidence coverage, score
distribution, broken-vote rate, and pairwise preference entropy. Near-universal success, a
near-universal floor, or criteria that are routinely unverified are calibration findings to address
in the next season; they are not reasons to change a frozen Season 1 task after scored runs begin.

## Goal contract policy

- The harness activates an audited external persistence control, then supplies the exact canonical English contract unchanged. Codex, Claude Code, and Pi must all expose observed Goal creation and completion in their traces; Pi uses the frozen benchmark adapter's structured lifecycle rather than the generic interactive completion policy.
- No wall-clock or token limit is embedded in a task contract. The runtime applies a two-hour formal-cell ceiling, a 2700-second non-canonical calibration ceiling, and revision-scoped bounded verification without a global implementation turn/tool cap.
- Candidate completion is operational: the production build must load as a visible, interactive 3D game at both viewports, a primary control and restart must work, and the checked flow must avoid runtime and layout failures.
- Candidates are not asked to write autopilots or prove full win/loss and end-to-end paths. Missing systems, balance, polish, and game feel lower the evaluated result instead of forcing indefinite self-testing.
- Milestones and target systems guide implementation and grading; they are not an exhaustive self-proof checklist.
- Classic game names establish a shared interaction reference only. Every submission must use original names, geometry, maps, characters, audio, and other assets.
- Chinese files are review mirrors and are not sent alongside English files during a scored run.
