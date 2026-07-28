# Sentry Copilot / 卫戍协议助手

一个 **录像回放优先、只读、不自动操作游戏** 的卫戍协议辅助框架。

这份 v0.1 种子工程已把你刚刚纠正的玩家逻辑和新增的地图路径功能落实到代码结构中：

- 左侧玩家头像是个性化头像，只能用于保持槽位连续性，**不能推断玩家策略**。
- 玩家头像下方数字是血量；血量 `<= 0` 时，玩家状态变为 `ELIMINATED`。
- 队友策略通过“用户点击该玩家头像 → 切到其场地 → 点击左上角策略面板 → 助手识别”的引导式流程获取。
- 地图路径按 `ruleset_id + map_id` 版本化，支持普通敌人路线、Boss 路线、阶段路线、停留点和传送段。
- 路线保存在归一化地图坐标中，再通过四角校准/单应性矩阵投影到当前画面。
- 地图或校准置信度不足时不显示猜测路线。

## 快速运行

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
python -m sentry_copilot.cli validate-data --maps data/maps
python -m sentry_copilot.cli demo-route-overlay \
  --map-file data/maps/demo.synthetic_training_map.yaml \
  --output outputs/demo_route_overlay.png
```

演示图完全由合成背景和占位路线生成，不代表真实游戏地图或真实 Boss 路径。

## 架构

```text
Video / Image Folder / Live Window (later)
                     ↓
                 FrameSource
                     ↓
       Scene / HUD / Player / Map recognizers
                     ↓
             typed observations/events
                     ↓
                SessionReducer
                     ↓
                 SessionState
                  ↙       ↘
       knowledge panels   RouteOverlayService
                                 ↓
                 map calibration + route overlay
```

## 玩家策略检查

```text
助手选择要检查的 player_slot
→ 提示用户点击游戏左侧该玩家的个性化头像
→ 提示用户点击该玩家场地左上角的策略入口
→ 识别策略面板
→ 将结果绑定到明确的 player_slot
→ 低置信度时要求用户确认
```

v0.1 不做自动点击。自动输入即使未来研究，也必须是独立适配器，不能混入视觉识别和状态管理。

## 路径功能

```text
识别或手动选择 map_id
→ 找到战场四角/稳定锚点
→ 计算归一化地图到屏幕的投影
→ 根据阶段、回合、敌人、Boss 与 Boss 阶段筛选路线
→ 显示来怪路径、Boss 路径、传送和停留节点
```

第一版先人工标注路线。之后才逐步加入录像中的目标跟踪、轨迹对齐和聚类，避免在真实数据不足时过早训练模型。

## 目录

```text
src/sentry_copilot/
  domain/      对局状态、事件和归并规则
  player/      引导式队友策略检查
  routes/      地图路线模型、筛选、投影和渲染
  vision/      地图识别与校准接口
  services/    模块编排
  capture/     回放帧来源
data/maps/    版本化地图路线 YAML
data/replays/  录像标注元数据，不含视频
docs/          架构、路线系统和 Codex 任务
```

界面范围见 `docs/product-scope-v0.1.md`。从 `docs/CODEX_NEXT_TASK.md` 开始下一轮开发。
