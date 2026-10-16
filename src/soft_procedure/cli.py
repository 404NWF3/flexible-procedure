"""uv run soft-procedure [serve | experiments | run]。"""
import argparse
import json
from pathlib import Path

from .config import SimulationConfig
from .experiments import SCENARIOS, run_experiments, scenario_config
from .export import write_experiments, write_run
from .model.simulation import run_simulation


def main():
    parser = argparse.ArgumentParser(description="柔性生产线 SimPy 决策仿真")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("serve", "启动交互面板"), ("experiments", "运行五组实验并生成离线 HTML"), ("run", "运行单次模型")):
        p = commands.add_parser(name, help=help_text)
        p.add_argument("--config", type=Path, help="JSON 配置文件，仅填写需要修改的字段")
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--output", type=Path, default=Path("outputs"))
        if name != "run":
            p.add_argument("--replications", type=int, default=10)
        if name == "serve":
            p.add_argument("--port", type=int, default=8765)
        if name == "run":
            p.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    args = parser.parse_args()
    try:
        config = SimulationConfig.from_dict(json.loads(args.config.read_text())) if args.config else SimulationConfig()
        if args.command == "run":
            result = run_simulation(scenario_config(config, args.scenario), args.seed)
            write_run(result, args.output)
            args.output.joinpath("run.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
            print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
            return
        suite = run_experiments(config, args.replications, args.seed)
        html = write_experiments(suite, args.output)
        for s in suite["scenarios"]:
            stat = s["summary"]["completed"]
            print(f"{s['name']}: {stat['mean']:.1f} 件；配对差值 {s['paired_output_difference']['mean']:+.1f} 件")
        print(f"HTML 面板：{html.resolve()}", flush=True)
        if args.command == "serve":
            from .server import make_server
            server = make_server(suite, args.output, args.port)
            print(f"Local: http://127.0.0.1:{server.server_port}  (Ctrl+C 停止)", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, OSError) as error:
        parser.exit(2, f"错误：{error}\n")
