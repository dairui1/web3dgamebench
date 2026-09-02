# Pi Harness 收敛与 Season 1 重启 TODO

## 当前决定

- [x] 保持 Season 1 Matrix 停止，不从当前 receipt 继续执行。
- [x] 不直接切换到普通 Pi：虽然能较快退出，但没有可验证的 goal lifecycle，且本次官方 evaluator 仅通过 14/20。
- [x] 不采用 `pi-goal-pro`：它不能直接驱动当前 `pi --print`，并且本次 `autoTurnCount` 达到 39/25 后仍未暂停。
- [x] 在完成下面的 calibration gate 前，不重跑 80-cell Matrix，不发布任何候选产物。

旧 Matrix 已于 2026-09-02 显式标记为 `invalidated`。冻结快照包含 6 个 `completed`、8 个 `evidence-failure`、1 个 `interrupted`、1 个在终止旧恢复调度器时保留为 `running` 的 cell 和 64 个 `pending` cell；不手工改写旧 receipt。

## P0：冻结与保全

- [x] 确认没有 Matrix、Harbor candidate 或遗留 Chromium 进程继续运行，并移除旧的自动恢复 LaunchAgent。
- [x] 保留当前 matrix receipt、interrupted/running run、原始 trace、workspace 和 evaluator 报告，不覆盖或手工修复。
- [x] 将本次非 canonical A/B 结果登记为诊断证据，不纳入 leaderboard、publisher 或正式 Season receipt。
- [x] 为当前 plan 标记 runtime/control semantics 已变更；旧 canonical matrix 已审计性 invalidated，不再复用旧 plan。

诊断摘要位于：
`~/.local/state/web3dgamebench/experiments/pi-goal-ab-20260902T034619Z/summary.json`

当前冻结产物：

- Plan：`~/.local/state/web3dgamebench/runs/plans/season-1-build-only-v3-20260902T114050Z.json`
- Plan digest：`656316e5037a9855da44aff26545b9be3b2e4a4c1432952e66b87eea1161b190`
- Smoke receipt：尚未为此 plan 生成；旧 receipt 已因 Goal、adapter 和镜像变化而失效。
- Candidate image：`web3dgamebench-candidate:0.2.0` / `sha256:1cde9f7cf7c7a3c3f9d286ff6c1f47493f5e64131f2ba396dcfc17e5da1750f5`

## P1：本地 Matrix Control Plane

- [x] 新增只监听 loopback 的 `web3dgamebench control`，WebUI 关闭或 Codex 退出不影响其托管的 Matrix 子进程。
- [x] WebUI 通过既有 Matrix CLI 启动或恢复 Harbor backend，不直接调用 Docker、Harbor 或改写 receipt。
- [x] 支持在下一个 task barrier 暂停；控制命令绑定 `matrix_id`、持久化并由 Matrix 在 barrier 审计性确认。
- [x] 支持立即中断托管进程组并沿用现有 trace 保全与 `interrupted` 恢复语义。
- [x] 展示 10 × 8 cell 网格、状态分类、当前 task、plan/smoke/image provenance、runner 日志和 cell artifacts。
- [x] 写操作使用本地随机 token，拒绝非 loopback Host/Origin；浏览器不接收模型凭证。
- [x] 将 control runtime、UI 和 host dependency lock 纳入冻结 plan，并重新生成匹配的 Harbor smoke receipt。
- [x] 前端由 Claude Code `2.1.258` + `claude-fable-5-1` 实现，经 1440 × 900 和 390 × 844 浏览器验收。

## P1：实现 Benchmark 专用 Pi Adapter

- [x] 移除对通用 Goal 插件 completion policy 的依赖，保留 Pi `0.84.4`、模型、工具集和候选镜像的其他冻结条件。
- [x] 新增 benchmark 专用 lifecycle，至少提供 `active`、`complete`、`blocked`、`interrupted` 和 `timed_out` 终态，并写入结构化 trace。
- [x] 将外部 Goal 缩短为“实现 TASK.md，并在 `npm run build` 成功后停止”。
- [x] 明确声明：feature completeness、平衡、game feel 和完整胜负流程由提交后的 evaluator/judge 评估，不是候选自证终点。
- [x] 提供结构化 completion tool，只要求最终一次 `npm run build` 成功、TASK.md hash 未变化，且 source/dist 与该构建一致。
- [x] completion tool 只校验 evidence 结构和真实命令记录，不要求完整通关，也不把候选自述当作 evaluator 通过。
- [x] 由 runner 负责等待并记录 lifecycle 终态，避免依赖交互式 slash command 保持 `pi --print` 存活。

## P1：外部强制收敛

- [x] 外部 watchdog 由 runner/process-group 负责，能够中断单次长 agent run，而不是只在 `agent_end` 后检查。
- [x] 保留 wall clock 和单条 shell command 的硬边界；不对实现阶段做粗粒度的全局 turn/tool cap，改为在 source + dist revision 构建成功后立即收敛。
- [x] 对连续重复的 full-playthrough、autopilot 或同一路径浏览器脚本发出一次收敛提醒；再次发生则终止为明确的 candidate verification overrun。
- [x] 保留正式 cell 的 `7200s` 硬上限，但 calibration 阶段增加 `2700s` 的外部诊断上限，避免再次为已识别的循环消耗两小时。
- [x] 将 timeout 分类拆开：provider/Harbor infrastructure failure 与 candidate non-termination 不再混为一类。

## P2：Evaluator 对齐

- [x] 删除候选侧 smoke helper 和所有 Goal 中的 smoke evidence 要求。
- [x] 明确禁止候选编写浏览器自动化、autopilot 或完整通关脚本。
- [x] 保持 adapter completion 与 evaluator admission 为两个独立 gate：前者在构建成功后结束候选执行，后者独立判断 submission 是否可信可玩。

## P2：Calibration Gate

- [ ] 使用全新、非 canonical workspace 运行 `bombsite-retake`、`canyon-strike` 和 `first-night`。
- [ ] 第一轮只跑 `pi-deepseek-v4-flash`，保持同一 provider/model 串行执行，禁止与 canonical Matrix 并发。
- [ ] 对每个任务比较现有 adapter 与新 adapter；普通 Pi 和 `pi-goal-pro` 仅保留为历史诊断，不再扩大样本。
- [ ] 每个 calibration run 保存 prompt/control hash、镜像 digest、trace、workspace digest、completion receipt 和 evaluator report。
- [ ] 新 adapter 必须全部满足以下条件才可进入正式重启：
  - 3/3 lifecycle 得到可信终态，无 Harbor `7200s` timeout；
  - TASK.md 未修改；
  - build evidence 完整，TASK.md、source 和 dist digest 一致；
  - 没有为了 completion 反复运行完整胜负流程；
  - evaluator 结果不低于相同 workspace budget 下的现有 adapter 基线；
  - watchdog 能在测试用无限单次 agent run 中真实抢占，而不是只更新计数器。
- [ ] 任一条件失败则继续修 adapter，Matrix 保持停止。

## P3：正式重启条件

- [x] bump Pi runtime/control/adapter version，并更新冻结的 image digest 与 runtime evidence schema。
- [x] 补齐 unit、integration、Harbor smoke、timeout counterexample 和 receipt verification tests。
- [x] 将旧 plan 标记 stale，保留原始审计记录，不原地修改旧 receipt。
- [x] 重新生成 Season 1 plan，并核对完整 80-cell matrix、task barrier 和 profile 顺序；价格仍按冻结 pricing 配置与实际 token buckets 在 receipt 中结算。
- [ ] 在控制台手动生成与新 plan、镜像和 adapter digest 一致的 harness smoke receipt。
- [ ] 只有 plan review 与 smoke receipt 同时通过后，才从第一个 task barrier 重新开始完整 Matrix。
- [ ] 执行期间继续遵守 same-task profiles 可并行、tasks 串行；不得混入 calibration 或人工修补 workspace。
- [ ] 80-cell closure、Fable backfill、judge、publisher 全部完成前不得发布 task prompt 或生成游戏源码。

## 本次诊断基线

| 方案 | 终止情况 | 官方 evaluator | 结论 |
| --- | --- | --- | --- |
| 现有 `pi-goal` 超时快照 | `7200s` timeout | 19/20 | 产物最好，但未收敛 |
| 普通 Pi | 1814s，exit 0 | 14/20 | 较快退出，但自测与 evaluator 明显错位 |
| `pi-goal-pro 1.3.1` | 1823s 时仍 active，人工中断 | 17/20 | 需要非交互 shim，且 25-turn 上限未生效 |

注意：本次 `pi-goal-pro` run 与一个意外重启的 canonical DeepSeek cell 并发，耗时和 provider latency 不能作为严格 A/B 证据；其 `--print` 兼容性和 `39/25` 未暂停属于结构性证据。
