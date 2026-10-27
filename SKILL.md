---
name: unity-skills-guidelines
description: "规定 UnitySkills 的连接、模块选择、安全调用和验证闭环。用于任何需要通过 UnitySkills 操作 Unity Editor 的任务，包括场景、资源、GameObject、组件、脚本、批量操作、实例连接、C# 编译、Unity Test Runner 和临时 Python 调用；作为使用规范层，与底层 unity-skills 功能模块共同触发。"
---

# UnitySkills 使用规范

先遵守本 Skill 的使用规则，再按任务加载 `unity-skills` 的相关功能或设计模块。底层 Skill 提供能力、schema 和权限协议；本 Skill 只规定 UnitySkills 的路由、稳定入口和验证闭环。

## 能力路由

1. 普通场景、资源、GameObject、组件、脚本和项目操作，加载 `.agents/skills/unity-skills` 下对应模块；不要在本 Skill 重复模块文档或猜测参数。
2. 当前项目 C# 编译使用 `.agents/skills/unity-skills-guidelines/scripts/unity_compile.py`；Unity Test Runner 使用 `.agents/skills/unity-skills-guidelines/scripts/unity_test.py`。
3. 运行时 UI 树检查、点击、拖动、滚轮和鼠标队列使用 `unity-ui-interaction`；创建或布局 UGUI 使用 `unity-ui-interaction`。
4. 移动或删除 Unity 项目资产时，唯一允许的入口是
   `unity command assets.file-operations.apply`。除该命令外，禁止使用任何其他 Unity Skill、任何其他
   Unity CLI 命令、任何 `AssetDatabase` API、临时 Command 或操作系统文件命令执行移动或删除。

## 安全与调用规则

1. 禁止手写 UnitySkills URL、扫描 `8090-8100`，也禁止使用 `curl`、`Invoke-WebRequest`、`requests`、`urllib` 或其他方式直接拼装 HTTP/REST 请求。
2. 统一使用 `unity_skills.call_skill("技能名", 参数名=参数值)`。首次调用未知签名时，按底层模块说明、schema 或 dry-run 取得准确参数，不从描述猜测。
3. 操作两个及以上对象时，先查找 `*_batch` 入口；多步骤修改遵守底层 `unity-skills` 的计划、dry-run、权限、确认和回滚规则。
4. 修改场景或资产时，先按下文「Unity 资产字段值修改」判断修改方式；结构修改使用对应 UnitySkills 模块，未打开的目标场景先通过模块加载。
5. 连接失败时先按 Unity 正在编译或 Domain Reload 的瞬时状态处理：优先遵循返回的 `retryAfterSeconds`；没有明确等待时间时，等待 5 秒后重试，最多重试 3 次。连续失败后再提示用户打开 `Window > UnitySkills > Start Server` 并停止；不要修改项目配置、扫描端口或绕过连接规则。

## Unity 资产字段值修改

1. 对 `.unity`、`.prefab`、`.asset` 等确认为文本 YAML 的 Unity 资产，仅修改已存在字段的确定值、不改变资产结构时，优先使用 `apply_patch` 直接编辑资产 YAML 文件，不通过 Unity API 完成赋值。
2. 新增或删除对象、组件、字段、数组元素，以及调整层级等结构修改，继续使用对应 UnitySkills 模块；不属于本章节的字段值修改规则。
3. 修改前准确定位目标对象和字段，确认字段含义与目标值；保留对象锚点、资产身份标识、原有文件格式及无关内容，不进行整文件重新序列化。
4. 修改后检查 diff，确认只有预期字段值发生变化；必要时通过 Unity 集中刷新或重载验证结果，不为字段赋值重复调用 Unity API。
5. 字段值修改的路由与验证方式以本章节为准，优先于底层 `unity-yaml-editing` 指引的「REST 优先／最后手段」及每次修改后必须重导入的规则；其余安全注意事项及项目约束仍适用。
6. 批量字段修改先集中完成文件编辑，再按需要集中刷新或重载验证，避免逐字段调用导入和保存 API。

## 资产文件操作

移动或删除 Unity 项目内代码文件、目录和资产时，统一调用该命令；一次请求可包含一项或多项操作。

传入 JSON 文件：

```powershell
unity command assets.file-operations.apply `
  --requestJson <操作参数.json> `
  --project-path <Unity项目根目录>
```

直接传入 JSON：

```powershell
unity command assets.file-operations.apply `
  --requestJson '{"operations":[{"type":"move","source":"Packages/example/Old","destination":"Packages/example/New"},{"type":"delete","source":"Packages/example/Obsolete"}]}' `
  --project-path <Unity项目根目录>
```

`requestJson` 支持内联 JSON，也支持绝对或项目根相对的 `.json` 文件路径。请求中的 `move`
操作填写 `source` 和 `destination`，`delete` 操作只填写 `source`；操作路径支持绝对路径或
相对于 Unity 项目根目录的路径。命令返回整批及逐项执行结果，
并在 `Dev/Logs/文件操作记录` 写入带时间戳的 JSON 记录。

# Unity 批量资产导入性能规范

- 设计批量资产处理时，应留意在内层循环逐文件调用同步
  `AssetDatabase.ImportAsset`、`AssetImporter.SaveAndReimport` 或
  `AssetDatabase.Refresh` 的成本，避免无意中产生大量重复导入。
- 如果业务允许，优先采用分阶段处理：先复制或生成一批文件，再集中刷新、配置
  Importer、创建引用资产和构建图集。
- 同一个文件的 Importer 设置应尽量一次写完，减少不必要的连续
  `SaveAndReimport`。
- 如果后续逻辑确实需要立即读取刚导入的对象，或必须逐文件确认导入结果，可以使用
  逐文件同步导入；实现时应确认这是必要条件，并尽量控制调用次数。
- 设计涉及大量 Unity 资产的 Editor 工具时，建议在实现前大致估算
  `ImportAsset`、`SaveAndReimport`、`Refresh` 和 `SaveAssets` 的调用规模，
  优先排查调用次数随文件数量快速增长的实现。

## 场景画面抓取

1. 普通 Unity Editor 场景画面抓取统一使用 `unity-skills`，并按画面来源加载 `scene` 或 `camera` 模块；不得仅因 `unity-cli-perception` 同样声明了截图能力，就自动改用 `unity command capture_scene_view`、`capture_game_view` 或 `screenshot`。
2. 最终合成的 Game View（全部相机与 UI，Play Mode 下为实时运行画面）使用 `scene_screenshot`；指定单个 Game Camera 的离屏渲染使用 `camera_screenshot`；Editor Scene View 使用 `camera_sceneview_screenshot`。
3. 只有用户明确要求使用官方 Unity CLI 时，才路由到 `unity-cli-perception`。UnitySkills 连接失败不构成自动改走 Unity CLI 的授权，仍按本 Skill 的连接失败规则重试并停止。
4. Unity Editor 之外的老 EXE 或其他游戏窗口使用 `windows-game-window-capture`，不得与 Unity Editor 截图入口混用。
5. 遵守目标截图 Skill 的保存路径契约：`scene_screenshot` 和 `camera_sceneview_screenshot` 的文件名不得包含路径分隔符，产物位于 `Assets/Screenshots/`；不得把裸的 `Output/...` 路径误认为项目根目录输出。

## C# 编译

C# 修改后必须使用 Unity 编译，不要用 `dotnet` 替代：

```powershell
python .agents/skills/unity-skills-guidelines/scripts/unity_compile.py
```

脚本先通过正式 `asset_refresh` 同步外部文件改动并等待其 job 终态；若本次刷新已完成真实编译，直接使用该次编译证据，否则才请求强制重编译。必须核验本次编译 job 的 compiled/success/domainLoaded，不能使用上一轮编译状态冒充成功。之后清理历史 Console 噪声并读取稳定错误状态，成功标准是进程退出码为 `0` 且 `errors=0`。刷新或编译请求超时不等于任务结束，不重复提交。

## Unity Test Runner

只有用户明确要求测试时才运行测试。禁止使用 `test_run_by_name` 或直接调用 `test_run`；必须通过本 Skill 显式提供 `--filter` 或 `--all`：

```powershell
python .agents/skills/unity-skills-guidelines/scripts/unity_test.py --filter Xuexue.SomePackage.Tests
python .agents/skills/unity-skills-guidelines/scripts/unity_test.py --mode PlayMode --filter Xuexue.SomePackage.Tests
python .agents/skills/unity-skills-guidelines/scripts/unity_test.py --all
```

优先使用模块级或命名空间级过滤，不按单个测试逐条启动。脚本先发现并报告匹配测试，再启动唯一任务并轮询 `test_get_result`；测试产物遵守项目 `Output/Tests` 约定。
