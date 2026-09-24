import base64
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
test_data_dir = Path(tempfile.mkdtemp(prefix="xjalgo-auth-browser-")).resolve()
os.environ["MC_TRAIN_DATA_DIR"] = str(test_data_dir)
os.environ["MC_PLATFORM_VERSION"] = "browser-auth-test"
os.environ["MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS"] = "0"
os.environ["MC_CHANGLIAN_LOGIN_BASE_URL"] = "http://127.0.0.1:18081"
os.environ["MC_AUTH_SESSION_IDLE_SECONDS"] = str(7 * 24 * 60 * 60)
os.environ["MC_AUTH_SESSION_ABSOLUTE_SECONDS"] = str(30 * 24 * 60 * 60)
test_ultralytics_dir = test_data_dir / "ultralytics"
test_ultralytics_dir.mkdir()
os.environ["YOLO_CONFIG_DIR"] = str(test_ultralytics_dir)


def _b64(value):
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")


class ChangLianMockHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        if self.path != "/login":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if body.get("username") == "demo" and body.get("password") == "secret":
            expires_in = 2 * 60 * 60
            token = f"{_b64({'alg': 'none'})}.{_b64({'sub': 'demo', 'exp': int(time.time()) + expires_in})}."
            payload = {
                "code": 200,
                "msg": "登录成功",
                "token": token,
                "expiresIn": expires_in,
            }
            status = 200
        else:
            payload = {"code": 500, "msg": "用户名或密码错误"}
            status = 200
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


mock = ThreadingHTTPServer(("127.0.0.1", 18081), ChangLianMockHandler)
threading.Thread(target=mock.serve_forever, daemon=True).start()

uvicorn.run("app:app", host="127.0.0.1", port=8012, log_level="warning")
