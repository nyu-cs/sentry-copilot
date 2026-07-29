# Sentry Copilot / 卫戍协议助手

一个 **录像回放优先、只读、不自动操作游戏** 的卫戍协议辅助框架。

这份 v0.1 种子工程已把你刚刚纠正的玩家逻辑和新增的地图路径功能落实到代码结构中：

- 左侧玩家头像是个性化头像，只能用于保持槽位连续性，**不能推断玩家策略**。
- 玩家头像下方数字是血量；当前种子模型在血量 `<= 0` 时写入 legacy `ELIMINATED`。
  后续 runtime 业务模型会归一为 `INACTIVE + HP_DEPLETED`，并独立记录是否离开或观战。
- 策略选择界面是主要采集时机；reducer 维护的最多四人策略快照是本局策略权威状态。
- 单人或多人实际参战人数由 `expected_participant_count` 明确记录，不能按已识别行数猜测。
- 策略快照保存历史选择；局内退出、断线或淘汰不会删除玩家或改变快照完整度。
- `#XXXX` 以四位字符串保存并且只在本局唯一；策略选择行不等于局内左侧槽位。
- 左上角策略面板仅作为缺失补充、局内消歧或人工验证的备用来源。
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

## 策略选择阶段快照

```text
策略选择界面观察最多四行玩家信息
→ 为每行建立 session-local participant
→ 按字段保存编号、名字、头像、策略、ready 与证据
→ 明确记录实际参战人数，不按识别出的行数推断
→ reducer 合并为当前 StrategySelectionSnapshot
→ 离开选择阶段时冻结
→ 局内查询读取实际参战玩家的历史策略，不要求 runtime slot 映射
```

快照冻结、最终入场人数已知且每名 `ENTERED_BATTLE` 参与者的策略均确认时，即可供
局内查询；单人、三人或四人对局使用同一规则。选择阶段退出者仍保留在原始快照，
但不进入默认最终队伍查询。部分玩家名、头像或编号仍可未知。运行时仍存活人数与
快照记录人数彼此独立。左上角面板流程保留为未来 fallback，所有切换和打开面板
操作都由用户完成。v0.1 不做自动点击。

`TeamStrategyContext` 是历史策略上下文，不是当前有效队伍查询。未来 active-team
查询会排除所有 `INACTIVE` 玩家，但不会修改历史策略快照。

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
  domain/      对局状态、最多四人策略快照、字段证据和归并规则
  player/      引导式 fallback 策略检查
  routes/      地图路线模型、筛选、投影和渲染
  vision/      地图识别与校准接口
  services/    模块编排
  capture/     回放帧来源
data/maps/    版本化地图路线 YAML
data/replays/  录像标注元数据，不含视频
docs/          架构、路线系统和 Codex 任务
```

界面范围见 `docs/product-scope-v0.1.md`。从 `docs/CODEX_NEXT_TASK.md` 开始下一轮开发。
