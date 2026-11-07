"""nearagentpay smoke tests. Run: cd app && python3 ../tests/smoke_test.py

Covers the chain primitives (base58 round-trip, borsh shapes), the agent
loop against the simulation gateway, the ledger and refunds, and a live
HTTP integration pass against a spawned server.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from chain import b58encode, b58decode, SimGateway, get_gateway, to_yocto, NEAR  # noqa: E402
from agent import plan, run_task, live_quotes, CATALOG, receiver_for, artifact_for  # noqa: E402
from store import Store  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ok {name}")


print("chain primitives")
raw = bytes(range(1, 64))
check("base58 round-trip", b58decode(b58encode(raw)) == raw)
check("base58 known vector (bitcoin)", b58encode(b"hello world") == "StV1DL6CwTryKyV")
check("yocto conversion", to_yocto(1.5) == 15 * 10 ** 23 and NEAR == 10 ** 24)
check("yocto exact at 24 decimals", to_yocto(0.037) == 37 * 10 ** 21)


print("plan()")
svc = plan("generate a header image, then translate the copy to french")
check("service order follows task order", svc[0] == "image" and "translation" in svc)
check("unknown task gets default plan", plan("xyzzy unknown") == ["search", "summarization"])
check("word boundaries: 'start' does not trigger 'art'",
      "image" not in plan("start a campaign"))
check("word boundaries: 'metadata' does not trigger 'data'",
      "dataset" not in plan("update the metadata"))
check("word boundaries: 'records' still matches",
      "dataset" in plan("find records of suppliers"))
print("artifact seed stability")
a1 = artifact_for("image", "PixelForge")
check("seed derived from stable crc32", a1["seed"] == artifact_for("image", "PixelForge")["seed"])

print("live_quotes()")
q = live_quotes()
check("every catalog service quoted", set(q) == set(CATALOG))
check("prices positive", all(x["price"] > 0 for s in q for x in q[s]))
check("default settlement accounts derive from provider names",
      receiver_for("LinguaFast", None) == "linguafast.provider")


class Flaky(SimGateway):
    def __init__(self, n):
        self.n = n

    def create_order(self, amount, receiver=None):
        if self.n > 0:
            self.n -= 1
            return {"ok": False, "error": "provider timeout"}
        return super().create_order(amount, receiver=receiver)


print("run_task with sim gateway")
steps = []
res = run_task("translate the deck to french and summarize it",
               1.0, SimGateway(), steps.append)
paid = [s for s in steps if s["status"] == "paid"]
check("run completes", res["status"] == "completed")
check("steps settled", len(paid) >= 2)
check("every settled step has a tx id", all(s["order_id"] for s in paid))
check("spend equals sum of settled steps",
      abs(res["spent"] - sum(s["best_price"] for s in paid)) < 0.0001)
check("provider recorded on settled steps", all(s["provider"] for s in paid))

print("budget enforcement")
steps = []
run_task("build a dataset and summarize it", 0.10, SimGateway(), steps.append)
check("unaffordable step skipped with reason",
      any(s["status"] == "skipped" and "exceeds remaining budget" in s["note"]
          for s in steps))
check("affordable step still settled", any(s["status"] == "paid" for s in steps))

print("provider fallback")
steps = []
run_task("translate the deck", 1.0, Flaky(1), steps.append)
check("fallback after failure",
      any("after 1 failed provider" in s["note"] for s in steps if s["status"] == "paid"))

print("store and refunds")
tmp = os.path.join(tempfile.mkdtemp(), "t.db")
store = Store(tmp)
store.create_run("r1", "task", 1.0)
run_task("translate the deck", 1.0, SimGateway(), lambda s: store.add_step("r1", s))
run = store.get_run("r1")
check("run stored with steps", len(run["steps"]) >= 1 and run["spent"] > 0)
paid_step = next(s for s in run["steps"] if s["status"] == "paid")
ok, detail = store.refund_step(SimGateway(), paid_step["id"])
check("refund succeeds", ok and detail)
ok2, _ = store.refund_step(SimGateway(), paid_step["id"])
check("double refund rejected", not ok2)

print("gateway selection")
check("no creds -> sim", get_gateway({}).name == "sim")
import nacl.signing  # noqa: E402
from chain import Key  # noqa: E402
dummy_seed = bytes(nacl.signing.SigningKey.generate()._seed)
dummy_b58 = "ed25519:" + b58encode(dummy_seed)
check("creds -> near testnet",
      get_gateway({"NEAR_FACILITATOR_ACCOUNT": "x.testnet",
                   "NEAR_FACILITATOR_KEY": dummy_b58}).name == "near-testnet")

print("integration: real server over HTTP")
env = dict(os.environ, AGENTPAY_PORT="8793",
           AGENTPAY_DB=os.path.join(tempfile.mkdtemp(), "i.db"))
proc = subprocess.Popen([sys.executable, "main.py"], cwd=os.path.join(
    os.path.dirname(__file__), "..", "app"), env=env)
try:
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:8793/api/runs", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    req = urllib.request.Request(
        "http://127.0.0.1:8793/api/run", method="POST",
        data=json.dumps({"task": "translate the deck to french",
                         "budget": "1.0"}).encode(),
        headers={"Content-Type": "application/json"})
    rid = json.loads(urllib.request.urlopen(req, timeout=5).read())["run_id"]
    for _ in range(40):
        run = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:8793/api/run?id={rid}", timeout=2).read())
        if run["run"]["status"] != "running":
            break
        time.sleep(0.3)
    check("run completes over HTTP", run["run"]["status"] == "completed")
    check("steps settled over HTTP", any(s["status"] == "paid" for s in run["steps"]))
    check("ui served", b"near" in urllib.request.urlopen(
        "http://127.0.0.1:8793/", timeout=2).read().lower())
    bad = urllib.request.Request(
        "http://127.0.0.1:8793/api/run", method="POST",
        data=json.dumps({"task": "", "budget": "1"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(bad, timeout=2)
        check("empty task rejected", False)
    except urllib.error.HTTPError as e:
        check("empty task rejected", e.code == 400)
finally:
    proc.terminate()

print(f"\n{PASS} checks passed")
