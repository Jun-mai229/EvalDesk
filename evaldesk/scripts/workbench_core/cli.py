"""Command-line routing for EvalDesk scripts."""
from __future__ import annotations

import argparse
import sys

from .common import DEFAULT_RANGE, WorkbenchError
from .environment import command_doctor
from .launcher import command_launch
from .lifecycle import command_stop
from .self_test import command_self_test
from .server import command_serve
from .template import command_diagnose, command_prepare
from .writeback import command_commit


def add_assignment_arguments(command: argparse.ArgumentParser) -> None:
    assignment = command.add_mutually_exclusive_group(required=True)
    assignment.add_argument("--annotator", help="只载入分配给该标注人的任务")
    assignment.add_argument(
        "--include-unassigned",
        action="store_true",
        help="仅载入标注人为空的任务",
    )


def add_prepare_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--url", required=True, help="飞书表格或 Wiki 链接")
    command.add_argument("--sheet-id", help="子表 ID；默认从 URL 的 sheet 参数读取")
    command.add_argument("--target-group", help="有多个模型或评分区时，指定表头原始组名")
    command.add_argument("--aliases", help="自定义 JSON 字段别名文件")
    command.add_argument("--blind", action="store_true", help="先独立评分并本地留档，再显示机评和历史对照")
    add_assignment_arguments(command)
    command.add_argument("--range", default=DEFAULT_RANGE, help="读取范围")
    command.add_argument(
        "--validation-end-row",
        type=int,
        default=20,
        help="扫描数据验证的末行",
    )
    command.add_argument("--session", help="会话输出目录")
    command.add_argument("--force", action="store_true", help="覆盖非空会话目录")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="从飞书评测模板生成本地评分工作台，并安全预览或回写结果"
    )
    subparsers = root.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="只读飞书并创建本地会话")
    add_prepare_arguments(prepare)
    prepare.set_defaults(handler=command_prepare)

    diagnose = subparsers.add_parser("diagnose", help="只读分析模板兼容性和字段映射")
    diagnose.add_argument("--url", required=True, help="飞书表格或 Wiki 链接")
    diagnose.add_argument("--sheet-id", help="子表 ID；默认从 URL 的 sheet 参数读取")
    diagnose.add_argument("--target-group", help="有多个模型或评分区时，指定表头原始组名")
    diagnose.add_argument("--aliases", help="自定义 JSON 字段别名文件")
    diagnose.add_argument("--range", default=DEFAULT_RANGE, help="读取范围")
    diagnose.set_defaults(handler=command_diagnose)

    doctor = subparsers.add_parser("doctor", help="检查本地运行环境和飞书访问")
    doctor.add_argument("--url", help="可选；同时验证飞书登录和目标表访问")
    doctor.add_argument("--sheet-id", help="链接不含 sheet 参数时显式指定")
    doctor.add_argument("--session-root", help="会话目录根路径")
    doctor.add_argument("--port", type=int, default=4180, help="首选本地端口")
    doctor.add_argument(
        "--no-browser-check", action="store_true", help="跳过默认浏览器检查"
    )
    doctor.set_defaults(handler=command_doctor)

    launch = subparsers.add_parser("launch", help="环境检查后创建会话并启动工作台")
    add_prepare_arguments(launch)
    launch.add_argument("--port", type=int, default=4180, help="首选本地端口")
    launch.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    launch.set_defaults(handler=command_launch)

    serve = subparsers.add_parser("serve", help="启动本地评分页面")
    serve.add_argument("--session", required=True, help="会话目录")
    serve.add_argument(
        "--port", type=int, default=4180, help="首选端口；占用时自动递增"
    )
    serve.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    serve.set_defaults(handler=command_serve)

    stop = subparsers.add_parser("stop", help="安全停止指定会话的本地服务")
    stop.add_argument("--session", required=True, help="会话目录")
    stop.set_defaults(handler=command_stop)

    commit = subparsers.add_parser("commit", help="生成回写预览；--apply 才实际写入")
    commit.add_argument("--session", required=True, help="会话目录")
    commit.add_argument("--apply", action="store_true", help="实际写入并回读校验")
    commit.set_defaults(handler=command_commit)

    self_test = subparsers.add_parser("self-test", help="运行离线自检")
    self_test.set_defaults(handler=command_self_test)
    return root


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except WorkbenchError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def run_subcommand(command: str, argv: list[str] | None = None) -> int:
    forwarded = list(sys.argv[1:] if argv is None else argv)
    return run([command, *forwarded])


def main() -> int:
    return run()
