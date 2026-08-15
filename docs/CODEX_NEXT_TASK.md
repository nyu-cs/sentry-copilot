# 下一条 Codex 任务门禁

M0.2c.3“Derive slot strategy assignments”已形成独立本地提交后，先等待用户
审查提交和全部质量检查结果。

未经明确批准，不要继续 M0.2d 或路线 M1。

M0.2c.2 与 M0.2c.3 已完成的边界：

- runtime slot observation、layout epoch 与稳定 slot ID；
- 查询派生 current slots，不持久化第二份镜像；
- 仅关联 confirmed entrants；
- `DIRECT_PLAYER_TAG`、`DIRECT_SELF_MARKER` 与 manual confirmation；
- slot/participant 双向一对一 conflict；
- observation/association 的稳定 ID、幂等纠正和审计历史；
- inactive 与 revision correction 后仍保留 association。
- 只通过无冲突 association、confirmed entrant、effective identification 与 uncontested
  occupancy 查询派生 slot-strategy assignment；
- assignment 不持久化，链路未满足时返回 explicit unresolved reason；
- 不存在 `DIRECT_SLOT_STRATEGY_PANEL` 或任何 slot-only 策略权威。

下一步只能等待明确的 M0.2d 批准。不得擅自实现 annotation、OCR、OpenCV、capture、桌面 UI、
自动点击、真实 catalog 或路线 M1。
