"""nearagentpay: per-step on-chain payments for AI agents on NEAR.

Give an AI agent a task and a NEAR budget. It plans priced steps, routes
each to the cheapest live provider quote, and settles every step on-chain
(NEAR testnet) through a facilitator account, with budget enforcement and a
full audit ledger. Run: cd app && python3 main.py -> localhost:8792
"""
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from chain import get_gateway
from agent import run_task, live_quotes, DEFAULT_PROVIDERS
from store import Store

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "..", "static")
PORT = int(os.environ.get("AGENTPAY_PORT", "8792"))
STORE = Store(os.environ.get(
    "AGENTPAY_DB", os.path.join(ROOT, "..", "nearagentpay.db")))
GATEWAY = get_gateway(os.environ)
PROVIDER_MAP = None
if GATEWAY.name == "near-testnet":
    PROVIDER_MAP = getattr(GATEWAY, "provider_map", None)
RUN_TIMES = []
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"):
            try:
                with open(os.path.join(STATIC, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, "{}")
        if p.path == "/api/providers":
            return self._send(200, json.dumps({
                "gateway": GATEWAY.name, "quotes": live_quotes(),
                "providers": DEFAULT_PROVIDERS}))
        if p.path == "/api/runs":
            return self._send(200, json.dumps({"runs": STORE.list_runs(),
                                               "gateway": GATEWAY.name}))
        if p.path == "/api/run":
            rid = parse_qs(p.query).get("id", [""])[0]
            run = STORE.get_run(rid)
            if not run:
                return self._send(404, json.dumps({"error": "not found"}))
            return self._send(200, json.dumps(run))
        return self._send(404, "{}")

    def do_POST(self):
        p = urlparse(self.path)
        body = self._json_body()
        if p.path == "/api/run":
            task = (body.get("task") or "").strip()
            if not task:
                return self._send(400, json.dumps({"error": "task required"}))
            try:
                budget = float(body.get("budget", "5.00"))
            except ValueError:
                return self._send(400, json.dumps({"error": "budget must be a number"}))
            if budget <= 0 or budget > 1000:
                return self._send(400, json.dumps({"error": "budget must be between 0 and 1000"}))
            now = time.time()
            with LOCK:
                recent = [t for t in RUN_TIMES if now - t < 60]
                RUN_TIMES[:] = recent
                if len(recent) >= 10:
                    return self._send(429, json.dumps({"error": "rate limit: 10 runs per minute"}))
                RUN_TIMES.append(now)
            rid = str(uuid.uuid4())[:8]
            STORE.create_run(rid, task, budget)
            threading.Thread(target=self._run_task,
                             args=(rid, task, budget), daemon=True).start()
            return self._send(202, json.dumps({"run_id": rid}))
        if p.path == "/api/refund":
            ok, detail = STORE.refund_step(GATEWAY, body.get("step_id"))
            return self._send(200 if ok else 400, json.dumps({"ok": ok, "detail": detail}))
        return self._send(404, "{}")

    def _run_task(self, rid, task, budget):
        result = run_task(task, budget, GATEWAY, lambda s: STORE.add_step(rid, s),
                          PROVIDER_MAP)
        STORE.finish_run(rid, result["status"], result.get("error"))


def main():
    print(f"nearagentpay on http://localhost:{PORT} (gateway: {GATEWAY.name})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
