#!/usr/bin/env python
"""通过项目 UnitySkills helper 编译 Unity 脚本并读取错误。

本脚本实现 UnitySkills 使用规范中的 Unity 编译流程：
- 清空控制台；
- 请求 Unity 脚本重新编译；
- 轮询 debug_get_errors 和 debug_check_compilation，直到 Unity 状态稳定。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TRANSIENT_ERROR_FRAGMENTS = (
    "unity is compiling or reloading scripts",
    "invalid json response",
    "cannot connect",
    "timed out",
    "connection",
    "timeout",
)

# 只屏蔽 UnitySkills HTTP 服务在 Domain Reload 期间产生的通信噪声。
# 业务代码即使包含相同异常文本，只要调用栈不来自 SkillsHttpServer，就仍会作为编译错误报告。
UNITY_SKILLS_HTTP_SERVER_FRAGMENTS = (
    "unityskills.skillshttpserver",
    "packages/com.besty.unity-skills/editor/skills/skillshttpserver.cs",
)

TRANSIENT_HTTP_SERVER_ERROR_FRAGMENTS = (
    "fallback response failed",
    "thread was being aborted",
    "threadabortexception",
    "request was aborted",
    "operation has been aborted",
    "objectdisposedexception",
    "cannot access a disposed object",
    "httplistenerexception",
    "response was closed",
    "response has been closed",
    "client disconnected",
    "connection reset",
    "forcibly closed",
    "broken pipe",
)


def connect_unity_skills(target: Optional[str] = None):
    """获取当前项目的 UnitySkills helper。"""
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import unity_connect

    unity_skills, _, _ = unity_connect.connect_to_local_project(target)
    return unity_skills


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="通过 unity_skills helper 调用编译 Unity 脚本。",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument(
        "--target",
        default=None,
        help="可选 UnitySkills 项目实例的 name 或 id；默认当前本地项目。",
    )
    parser.add_argument(
        "--timeout",
        default=180.0,
        type=float,
        help="等待编译稳定的最大秒数，默认 180。",
    )
    parser.add_argument(
        "--interval",
        default=5.0,
        type=float,
        help="两次错误轮询之间的秒数，默认 5。",
    )
    parser.add_argument(
        "--limit",
        default=200,
        type=int,
        help="最多读取的错误条目数，默认 200。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出完整 JSON，而不是简短摘要。",
    )
    return parser.parse_args()


def print_json(payload: Dict[str, Any]) -> None:
    """使用稳定且 UTF-8 友好的格式输出 JSON。"""
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def is_connection_failure(value: Any) -> bool:
    """判断 helper 结果是否表示无法访问 UnitySkills 实例。"""
    if value is True:
        return False

    text = str(value)
    return "No Unity instance found" in text or "Cannot connect" in text


def is_transient_result(result: Any) -> bool:
    """判断 UnitySkills 响应是否属于重载期间可重试结果。"""
    if not isinstance(result, dict):
        return False

    if result.get("success") is True:
        return False

    text = json.dumps(result, ensure_ascii=False, default=str).lower()
    return any(fragment in text for fragment in TRANSIENT_ERROR_FRAGMENTS)


def normalize_log_text(log: Any) -> str:
    """把 Console 日志转换为适合稳定匹配的规范化文本。"""
    if isinstance(log, dict):
        text = json.dumps(log, ensure_ascii=False, default=str)
    else:
        text = str(log)

    return text.replace("\\", "/").lower()


def is_transient_unityskills_server_error(log: Any) -> bool:
    """判断日志是否为 UnitySkills HTTP 服务重载期间产生的瞬时错误。"""
    text = normalize_log_text(log)
    has_server_origin = any(
        fragment in text for fragment in UNITY_SKILLS_HTTP_SERVER_FRAGMENTS
    )
    if not has_server_origin:
        return False

    return any(
        fragment in text for fragment in TRANSIENT_HTTP_SERVER_ERROR_FRAGMENTS
    )


def filter_transient_server_errors(
    errors: Any,
) -> Tuple[Any, int]:
    """过滤 UnitySkills 重载噪声，并返回过滤结果与被屏蔽数量。"""
    if not isinstance(errors, dict) or errors.get("success") is not True:
        return errors, 0

    logs = errors.get("logs")
    if not isinstance(logs, list):
        return errors, 0

    kept_logs: List[Any] = []
    suppressed_count = 0
    for log in logs:
        if is_transient_unityskills_server_error(log):
            suppressed_count += 1
        else:
            kept_logs.append(log)

    if suppressed_count == 0:
        return errors, 0

    filtered_errors = dict(errors)
    filtered_errors["logs"] = kept_logs
    filtered_errors["count"] = len(kept_logs)
    return filtered_errors, suppressed_count


def is_compiling(compilation: Any) -> bool:
    """判断 Unity 是否仍在编译或更新。"""
    if not isinstance(compilation, dict):
        return False

    return bool(compilation.get("isCompiling") or compilation.get("isUpdating"))


def error_count(errors: Any) -> Optional[int]:
    """从 debug_get_errors 结果中提取 Unity 控制台错误数量。"""
    if not isinstance(errors, dict) or errors.get("success") is not True:
        return None

    count = errors.get("count")
    try:
        return int(count)
    except (TypeError, ValueError):
        logs = errors.get("logs", [])
        return len(logs) if isinstance(logs, list) else None


def summarize_errors(errors: Dict[str, Any], max_items: int = 10) -> None:
    """打印紧凑的编译错误列表。"""
    logs = errors.get("logs", [])
    if not isinstance(logs, list) or not logs:
        return

    print("编译错误：")
    for index, log in enumerate(logs[:max_items], start=1):
        if isinstance(log, dict):
            message = log.get("message", log)
            file_name = log.get("file")
            line = log.get("line")
            location = f" ({file_name}:{line})" if file_name else ""
            print(f"  {index}. {message}{location}")
        else:
            print(f"  {index}. {log}")

    if len(logs) > max_items:
        print(f"  ... 省略 {len(logs) - max_items} 条")


def check_health(unity_skills) -> Any:
    """检查当前 UnitySkills 实例是否可用。"""
    return unity_skills.health()


def run_compile(unity_skills, args: argparse.Namespace) -> int:
    """运行 Unity 编译流程并返回进程退出码。"""
    payload: Dict[str, Any] = {
        "target": args.target,
        "timeout": args.timeout,
        "limit": args.limit,
    }

    try:
        payload["health"] = check_health(unity_skills)
    except Exception as exception:
        payload["health_error"] = str(exception)
        print_missing_server(payload, args.json)
        return 2

    if is_connection_failure(payload.get("health")):
        print_missing_server(payload, args.json)
        return 2

    payload["console_clear"] = unity_skills.call_skill("console_clear")
    payload["debug_force_recompile"] = unity_skills.call_skill("debug_force_recompile")

    deadline = time.monotonic() + max(1.0, args.timeout)
    last_errors: Any = {}
    last_compilation: Any = {}
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        time.sleep(max(0.5, args.interval))
        raw_errors = unity_skills.call_skill("debug_get_errors", limit=args.limit)
        last_compilation = unity_skills.call_skill("debug_check_compilation")
        payload["lastAttempt"] = attempt
        payload["debug_check_compilation"] = last_compilation

        if is_transient_result(raw_errors) or is_transient_result(last_compilation):
            continue

        if is_compiling(last_compilation):
            continue

        last_errors, suppressed_count = filter_transient_server_errors(raw_errors)
        payload["debug_get_errors"] = last_errors
        if suppressed_count:
            payload["suppressedUnitySkillsNoiseCount"] = suppressed_count

        count = error_count(last_errors)
        if count is None:
            continue

        if args.json:
            print_json(payload)
        elif count == 0:
            print(f"Unity 编译通过：errors=0 attempts={attempt}")
        else:
            print(f"Unity 编译失败：errors={count} attempts={attempt}")
            summarize_errors(last_errors)

        return 0 if count == 0 else 1

    payload["debug_get_errors"] = last_errors
    payload["debug_check_compilation"] = last_compilation
    if args.json:
        print_json(payload)
    else:
        print(f"Unity 编译等待超时：timeout={args.timeout}s")
        if last_errors:
            print("最后一次 debug_get_errors：")
            print_json(last_errors if isinstance(last_errors, dict) else {"result": last_errors})
        if last_compilation:
            print("最后一次 debug_check_compilation：")
            print_json(last_compilation if isinstance(last_compilation, dict) else {"result": last_compilation})

    return 3


def print_missing_server(payload: Dict[str, Any], json_output: bool) -> None:
    """打印 UnitySkills 服务缺失时的标准提示。"""
    if json_output:
        print_json(payload)
        return

    print("无法连接 UnitySkills。请在 Unity 中打开 Window > UnitySkills > Start Server 后重试。")
    if payload:
        print_json(payload)


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    unity_skills = connect_unity_skills(args.target)
    return run_compile(unity_skills, args)


if __name__ == "__main__":
    raise SystemExit(main())
