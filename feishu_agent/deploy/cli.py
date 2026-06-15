import argparse
from typing import List, Optional

from feishu_agent.config import Settings
from feishu_agent.deploy.github_sync import check_remote_version, push_to_github, sync_from_github
from feishu_agent.deploy.rollback import list_deploy_history, rollback_to_version


def _print_notes(notes: List[str]) -> None:
    for note in notes:
        print(f"- {note}")


def main(argv: Optional[List[str]] = None, settings: Optional[Settings] = None) -> int:
    if settings is None:
        raise ValueError("settings is required")
    resolved_settings = settings
    parser = argparse.ArgumentParser(prog="python -m feishu_agent.deploy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="检查本地和上游版本")

    sync_parser = subparsers.add_parser("sync", help="生成同步计划")
    sync_parser.add_argument("--no-dry-run", action="store_true", help="标记为非 dry-run，仅输出计划状态")

    push_parser = subparsers.add_parser("push", help="生成推送计划")
    push_parser.add_argument("--no-dry-run", action="store_true", help="标记为非 dry-run，仅输出计划状态")

    subparsers.add_parser("history", help="查看部署历史")

    rollback_parser = subparsers.add_parser("rollback", help="查找回滚目标")
    rollback_parser.add_argument("version", help="要回滚到的版本号")

    args = parser.parse_args(argv)

    if args.command == "check":
        result = check_remote_version(settings=resolved_settings)
        print(f"action: {result.action}")
        print(f"local: {result.local_version}")
        print(f"remote: {result.remote_version}")
        if result.notes:
            _print_notes(result.notes)
        return 0 if result.ok else 1

    if args.command == "sync":
        result = sync_from_github(dry_run=not args.no_dry_run, settings=resolved_settings)
        print(f"action: {result.action}")
        print(f"local: {result.local_version}")
        print(f"remote: {result.remote_version}")
        _print_notes(result.notes)
        return 0 if result.ok else 1

    if args.command == "push":
        result = push_to_github(dry_run=not args.no_dry_run, settings=resolved_settings)
        print(f"action: {result.action}")
        print(f"local: {result.local_version}")
        print(f"remote: {result.remote_version}")
        _print_notes(result.notes)
        return 0 if result.ok else 1

    if args.command == "history":
        history = list_deploy_history(settings=resolved_settings)
        if not history:
            print("no deploy history")
            return 0
        for record in history:
            print(f"{record.version} | {record.deployed_at} | {record.notes}")
        return 0

    if args.command == "rollback":
        print(rollback_to_version(args.version, settings=resolved_settings))
        return 0

    return 0
