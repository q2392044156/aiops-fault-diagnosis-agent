"""实现 `python -m` 命令行入口和参数分发。"""

import argparse
import json
import logging
import sys

import uvicorn

from .api import create_app
from .benchmark import run as run_benchmark
from .config import load
from .incident_cli import run as run_incident
from .release import RuleDetector
from .runtime import ServiceRuntime


def main(argv=None):
    """命令行总分发入口。所有子命令共享同一套配置加载逻辑，
    但各自按需装配不同的 ServiceRuntime role，避免 API 进程无谓加载模型。"""

    argv = list(sys.argv[1:] if argv is None else argv)

    # ---------- 特殊分支：incident 子命令不走 argparse ----------
    # incident 是一个独立的 CLI 工具（非服务生命周期管理），参数格式与其他子命令不同，
    # 因此在 argparse 初始化之前单独拦截，转发给 incident_cli.run 处理。
    if argv and argv[0] == "incident":
        print(json.dumps(run_incident(argv[1:]), ensure_ascii=False, default=str, indent=2))
        return

    # ---------- 构建 argparse 解析器 ----------
    # 5 个基础子命令统一要求 --config，benchmark 额外提供 --suite 选择测试套件。
    parser = argparse.ArgumentParser(description="W9 controlled AIOps diagnosis service")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "verify", "serve", "worker", "worker-health"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
    benchmark = sub.add_parser("benchmark")
    benchmark.add_argument("--config", required=True)
    benchmark.add_argument("--suite", choices=("e1", "e2", "e3", "e4", "all"),
                           default="all")
    args = parser.parse_args(argv)

    # 统一加载配置（所有子命令共用）
    cfg = load(args.config)

    # ---------- init：初始化数据库 ----------
    # 创建 SQLite 文件和 schema（version=4）。role 用默认 api（不加载检测器明细），
    # 因为只需要 Database 的建表能力，不需要任何推理组件。
    if args.command == "init":
        runtime = ServiceRuntime(cfg, load_model=False)
        print(json.dumps({"database": str(runtime.db.path), "schema_version": 4},
                         ensure_ascii=False, indent=2))

    # ---------- verify：校验运行时装配 ----------
    # 检测器是纯规则实现，无外部制品；这里只做一次装配自检，
    # 生产部署的门禁步骤，verify 通过后才允许 serve/worker 启动。
    elif args.command == "verify":
        detector = RuleDetector(cfg)
        print(json.dumps({"verified": True, "release_id": detector.manifest["release_id"],
                          "model_id": detector.manifest["model_id"]},
                         ensure_ascii=False, indent=2))

    # ---------- serve：启动 API 服务 ----------
    # 调用 create_app(cfg) 构建 FastAPI 应用，uvicorn 以单 worker 模式启动
    # （进程模型下多 worker 会导致 SQLite 锁冲突）。
    # API 进程不加载模型推理组件，仅负责路由和数据库交互。
    elif args.command == "serve":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        app = create_app(cfg)
        uvicorn.run(app, host=cfg["server"]["host"], port=int(cfg["server"]["port"]),
                    workers=1, log_level="info")

    # ---------- worker：启动后台计算进程 ----------
    # role="worker" + load_model=True，会加载完整的规则检测器 + Agent。
    # 启动后进入 run_forever() 主循环：心跳 → 抢占租约 → 执行任务 → 续期 → 写回结果。
    # 这是整个平台的核心计算引擎，负责日志解析、事件诊断、Agent 推理。
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        runtime = ServiceRuntime(cfg, load_model=True, role="worker")
        # 启动前的就绪检查：如果装配阶段出错（模型缺失、Agent 加载失败等），立即退出
        # 而不是让 worker 进入循环后持续抛异常。
        if runtime.ready_error:
            raise SystemExit(runtime.ready_error)
        try:
            runtime.run_forever()
        except KeyboardInterrupt:
            # 优雅停机：停止事件 → 释放资源（Agent/RAG 连接池等）
            runtime.stop()

    # ---------- worker-health：健康检查探针 ----------
    # 不启动任何长驻进程，仅做一次性检查：
    # 1) manifest 是否存在（release 目录是否就绪）
    # 2) 最近是否收到过 worker 心跳（防止 worker 崩溃但容器仍存活）
    # Kubernetes 的 liveness/readiness probe 或 systemd 看门狗会调用此命令。
    elif args.command == "worker-health":
        runtime = ServiceRuntime(cfg, load_model=False, role="healthcheck")
        if runtime.manifest is None:
            raise SystemExit(runtime.ready_detail or "release unavailable")
        age = int(cfg["worker"].get("heartbeat_max_age_seconds", 15))
        # 心跳超过 age 秒 → worker 可能已僵死，返回非零退出码触发重启
        if runtime.db.worker_ready(runtime.manifest["release_id"], age) is None:
            raise SystemExit("worker heartbeat is stale")
        print("ready")

    # ---------- benchmark：运行基准测试 ----------
    # 套件 e1–e4 分别覆盖不同场景（单批次处理、并发诊断、RAG 检索、Agent 推理等），
    # 返回结构化的性能指标 JSON。
    elif args.command == "benchmark":
        print(json.dumps(run_benchmark(cfg, args.suite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()