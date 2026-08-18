# 下一条 Codex 任务门禁

M0.3c“Recognition Probe Harness”形成独立本地提交后，先等待用户审查提交和全部质量检查结果。

未经明确批准，不要继续 M0.2d、游戏特定识别或路线 M1。

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

M0.3c 仅组合既有单帧 FrameSource、显式 ROI、OCR 与模板匹配为 caller-owned 调试工具；
不得擅自实现自动 ROI 检测、游戏页面/玩家/策略识别、桌面 UI、自动点击、真实 catalog 或路线 M1。
