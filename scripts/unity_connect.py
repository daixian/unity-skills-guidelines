#!/usr/bin/env python
"""按项目 UnitySkills 使用规范连接当前本地项目。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def repo_root() -> Path:
    """从脚本路径向上发现当前 Unity 项目根目录。"""
    script_path = Path(__file__).resolve()
    for candidate in (script_path.parent, *script_path.parents):
        project_version = candidate / "ProjectSettings" / "ProjectVersion.txt"
        if project_version.is_file() and (candidate / "Assets").is_dir():
            return candidate

    raise FileNotFoundError(
        "无法从 Skill 脚本路径定位 Unity 项目根目录：" + str(script_path)
    )


def project_name() -> str:
    """返回本地 Unity 项目名，默认等于仓库目录名。"""
    return repo_root().name


def load_unity_skills():
    """导入本地 UnitySkills Python helper。"""
    helper_dir = repo_root() / ".agents" / "skills" / "unity-skills" / "scripts"
    sys.path.insert(0, str(helper_dir))
    import unity_skills

    return unity_skills


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="获取当前本地项目对应的 UnitySkills 客户端。",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument(
        "--target",
        default=None,
        help="可选 UnitySkills 项目实例的 name 或 id；默认当前本地项目。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON，便于其他脚本读取。",
    )
    parser.add_argument(
        "--export-env",
        action="store_true",
        help="输出 PowerShell 环境变量设置语句。",
    )
    return parser.parse_args()


def registry_path() -> Path:
    """返回 UnitySkills registry 文件路径。"""
    return Path.home() / ".unity_skills" / "registry.json"


def load_registry() -> Dict[str, Any]:
    """读取 UnitySkills registry；不存在或损坏时返回空字典。"""
    path = registry_path()
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def find_registry_entry(target: str) -> Optional[Dict[str, Any]]:
    """按项目路径、项目名或实例 id 匹配 registry 条目。"""
    normalized_root = str(repo_root()).lower()
    registry = load_registry()

    if target == project_name():
        for path, info in registry.items():
            if not isinstance(info, dict):
                continue

            entry_path = str(info.get("path") or path).lower()
            if entry_path == normalized_root:
                return dict(info, registryPath=path)

    for path, info in registry.items():
        if not isinstance(info, dict):
            continue

        if info.get("name") == target or info.get("id") == target:
            return dict(info, registryPath=path)

    return None


def build_client(unity_skills, target: str):
    """只通过 unity_skills helper 创建目标项目客户端。"""
    entry = find_registry_entry(target)
    if entry and entry.get("id"):
        return unity_skills.connect(target=entry["id"])

    return unity_skills.connect(target=target)


def activate_client(unity_skills, client) -> None:
    """把 helper 默认客户端切换为当前项目实例。"""
    unity_skills._default_client = client


def get_status(unity_skills) -> Dict[str, Any]:
    """通过 unity_skills helper 检查当前默认 UnitySkills 服务。"""
    if not unity_skills.health():
        return {"status": "offline"}

    status = unity_skills.get_server_status()
    return status if isinstance(status, dict) else {"status": str(status)}


def success_payload(target: str, client, status: Dict[str, Any]) -> Dict[str, Any]:
    """构建稳定的连接结果。"""
    entry = find_registry_entry(target)
    return {
        "success": True,
        "target": target,
        "projectName": project_name(),
        "url": client.url,
        "registry": entry,
        "status": status,
    }


def error_payload(target: str, error: Exception) -> Dict[str, Any]:
    """构建连接失败结果。"""
    return {
        "success": False,
        "target": target,
        "projectName": project_name(),
        "registryPath": str(registry_path()),
        "registry": find_registry_entry(target),
        "error": str(error),
        "hint": "请在对应 Unity 项目中打开 Window > UnitySkills > Start Server。",
    }


def print_json(payload: Dict[str, Any]) -> None:
    """以 UTF-8 友好格式输出 JSON。"""
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def print_text(payload: Dict[str, Any]) -> None:
    """输出面向命令行阅读的连接结果。"""
    if payload.get("success"):
        status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        registry = payload.get("registry") if isinstance(payload.get("registry"), dict) else {}
        print(f"UnitySkills 已连接：target={payload['target']} url={payload['url']}")
        print(f"  project: {registry.get('name', payload.get('projectName'))}")
        print(f"  id: {registry.get('id', '')}")
        print(f"  port: {registry.get('port', '')}")
        print(f"  unityVersion: {status.get('unityVersion', registry.get('unityVersion', ''))}")
        print(f"  skillsVersion: {status.get('version', '')}")
        return

    print(f"UnitySkills 连接失败：target={payload['target']}")
    print(f"  error: {payload.get('error', '')}")
    print(f"  hint: {payload.get('hint', '')}")


def print_export_env(payload: Dict[str, Any]) -> None:
    """输出 PowerShell 可执行的环境变量设置。"""
    if not payload.get("success"):
        print_text(payload)
        return

    print(f"$env:UNITY_SKILLS_TARGET='{payload['target']}'")
    print(f"$env:UNITY_SKILLS_URL='{payload['url']}'")


def connect_to_local_project(target: Optional[str] = None):
    """返回 UnitySkills 模块、目标客户端和状态信息。"""
    selected_target = target or project_name()
    unity_skills = load_unity_skills()
    client = build_client(unity_skills, selected_target)
    activate_client(unity_skills, client)
    status = get_status(unity_skills)
    if status.get("status") == "offline":
        raise RuntimeError("UnitySkills HttpServer is offline for the selected target.")

    return unity_skills, client, success_payload(selected_target, client, status)


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    target = args.target or project_name()

    try:
        _, _, payload = connect_to_local_project(target)
    except Exception as exception:  # noqa: BLE001 - 命令行诊断需要完整暴露 helper 错误。
        payload = error_payload(target, exception)

    if args.json:
        print_json(payload)
    elif args.export_env:
        print_export_env(payload)
    else:
        print_text(payload)

    return 0 if payload.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
