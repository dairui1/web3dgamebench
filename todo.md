# Pi Harness 收敛与 Season 1 重启 TODO

## 当前决定

- [x] 保持 Season 1 Matrix 停止，不从当前 receipt 继续执行。
- [x] 不直接切换到普通 Pi：虽然能较快退出，但没有可验证的 goal lifecycle，且本次官方 evaluator 仅通过 14/20。
- [x] 不采用 `pi-goal-pro`：它不能直接驱动当前 `pi --print`，并且本次 `autoTurnCount` 达到 39/25 后仍未暂停。
- [x] 正式 Matrix 只依赖冻结 plan 与匹配的 Harbor smoke receipt，不再执行额外的完整游戏预检。

旧 Matrix 曾于 2026-09-02 显式标记为 `invalidated`；随后已按操作要求删除全部旧 Matrix receipt、run workspace、canonical claim 和 control history。历史诊断摘要单独保留，不可恢复或纳入正式 Season 1。

## P0：冻结与保全

- [x] 确认没有 Matrix、Harbor candidate 或遗留 Chromium 进程继续运行，并移除旧的自动恢复 LaunchAgent。
- [x] 删除全部旧 Matrix receipt、run workspace、canonical claim 和 control history，使控制台从空白状态重新开始。
- [x] 将本次非 canonical A/B 结果登记为诊断证据，不纳入 leaderboard、publisher 或正式 Season receipt。
- [x] 为当前 plan 标记 runtime/control semantics 已变更；旧 canonical matrix 已审计性 invalidated，不再复用旧 plan。

诊断摘要位于：
`~/.local/state/web3dgamebench/experiments/pi-goal-ab-20260902T034619Z/summary.json`

当前冻结产物：

- Plan：`~/.local/state/web3dgamebench/runs/plans/season-1-90m-20260902T135349Z.json`
- Plan digest：`517560ecb521b3e80e357dfe9eea9dde279ff471a9b3bdcc7e7e567c7cf42e2d`
- Smoke receipt：`~/.local/state/web3dgamebench/runs/smoke/season-1-20260902T135351Z-a4034470-730cdc52/receipt.json`（3/3 harness passed）。
- Candidate image：`web3dgamebench-candidate:0.3.0` / `sha256:66e16b8f9d041bb8b5f17fda5f7aee7b9ee93ff7cf49b041ad3c75d2d54ca1e1`

## P1：本地 Matrix Control Plane

- [x] 新增只监听 loopback 的 `web3dgamebench control`，WebUI 关闭或 Codex 退出不影响其托管的 Matrix 子进程。
- [x] WebUI 通过既有 Matrix CLI 启动或恢复 Harbor backend，不直接调用 Docker、Harbor 或改写 receipt。
- [x] 支持在下一个 task barrier 暂停；控制命令绑定 `matrix_id`、持久化并由 Matrix 在 barrier 审计性确认。
- [x] 支持立即中断托管进程组并沿用现有 trace 保全与 `interrupted` 恢复语义。
- [x] 展示 10 × 8 cell 网格、状态分类、当前 task、plan/smoke/image provenance、runner 日志和 cell artifacts。
- [x] 写操作使用本地随机 token，拒绝非 loopback Host/Origin；浏览器不接收模型凭证。
- [x] 将 control runtime、UI 和 host dependency lock 纳入冻结 plan，并重新生成匹配的 Harbor smoke receipt。
- [x] 前端由 Claude Code `2.1.258` + `claude-fable-5-1` 实现，经 1440 × 900 和 390 × 844 浏览器验收。

## P1：收缩为原生 pi-goal + 薄 Bridge

- [x] 使用未修改的 `@narumitw/pi-goal@0.54.4`，不再维护 benchmark 专用 fork、completion tool 或 prompt policy。
- [x] 只保留薄 bridge：启动 upstream managed run，让 `pi --print` 等待终态，并写入统一 lifecycle 事件。
- [x] 将外部 Goal 缩短为“实现 TASK.md，并在 `npm run build` 成功后停止”。
- [x] 明确声明：feature completeness、平衡、game feel 和完整胜负流程由提交后的 evaluator/judge 评估，不是候选自证终点。
- [x] Goal complete 只代表上游 lifecycle 结束；TASK hash、独立构建、source/dist digest 由 runner evaluator 在退出后验证。

## P1：外部强制收敛

- [x] 外部 watchdog 由 runner/process-group 负责，能够中断单次长 agent run，而不是只在 `agent_end` 后检查。
- [x] 保留 wall clock 和单条 shell command 的硬边界，不对实现阶段做粗粒度的全局 turn/tool cap。
- [x] 正式 cell 与 Pi shell command 统一使用 `5400s`（90 分钟）硬上限。
- [x] 将 timeout 分类拆开：provider/Harbor infrastructure failure 与 candidate non-termination 不再混为一类。

## P2：Evaluator 对齐

- [x] 删除候选侧 smoke helper 和所有 Goal 中的 smoke evidence 要求。
- [x] 将十个候选可见 TASK 全部缩成单段自然用户 prompt，不暴露 schema、检查点、数值阈值或 evaluator 验收清单。
- [x] 保持 Goal completion 与 evaluator admission 为两个独立 gate：前者结束候选执行，后者独立判断 submission 是否可信可玩。

## P2：移除额外校准门禁

- [x] 删除三任务非 canonical 运行、receipt 指针和 `web3dgamebench calibrate` CLI。
- [x] 删除 Matrix 与控制台对校准 receipt 的启动依赖。
- [x] 保留普通 Harbor smoke 作为 plan-bound harness 预检；不再用完整游戏生成充当前置 smoke。

## P3：正式重启条件

- [x] bump Pi runtime/control/bridge version，并更新冻结的 image digest 与 runtime evidence schema。
- [x] 补齐 unit、integration、Harbor smoke、timeout counterexample 和 receipt verification tests。
- [x] 将旧 plan 标记 stale，保留原始审计记录，不原地修改旧 receipt。
- [x] 重新生成 Season 1 plan，并核对完整 80-cell matrix、task barrier 和 profile 顺序；价格仍按冻结 pricing 配置与实际 token buckets 在 receipt 中结算。
- [x] 生成与新 plan、镜像和 bridge digest 一致的 harness smoke receipt。
- [ ] 只有 plan review 与 smoke receipt 同时通过后，才从第一个 task barrier 重新开始完整 Matrix。
- [ ] 执行期间继续遵守 same-task profiles 可并行、tasks 串行；不得人工修补 workspace。
- [ ] 80-cell closure、Fable backfill、judge、publisher 全部完成前不得发布 task prompt 或生成游戏源码。

## 本次诊断基线

| 方案 | 终止情况 | 官方 evaluator | 结论 |
| --- | --- | --- | --- |
| 历史 `pi-goal` 超时快照（统一 90 分钟前） | `7200s` timeout | 19/20 | 产物最好，但未收敛 |
| 普通 Pi | 1814s，exit 0 | 14/20 | 较快退出，但自测与 evaluator 明显错位 |
| `pi-goal-pro 1.3.1` | 1823s 时仍 active，人工中断 | 17/20 | 需要非交互 shim，且 25-turn 上限未生效 |

注意：本次 `pi-goal-pro` run 与一个意外重启的 canonical DeepSeek cell 并发，耗时和 provider latency 不能作为严格 A/B 证据；其 `--print` 兼容性和 `39/25` 未暂停属于结构性证据。
