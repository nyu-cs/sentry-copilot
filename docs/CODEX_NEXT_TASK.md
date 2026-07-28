# 下一条 Codex 任务

在仓库根目录把下面内容交给 Codex：

```text
Read AGENTS.md, PLANS.md, docs/architecture.md, docs/player-inspection.md,
docs/route-system.md and docs/data-contracts.md.

Implement milestone M1 only.

Requirements:
1. Add a replay-overlay CLI command that accepts either a video or an image folder.
2. Accept a map YAML, a route query JSON, and a calibration JSON with four battlefield corners.
3. For each requested timestamp/frame, resolve matching routes, export an overlay PNG, and append
   a typed JSONL observation containing frame index, timestamp, map confidence, calibration
   confidence, matched route IDs, and failure reason when applicable.
4. Do not implement automatic clicks, shop recognition, deployment, or real map recognition.
5. Preserve the rule that personalized avatars are not strategies.
6. Use generated synthetic images in tests. Do not add game assets.
7. Run pytest, ruff, and mypy; fix failures before finishing.
```

验收结果：

- 新的 `replay-overlay` 命令。
- 校准与查询 JSON 示例。
- JSONL 输出契约。
- 合成数据集成测试。
- README 更新。
