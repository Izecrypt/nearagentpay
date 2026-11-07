"""SQLite audit ledger for the NEAR-native AgentPay run."""
import json
import sqlite3
import time


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs(
          id TEXT PRIMARY KEY, task TEXT, budget REAL, currency TEXT DEFAULT 'NEAR',
          status TEXT DEFAULT 'running', error TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, n INTEGER,
          service TEXT, provider TEXT, providers_considered INTEGER, best_price REAL,
          budget_remaining REAL, order_id TEXT, capture_id TEXT, status TEXT,
          refund_id TEXT, note TEXT, explorer_url TEXT, quotes_json TEXT, ts REAL);
        """)
        try:
            self.conn.execute("ALTER TABLE steps ADD COLUMN quotes_json TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("ALTER TABLE steps ADD COLUMN artifact_json TEXT")
        except sqlite3.OperationalError:
            pass

    def create_run(self, rid, task, budget):
        self.conn.execute(
            "INSERT INTO runs(id,task,budget,status,created) VALUES(?,?,?,'running',?)",
            (rid, task, budget, time.time()))
        self.conn.commit()

    def add_step(self, rid, step):
        self.conn.execute(
            """INSERT INTO steps(run_id,n,service,provider,providers_considered,
               best_price,budget_remaining,order_id,capture_id,status,refund_id,
               note,explorer_url,quotes_json,artifact_json,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, step.get("step"), step.get("service"), step.get("provider"),
             step.get("providers_considered"), step.get("best_price"),
             step.get("budget_remaining"), step.get("order_id"),
             step.get("capture_id"), step.get("status"), step.get("refund_id"),
             step.get("note"), step.get("explorer_url"),
             json.dumps(step.get("quotes")) if step.get("quotes") else None,
             json.dumps(step.get("artifact")) if step.get("artifact") else None,
             time.time()))
        self.conn.commit()

    def finish_run(self, rid, status, error=None):
        self.conn.execute("UPDATE runs SET status=?, error=? WHERE id=?",
                          (status, error, rid))
        self.conn.commit()

    def list_runs(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT id,task,budget,status,created FROM runs ORDER BY created DESC LIMIT 50")]

    def get_run(self, rid):
        run = self.conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if not run:
            return None
        steps = []
        for s in self.conn.execute("SELECT * FROM steps WHERE run_id=? ORDER BY n", (rid,)):
            d = dict(s)
            if d.get("quotes_json"):
                d["quotes"] = json.loads(d["quotes_json"])
            if d.get("artifact_json"):
                d["artifact"] = json.loads(d["artifact_json"])
            steps.append(d)
        spent = round(sum(s["best_price"] or 0 for s in steps if s["status"] == "paid"), 3)
        return {"run": dict(run), "steps": steps, "spent": spent,
                "remaining": round(run["budget"] - spent, 3)}

    def refund_step(self, gateway, step_id):
        s = self.conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone()
        if not s:
            return False, "step not found"
        if s["status"] != "paid" or not s["capture_id"]:
            return False, "step is not in a paid state"
        if s["refund_id"]:
            return False, "already refunded"
        res = gateway.refund(s["capture_id"], s["best_price"], provider=s["provider"])
        if not res.get("ok"):
            return False, f"refund failed: {res.get('error')}"
        self.conn.execute("UPDATE steps SET refund_id=?, status='refunded' WHERE id=?",
                          (res.get("refund_id"), step_id))
        self.conn.commit()
        return True, res.get("refund_id")

    def refund_step_safe(self, gateway, step_id):
        """Never raise into the HTTP handler; a chain error becomes a clean 400."""
        try:
            return self.refund_step(gateway, step_id)
        except Exception as e:
            return False, f"refund error: {str(e)[:200]}"

    def list_ledger(self, limit=100):
        rows = [dict(r) for r in self.conn.execute(
            """SELECT s.*, r.task AS run_task FROM steps s
               JOIN runs r ON r.id = s.run_id
               ORDER BY s.ts DESC LIMIT ?""", (limit,))]
        for d in rows:
            for key, col in (("quotes", "quotes_json"), ("artifact", "artifact_json")):
                if d.get(col):
                    d[key] = json.loads(d[col])
        totals = dict(self.conn.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN status='paid' THEN best_price END),0) AS settled,
                 COALESCE(SUM(CASE WHEN status='refunded' THEN best_price END),0) AS refunded,
                 COUNT(*) AS steps,
                 COUNT(DISTINCT run_id) AS runs
               FROM steps""").fetchone())
        return {"rows": rows, "totals": totals}
