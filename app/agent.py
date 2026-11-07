"""AgentPay-on-NEAR agent loop: plan a task into priced steps, route each
step to the cheapest live quote, settle per step on-chain, enforce the
budget, and record every decision."""
import random
import time

CURRENCY = "NEAR"

# Service catalog: provider -> subaccount suffix and base price (NEAR).
# Prices jitter per call so live price routing is visible on every run.
CATALOG = {
    "translation":   [("LinguaFast", 0.09), ("PolyGlot", 0.11), ("VerbatimAI", 0.16)],
    "summarization": [("TLDRbox", 0.04), ("Summa", 0.06), ("CondensePro", 0.08)],
    "image":         [("PixelForge", 0.12), ("DraWave", 0.15), ("StudioBot", 0.21)],
    "dataset":       [("DataMart", 0.18), ("SetForge", 0.22), ("GridSource", 0.29)],
    "search":        [("Fetchly", 0.03), ("CrawlWise", 0.04), ("IndexGo", 0.05)],
}

KEYWORDS = [
    (("translate", "translation", "french", "spanish", "language"), "translation"),
    (("summar", "tldr", "condense"), "summarization"),
    (("image", "logo", "picture", "poster", "art"), "image"),
    (("dataset", "data", "csv", "records"), "dataset"),
    (("research", "find", "search", "look up", "compare"), "search"),
]

DEFAULT_PROVIDERS = {
    name: name.lower() + ".provider"
    for providers in CATALOG.values() for name, _ in providers
}


def live_quotes():
    return {
        service: [
            {"provider": p, "price": round(base * random.uniform(0.85, 1.25), 3)}
            for p, base in providers
        ]
        for service, providers in CATALOG.items()
    }


def plan(task):
    low = task.lower()
    found = []
    for keys, svc in KEYWORDS:
        pos = min((low.find(k) for k in keys if low.find(k) >= 0), default=-1)
        if pos >= 0:
            found.append((pos, svc))
    services = [svc for _, svc in sorted(found)]
    if not services:
        services = ["search", "summarization"]
    if "dataset" in services and "search" not in services:
        services.insert(0, "search")
    return services


def receiver_for(provider, provider_map):
    return (provider_map or {}).get(provider) or DEFAULT_PROVIDERS.get(provider)


def run_task(task, budget, gateway, on_step, provider_map=None):
    run_spend = 0.0
    for n, service in enumerate(plan(task), start=1):
        quotes = sorted(live_quotes()[service], key=lambda q: q["price"])
        remaining = round(budget - run_spend, 3)
        step = {
            "step": n, "service": service,
            "providers_considered": len(quotes),
            "best_price": quotes[0]["price"],
            "budget_remaining": remaining,
            "order_id": None, "capture_id": None, "status": "skipped",
            "refund_id": None, "note": "", "provider": None,
            "explorer_url": None,
        }
        affordable = [q for q in quotes if q["price"] <= remaining]
        step["quotes"] = quotes
        if not affordable:
            step["note"] = (f"cheapest quote {quotes[0]['price']:.3f} exceeds remaining "
                            f"budget {remaining:.3f}; step skipped")
            on_step(step)
            continue
        attempts = []
        for quote in affordable:
            receiver = receiver_for(quote["provider"], provider_map)
            if not receiver:
                attempts.append(f"{quote['provider']}: no settlement account")
                continue
            created = gateway.create_order(quote["price"], receiver=receiver)
            if not created.get("ok"):
                attempts.append(f"{quote['provider']}: {created.get('error')}")
                continue
            step["order_id"] = created["order_id"]
            step["provider"] = quote["provider"]
            step["explorer_url"] = (gateway.explorer_url(created["order_id"])
                                    if hasattr(gateway, "explorer_url") else None)
            captured = gateway.capture(created["order_id"])
            if not captured.get("ok"):
                step["status"] = "failed"
                step["note"] = f"{quote['provider']}: {captured.get('error')}"
                on_step(step)
                break
            step["capture_id"] = captured.get("capture_id")
            step["status"] = "paid"
            step["best_price"] = quote["price"]
            run_spend += quote["price"]
            tried = f" after {len(attempts)} failed provider(s)" if attempts else ""
            step["note"] = (f"settled {quote['price']:.3f} NEAR to {quote['provider']}"
                            f"{tried}; tx final on-chain")
            on_step(step)
            break
        else:
            step["status"] = "failed"
            step["note"] = "; ".join(attempts) or "no provider succeeded"
            on_step(step)
        if step["status"] == "paid":
            time.sleep(0.4)
    return {"status": "completed", "error": None, "spent": round(run_spend, 3)}
