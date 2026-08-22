---
name: unity-skills-guidelines
description: "规定 CKStudy 项目中 UnitySkills 的连接、模块选择、安全调用和验证闭环。用于任何需要通过 UnitySkills 操作 Unity Editor 的任务，包括场景、资源、GameObject、组件、脚本、批量操作、实例连接、C# 编译、Unity Test Runner 和临时 Python 调用；作为项目使用规范层，与底层 unity-skills 功能模块共同触发。"
---

# UnitySkills 使用规范

先遵守本 Skill 的项目级规则，再按任务加载 `unity-skills` 的相关功能或设计模块。底层 Skill 提供能力、schema 和权限协议；本 Skill 只规定 CKStudy 的路由、稳定入口和验证闭环。

## 能力路由

1. 普通场景、资源、GameObject、组件、脚本和项目操作，加载 `.agents/skills/unity-skills` 下对应模块；不要在本 Skill 重复模块文档或猜测参数。
2. 当前项目 C# 编译使用 `.agents/skills/unity-skills-guidelines/scripts/unity_compile.py`；Unity Test Runner 使用 `.agents/skills/unity-skills-guidelines/scripts/unity_test.py`。
3. 运行时 UI 树检查、点击、拖动、滚轮和鼠标队列使用 `unity-ui-interaction`；创建或布局 UGUI 使用 `unity-ui-interaction`。
4. 移动两个及以上文件时 使用 Unity CLI 的 `eval` 或临时 CliCommand  实现。

## 安全与调用规则

1. 禁止手写 UnitySkills URL、扫描 `8090-8100`，也禁止使用 `curl`、`Invoke-WebRequest`、`requests`、`urllib` 或其他方式直接拼装 HTTP/REST 请求。
2. 统一使用 `unity_skills.call_skill("技能名", 参数名=参数值)`。首次调用未知签名时，按底层模块说明、schema 或 dry-run 取得准确参数，不从描述猜测。
3. 操作两个及以上对象时，先查找 `*_batch` 入口；多步骤修改遵守底层 `unity-skills` 的计划、dry-run、权限、确认和回滚规则。
4. 修改场景内容时优先使用对应 UnitySkills 模块。未打开的目标场景先通过模块加载；不要直接编辑 `.unity` YAML。
5. 连接失败时先按 Unity 正在编译或 Domain Reload 的瞬时状态处理：优先遵循返回的 `retryAfterSeconds`；没有明确等待时间时，等待 5 秒后重试，最多重试 3 次。连续失败后再提示用户打开 `Window > UnitySkills > Start Server` 并停止；不要修改项目配置、扫描端口或绕过连接规则。

## 资产移动

移动一个 Unity 项目内代码文件或资产时，优先调用：

```python
unity_skills.call_skill(
    "asset_move",
    sourcePath=source_path,
    destinationPath=destination_path,
)
```

移动两个及以上文件时 使用 Unity CLI 的 `eval` 或临时 CliCommand  实现。注意创建文件夹,有的Unity API不会自动创建文件夹.

## 场景画面抓取

1. 普通 Unity Editor 场景画面抓取统一使用 `unity-skills`，并按画面来源加载 `scene` 或 `camera` 模块；不得仅因 `unity-cli-perception` 同样声明了截图能力，就自动改用 `unity command capture_scene_view`、`capture_game_view` 或 `screenshot`。
2. 最终合成的 Game View（全部相机与 UI，Play Mode 下为实时运行画面）使用 `scene_screenshot`；指定单个 Game Camera 的离屏渲染使用 `camera_screenshot`；Editor Scene View 使用 `camera_sceneview_screenshot`。
3. 只有用户明确要求使用官方 Unity CLI 时，才路由到 `unity-cli-perception`。UnitySkills 连接失败不构成自动改走 Unity CLI 的授权，仍按本 Skill 的连接失败规则重试并停止。
4. Graphon 相机拍摄继续使用 `graphon-workflow`；Unity Editor 之外的老 EXE 或其他游戏窗口使用 `windows-game-window-capture`，不得与 Unity Editor 截图入口混用。
5. 遵守目标截图 Skill 的保存路径契约：`scene_screenshot` 和 `camera_sceneview_screenshot` 的文件名不得包含路径分隔符，产物位于 `Assets/Screenshots/`；不得把裸的 `Output/...` 路径误认为项目根目录输出。

## C# 编译

C# 修改后必须使用 Unity 编译，不要用 `dotnet` 替代：

```powershell
python .agents/skills/unity-skills-guidelines/scripts/unity_compile.py
```

脚本会清理本轮 Console、触发 Unity 重编译、跨 Domain Reload 轮询状态并读取错误。成功标准是进程退出码为 `0` 且 `errors=0`。

## Unity Test Runner

只有用户明确要求测试时才运行测试。禁止使用 `test_run_by_name` 或直接调用 `test_run`；必须通过本 Skill 显式提供 `--filter` 或 `--all`：

```powershell
python .agents/skills/unity-skills-guidelines/scripts/unity_test.py --filter Xuexue.SomePackage.Tests
python .agents/skills/unity-skills-guidelines/scripts/unity_test.py --mode PlayMode --filter Xuexue.SomePackage.Tests
python .agents/skills/unity-skills-guidelines/scripts/unity_test.py --all
```

优先使用模块级或命名空间级过滤，不按单个测试逐条启动。脚本先发现并报告匹配测试，再启动唯一任务并轮询 `test_get_result`；测试产物遵守项目 `Output/Tests` 约定。
