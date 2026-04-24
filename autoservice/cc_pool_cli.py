#!/usr/bin/env python3
"""
CC Pool CLI — 查看和管理 Claude Code 实例池。

用法：
  # 查看池状态
  uv run python -m autoservice.cc_pool_cli status

  # 启动池并查看状态（池未运行时会启动）
  uv run python -m autoservice.cc_pool_cli start

  # 关闭池
  uv run python -m autoservice.cc_pool_cli stop

  # 查看日志（最近 50 行）
  uv run python -m autoservice.cc_pool_cli logs

  # 查看日志（实时跟踪）
  uv run python -m autoservice.cc_pool_cli logs -f
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# If the snapshot's updated_at is older than this, the writer has likely died
# (e.g. gateway was force-killed on Windows, which bypasses the shutdown hook).
STALE_THRESHOLD_SECONDS = 30


def cmd_status():
    """显示池状态（如果有运行中的池实例）。"""
    status_file = Path.cwd() / ".autoservice" / "cc_pool_status.json"
    if not status_file.exists():
        print("[cc-pool] 状态文件不存在 — 池未运行或未写入状态")
        print(f"  路径: {status_file}")
        print("\n  提示: 运行集成测试或启动池后，状态文件会自动生成")
        return

    data = json.loads(status_file.read_text(encoding="utf-8"))
    stale_age = _snapshot_age_seconds(data)
    if stale_age is not None and stale_age > STALE_THRESHOLD_SECONDS:
        print(f"[cc-pool] !! 状态文件已 {int(stale_age)}s 未更新 — "
              f"写入者可能已终止（被强制 kill？）")
        print("  下面是最后一次快照：\n")
    _print_status(data)


def _snapshot_age_seconds(data: dict) -> float | None:
    ts = data.get("updated_at")
    if not ts:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return None


def cmd_start():
    """启动池并显示状态。"""
    asyncio.run(_async_start())


async def _async_start():
    from autoservice.cc_pool import get_pool, load_pool_config

    print("[cc-pool] 启动实例池...")
    config = load_pool_config()
    pool = await get_pool(config)

    # pool now maintains .autoservice/cc_pool_status.json itself (every 5s);
    # we just print the initial snapshot and wait for Ctrl+C.
    _print_status(pool.status())

    print("\n[cc-pool] 池已启动，按 Ctrl+C 关闭")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        from autoservice.cc_pool import shutdown_pool
        await shutdown_pool()
        print("\n[cc-pool] 池已关闭")


def cmd_stop():
    """关闭池。"""
    asyncio.run(_async_stop())


async def _async_stop():
    from autoservice.cc_pool import shutdown_pool
    await shutdown_pool()
    print("[cc-pool] 池已关闭")


def cmd_logs(follow: bool = False):
    """查看池日志。"""
    log_file = Path.cwd() / ".autoservice" / "logs" / "cc_pool.log"
    if not log_file.exists():
        print(f"[cc-pool] 日志文件不存在: {log_file}")
        return

    if follow:
        import subprocess
        try:
            subprocess.run(["tail", "-f", str(log_file)])
        except FileNotFoundError:
            # Windows fallback
            print(f"[cc-pool] 请手动查看: {log_file}")
            print("  Windows: Get-Content -Wait .autoservice/logs/cc_pool.log")
    else:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        for line in lines[-50:]:
            print(line)
        print(f"\n  ({len(lines)} 总行数，显示最后 50 行)")
        print(f"  文件: {log_file}")


def cmd_sessions():
    """显示当前 sticky session 绑定。"""
    status_file = Path.cwd() / ".autoservice" / "cc_pool_status.json"
    if not status_file.exists():
        print("[cc-pool] 状态文件不存在 — 池未运行")
        return

    data = json.loads(status_file.read_text(encoding="utf-8"))
    bindings = data.get("sticky_bindings", [])
    if not bindings:
        print("[cc-pool] 无活跃会话绑定")
        return

    print(f"\n  Sticky Sessions ({len(bindings)}):")
    print(f"  {'Key':<25} {'Instance':<10} {'Accesses':<10} {'Idle(s)':<10} {'Bound(s)':<10}")
    print(f"  {'─'*24} {'─'*9} {'─'*9} {'─'*9} {'─'*9}")
    for b in bindings:
        print(f"  {b['key']:<25} {b['instance_id']:<10} {b['access_count']:<10} "
              f"{b['idle_seconds']:<10} {b.get('bound_seconds', '?'):<10}")
    print()


def _print_status(data: dict):
    """格式化输出池状态。"""
    print(f"\n{'─' * 50}")
    print(f"  CC Pool Status")
    print(f"{'─' * 50}")
    print(f"  运行状态:   {'● 运行中' if data.get('started') else '○ 未运行'}")
    print(f"  总实例数:   {data.get('total', 0)} / {data.get('max_size', '?')}")
    print(f"  可用:       {data.get('available', 0)}")
    print(f"  已借出:     {data.get('checked_out', 0)}")

    sticky = data.get("sticky", 0)
    if sticky:
        print(f"  会话绑定:   {sticky}")

    if data.get("updated_at"):
        print(f"  更新时间:   {data['updated_at']}")

    instances = data.get("instances", [])
    if instances:
        print(f"\n  {'ID':<10} {'健康':<6} {'查询数':<8} {'存活(s)':<10}")
        print(f"  {'─'*10} {'─'*5} {'─'*7} {'─'*9}")
        for inst in instances:
            health = "+" if inst.get("healthy") else "-"
            print(f"  {inst['id']:<10} {health:<6} {inst['query_count']:<8} {inst['age_seconds']:<10}")

    bindings = data.get("sticky_bindings", [])
    if bindings:
        print(f"\n  Sticky Sessions:")
        print(f"  {'Key':<25} {'Instance':<10} {'Accesses':<10} {'Idle(s)':<10}")
        print(f"  {'─'*24} {'─'*9} {'─'*9} {'─'*9}")
        for b in bindings:
            print(f"  {b['key']:<25} {b['instance_id']:<10} {b['access_count']:<10} {b['idle_seconds']:<10}")
    print(f"{'─' * 50}\n")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return

    cmd = args[0]
    if cmd == "status":
        cmd_status()
    elif cmd == "start":
        cmd_start()
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "logs":
        follow = "-f" in args or "--follow" in args
        cmd_logs(follow=follow)
    elif cmd == "sessions":
        cmd_sessions()
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: status, start, stop, logs, sessions")
        sys.exit(1)


if __name__ == "__main__":
    main()
