# 下一条 Codex 任务门禁

M0.2a.2“Revision-aware synthetic strategy catalog”完成后，先审查独立提交和全部质量检查。

未经明确批准，不要继续 M0.2a.3、M0.2b 或路线 M1。

下一增量 M0.2a.3 只包含：

- 手动选择与 replay metadata 导入 revision；
- 同一 session 内可重复、原子、可审计的显式 revision correction；
- 单一当前 revision 与完整 revision change history；
- mismatch 报告，不静默切换 revision；
- revision-independent evidence 保留；
- 通过 dependency stamp 表达未来 revision-dependent derived state 的失效。

M0.2a.3 不得创建尚不存在的 occupancy、assignment、annotation 或 coverage 缓存，也不
包含真实 catalog、真实图标、PRTS 抓取、OCR、OpenCV、capture、桌面 UI 或自动点击。
