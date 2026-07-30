# 下一条 Codex 任务门禁

M0.2a.1“SessionRulesetContext 与规范化 ID”完成后先检查 diff 和全部质量检查结果。

未经明确批准，不要继续 M0.2a.2、M0.2b 或路线 M1。

下一增量 M0.2a.2 只包含：

- revision-aware synthetic strategy catalog；
- revision profile 上的 `initial_hp`、`icon_visual_key` 和 `icon_asset_reference`；
- revision-aware locale resources；
- catalog lookup、validation 与 support metadata；
- synthetic strategies 和 synthetic icons。

M0.2a.2 不包含真实策略数据、真实图标、PRTS 抓取、occupancy、runtime assignment、
structured effects、推荐倾向、OCR、OpenCV、桌面 UI 或自动点击。Catalog 文件若使用
YAML，必须复用当前已有的 PyYAML 依赖；运行时 repository 与 repository validation
必须调用同一解析和验证逻辑，不为 synthetic catalog 增加新的解析依赖。
