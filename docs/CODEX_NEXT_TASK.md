# 下一条 Codex 任务门禁

M0.2c.1“Battle participation facts 与 BattleRoster”已形成独立本地提交后，先等待用户
审查提交和全部质量检查结果。

未经明确批准，不要继续 M0.2c.2、M0.2c.3、M0.2d 或路线 M1。

M0.2c.1 已完成的边界：

- 可靠 normal participation 才建立 battle entrant；
- 首个稳定画面已退出只记录 entry-not-confirmed；
- `ACTIVE` / `INACTIVE`、原因、呈现与 normal/secret-core 上下文；
- entry 和 inactivation 的稳定 ID、幂等、不可变审计历史；
- false-positive observation correction 与原子重派生；
- 查询派生 `BattleRoster`，不持久化第二份 roster 镜像。

下一步若获批准进入 M0.2c.2，才考虑 runtime slots 与 participant association。未来
面板补查必须先通过底部 `name#XXXX` 或人工确认建立 association，再将 direct panel
evidence 绑定 participant；不得实现 `DIRECT_SLOT_STRATEGY_PANEL` 或 slot-only 策略权威。
仍不得擅自实现 assignment、annotation、OCR、OpenCV、capture、桌面 UI、自动点击、
真实 catalog 或路线 M1。
