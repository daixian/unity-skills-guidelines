#!/usr/bin/env python
"""通过项目 UnitySkills helper 运行 Unity Test Runner。

本脚本实现 UnitySkills 使用规范中的单元测试流程：
- 使用较大的模块级或命名空间级 filter 一次运行一组测试；
- 使用 test_get_result 轮询返回的 job；
- 不按单个测试类或测试方法拆碎运行。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled", "canceled"}
SUCCESS_STATUS = "completed"


def repo_root() -> Path:
    """通过同目录连接模块定位当前 Unity 项目根目录。"""
    import unity_connect

    return unity_connect.repo_root()


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
        description="通过 unity_skills.call_skill('test_run', ...) 运行 Unity 单元测试。",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument(
        "--mode",
        default="EditMode",
        help="Unity Test Runner 模式，默认 EditMode。",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="可选 UnitySkills 项目实例的 name 或 id；默认当前本地项目。",
    )
    scope_group = parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument(
        "--filter",
        dest="test_filter",
        help="要运行的模块级、命名空间级或明确测试过滤条件。",
    )
    scope_group.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="显式运行所选模式下的全部测试。",
    )
    parser.add_argument(
        "--timeout",
        default=300.0,
        type=float,
        help="等待测试任务完成的最大秒数，默认 300。",
    )
    parser.add_argument(
        "--interval",
        default=5.0,
        type=float,
        help="两次 test_get_result 轮询之间的秒数，默认 5。",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.run_all:
        args.test_filter = ""
    return args


def status_of(result: Optional[Dict[str, Any]]) -> str:
    """标准化 UnitySkills 返回的状态值。"""
    if not isinstance(result, dict):
        return ""

    return str(result.get("status", "")).strip().lower()


def print_raw_payload(title: str, payload: Any) -> None:
    """使用稳定且 UTF-8 友好的格式输出原始返回。"""
    print(title)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def summarize_result(result: Dict[str, Any]) -> str:
    """创建紧凑的测试结果摘要。"""
    total = result.get("totalTests", result.get("total", "?"))
    passed = result.get("passedTests", result.get("passed", "?"))
    failed = result.get("failedTests", result.get("failed", "?"))
    skipped = result.get("skippedTests", result.get("skipped", "?"))
    elapsed = result.get("elapsedSeconds", "?")
    return (
        f"status={status_of(result) or '?'} "
        f"passed={passed}/{total} failed={failed} skipped={skipped} elapsed={elapsed}s"
    )


def get_result_value(result: Dict[str, Any], *keys: str, default: Any = "?") -> Any:
    """按候选字段名读取测试结果值。"""
    for key in keys:
        if key in result and result[key] is not None:
            return result[key]

    return default


def print_result_details(result: Dict[str, Any], job_id: str, mode: str, test_filter: str) -> None:
    """打印 UnitySkills 当前可返回的完整测试结果摘要。"""
    print("测试结束：")
    print(f"  jobId: {job_id}")
    print(f"  mode: {mode}")
    print(f"  filter: {test_filter}")
    print(f"  status: {status_of(result) or get_result_value(result, 'status')}")
    print(f"  success: {get_result_value(result, 'success', default=False)}")
    print(f"  resultSummary: {get_result_value(result, 'resultSummary', default='')}")
    print("  counts:")
    print(f"    total: {get_result_value(result, 'totalTests', 'total')}")
    print(f"    passed: {get_result_value(result, 'passedTests', 'passed')}")
    print(f"    failed: {get_result_value(result, 'failedTests', 'failed')}")
    print(f"    skipped: {get_result_value(result, 'skippedTests', 'skipped')}")
    print(f"    inconclusive: {get_result_value(result, 'inconclusiveTests', 'inconclusive')}")
    print(f"    other: {get_result_value(result, 'otherTests', 'other')}")
    print(f"  elapsedSeconds: {get_result_value(result, 'elapsedSeconds', 'elapsed')}")
    print(f"  error: {get_result_value(result, 'error', default='')}")
    print_failed_names(result, show_empty=True)
    print_raw_payload("UnitySkills 原始返回：", result)
    print_test_results_xml_report()


def read_project_setting(name: str) -> Optional[str]:
    """从 ProjectSettings.asset 读取简单的 PlayerSettings 字段。"""
    settings_path = repo_root() / "ProjectSettings" / "ProjectSettings.asset"
    if not settings_path.exists():
        return None

    pattern = re.compile(rf"^\s*{re.escape(name)}:\s*(.*)\s*$")
    for line in settings_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip().strip("\"'")

    return None


def resolve_test_results_xml_path() -> Path:
    """按 Unity Windows persistentDataPath 规则推导 TestResults.xml 路径。"""
    company_name = read_project_setting("companyName") or "DefaultCompany"
    product_name = read_project_setting("productName") or repo_root().name
    user_profile = Path(os.environ.get("USERPROFILE") or str(Path.home()))
    return user_profile / "AppData" / "LocalLow" / company_name / product_name / "TestResults.xml"


def print_test_results_xml_report() -> None:
    """自动读取并打印 Unity 生成的 NUnit XML 测试报告。"""
    report_path = resolve_test_results_xml_path()
    print("TestResults.xml：")
    print(f"  path: {report_path}")

    if not report_path.exists():
        print("  status: 未找到报告文件")
        return

    try:
        stat = report_path.stat()
        root = ET.parse(report_path).getroot()
    except Exception as error:  # noqa: BLE001 - 这里只做诊断输出，不影响测试退出码。
        print(f"  status: 解析失败：{error}")
        return

    print(f"  lastWriteTime: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))}")
    print("  summary:")
    for key in (
        "result",
        "total",
        "passed",
        "failed",
        "inconclusive",
        "skipped",
        "asserts",
        "duration",
        "start-time",
        "end-time",
    ):
        print(f"    {key}: {root.attrib.get(key, '')}")

    test_cases = list(root.iter("test-case"))
    print(f"  testCases: {len(test_cases)}")
    for test_case in test_cases:
        result = test_case.attrib.get("result", "")
        duration = test_case.attrib.get("duration", "")
        full_name = test_case.attrib.get("fullname", test_case.attrib.get("name", ""))
        print(f"    [{result}] {duration}s {full_name}")

        if result and result != "Passed":
            print_failure_detail(test_case)


def print_failure_detail(test_case: ET.Element) -> None:
    """打印 XML 中失败用例的断言消息和堆栈。"""
    failure = test_case.find("failure")
    if failure is None:
        return

    message = failure.findtext("message", default="").strip()
    stack_trace = failure.findtext("stack-trace", default="").strip()
    if message:
        print("      message:")
        print_indented_text(message, "        ")
    if stack_trace:
        print("      stack-trace:")
        print_indented_text(stack_trace, "        ")


def print_indented_text(text: str, indent: str) -> None:
    """按行缩进打印多行文本。"""
    for line in text.splitlines():
        print(indent + line)


def extract_test_name(test_item: Any) -> str:
    """从结构不固定的发现结果中提取测试名称。"""
    if isinstance(test_item, str):
        return test_item

    if isinstance(test_item, dict):
        for key in ("fullName", "name", "testName", "id"):
            value = test_item.get(key)
            if value:
                return str(value)

    return str(test_item)


def filter_tests(tests: Iterable[Any], test_filter: str) -> List[str]:
    """返回包含指定 filter 文本的已发现测试名称。"""
    names = [extract_test_name(test) for test in tests]
    if not test_filter:
        return names

    return [name for name in names if test_filter in name]


def discover_tests(unity_skills, mode: str, test_filter: str) -> bool:
    """发现测试并报告指定 filter 命中的数量。"""
    started = unity_skills.call_skill("test_discover_start", testMode=mode)
    job_id = started.get("jobId") if isinstance(started, dict) else None
    if not job_id:
        print("测试发现启动失败。")
        print_raw_payload("UnitySkills 原始返回：", {"discover_start": started})
        return False

    deadline = time.monotonic() + 120.0
    result: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = unity_skills.call_skill("test_discover_get_result", jobId=job_id, limit=10000)
        if status_of(result) in TERMINAL_STATUSES:
            break
        time.sleep(2.0)

    current_status = status_of(result)
    if current_status not in TERMINAL_STATUSES:
        print(f"测试发现等待超时：jobId={job_id}")
        print_raw_payload("UnitySkills 原始返回：", {"discover_start": started, "lastResult": result})
        return False

    if current_status != SUCCESS_STATUS:
        print(f"测试发现失败：jobId={job_id} status={current_status or '?'}")
        print_raw_payload("UnitySkills 原始返回：", {"discover_start": started, "result": result})
        return False

    tests = result.get("tests", []) if isinstance(result, dict) else []
    matches = filter_tests(tests, test_filter)
    print(f"发现测试：总数 {len(tests)}，filter='{test_filter}' 命中 {len(matches)}。")
    for name in matches:
        print("  " + name)

    return True


def run_tests(unity_skills, args: argparse.Namespace) -> int:
    """启动一次较大范围的 Unity 测试并轮询结果。"""
    started = unity_skills.call_skill(
        "test_run",
        testMode=args.mode,
        filter=args.test_filter,
    )
    job_id = started.get("jobId") if isinstance(started, dict) else None
    if not job_id:
        print("测试启动失败：UnitySkills 没有返回 jobId。")
        print_raw_payload("UnitySkills 原始返回：", {"test_run": started})
        return 2

    print(f"测试已启动：jobId={job_id} mode={args.mode} filter={args.test_filter}")
    deadline = time.monotonic() + max(1.0, args.timeout)
    last_result: Dict[str, Any] = {}

    while time.monotonic() < deadline:
        last_result = unity_skills.call_skill("test_get_result", jobId=job_id)
        current_status = status_of(last_result)
        if current_status in TERMINAL_STATUSES:
            print_result_details(last_result, job_id, args.mode, args.test_filter)

            return 0 if current_status == SUCCESS_STATUS and not has_failures(last_result) else 1

        print("测试运行中：" + summarize_result(last_result))
        time.sleep(max(0.5, args.interval))

    print(f"测试等待超时：jobId={job_id} timeout={args.timeout}s")
    if last_result:
        print("最后一次结果：")
        print_result_details(last_result, job_id, args.mode, args.test_filter)
    print_raw_payload("UnitySkills 原始返回：", {"jobId": job_id, "lastResult": last_result})
    return 3


def has_failures(result: Dict[str, Any]) -> bool:
    """判断测试结果是否包含失败测试。"""
    failed = result.get("failedTests", result.get("failed", 0))
    try:
        return int(failed) > 0
    except (TypeError, ValueError):
        return bool(failed)


def print_failed_names(result: Dict[str, Any], show_empty: bool = False) -> None:
    """在存在失败测试时打印测试名称。"""
    failed_names = result.get("failedTestNames", result.get("failedNames", []))
    if not failed_names:
        if show_empty:
            print("  failedTestNames: []")
        return

    print("  failedTestNames:")
    for name in failed_names:
        print("    " + str(name))


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    unity_skills = connect_unity_skills(args.target)

    if not discover_tests(
        unity_skills,
        args.mode,
        args.test_filter,
    ):
        return 2

    return run_tests(unity_skills, args)


if __name__ == "__main__":
    raise SystemExit(main())
