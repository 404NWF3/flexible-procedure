"""仅绑定本机的轻量 API；面板和命令行共用同一仿真函数。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import SimulationConfig
from .experiments import public_suite, run_experiments
from .export import render_dashboard, write_experiments


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) - {"config", "replications", "seed"}:
        raise ValueError("请求必须只包含 config、replications、seed")
    config = SimulationConfig.from_dict(payload.get("config", {}))
    replications, seed = payload.get("replications", 10), payload.get("seed", 42)
    if type(replications) is not int or not 1 <= replications <= 30:
        raise ValueError("重复次数范围为 1–30")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 31:
        raise ValueError("随机种子必须是 0–2147483617 的整数")
    if not 1 <= config.horizon <= 14400 or config.arrival_mean < 1:
        raise ValueError("面板支持 1–14400 分钟，平均到达间隔至少 1 分钟")
    if max(config.machine_counts.values()) > 8 or config.buffer_capacity > 500 or config.batch_max > 100:
        raise ValueError("面板每工位最多 8 台机床、缓冲最多 500 件、每批最多 100 件")
    if config.mtbf < 1 or config.mttr < 0.1 or config.processing_cv > 1 or config.setup_time > 2400:
        raise ValueError("MTBF 至少 1 分钟，MTTR 至少 0.1 分钟，CV 不超过 1，换模不超过 2400 分钟")
    if config.sample_interval < 1 or config.horizon / config.sample_interval > 1500:
        raise ValueError("采样间隔至少 1 分钟，回放采样点不能超过 1500 个")
    workload = config.horizon / config.arrival_mean * (config.batch_min + config.batch_max) / 2 * replications * 5
    if workload > 1_500_000:
        raise ValueError("本次实验规模过大，请减少仿真时长、重复次数或批次大小")
    return config, replications, seed


def make_server(suite, output, port=8765):
    state = {"suite": suite}
    run_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def respond(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def local_request(self):
            host = self.headers.get("Host", "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                self.respond(403, {"error": "仅允许本机访问"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                self.respond(403, {"error": "请在本地面板中运行实验"})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            path = urlparse(self.path).path
            if path in ("/", "/dashboard.html"):
                self.respond(200, render_dashboard(state["suite"]), "text/html; charset=utf-8")
            elif path == "/api/health":
                self.respond(200, {"status": "ready", "engine": "SimPy"})
            elif path == "/api/results":
                self.respond(200, public_suite(state["suite"]))
            elif path == "/favicon.ico":
                self.respond(204, "")
            else:
                self.respond(404, {"error": "未找到页面"})

        def do_POST(self):
            if not self.local_request():
                return
            if self.path != "/api/run":
                self.respond(404, {"error": "未找到接口"})
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("请求格式应为 application/json")
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 32768:
                    raise ValueError("请求长度必须为 1–32768 字节")
                config, replications, seed = validate_request(json.loads(self.rfile.read(length)))
            except (ValueError, TypeError, UnicodeError) as error:
                self.respond(400, {"error": str(error)})
                return
            if not run_lock.acquire(blocking=False):
                self.respond(409, {"error": "已有实验正在运行，请稍后再试"})
                return
            try:
                result = run_experiments(config, replications, seed)
                write_experiments(result, output)
                state["suite"] = result
                self.respond(200, public_suite(result))
            except Exception:
                import traceback
                traceback.print_exc()
                self.respond(500, {"error": "仿真未完成，原结果已保留；请查看终端日志"})
            finally:
                run_lock.release()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
