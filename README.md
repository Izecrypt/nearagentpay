# nearagentpay — agents pay per step, on-chain

Built for the **NEAR Hackathon** (Nov 14 2026 deadline). The AgentPay
thesis, settled natively on NEAR: AI agents as economic actors that buy
services step by step, paying per step on-chain through a facilitator
account, with live price routing, budget enforcement, and an audit ledger
where every receipt is a transaction hash anyone can verify in the
explorer.

## Why NEAR

Per-step machine payments need a chain where a transfer is final in about
a second and costs a fraction of a cent. NEAR testnet settles each agent
step as a real transfer with an explorer link — the ledger stops being a
claim and becomes a receipt.

## How it works

1. **Plan.** A task is broken into priced steps (translation, image,
   dataset, search, summarization) in the order the task mentions them.
2. **Source by live price.** Providers are re-quoted before each step;
   the step routes to the cheapest quote that fits the remaining budget,
   with fallback if a provider fails.
3. **Settle per step.** Each executed step is a NEAR transfer from the
   facilitator to the provider, confirmed on-chain (tx hash shown, linked
   to the explorer). Money moves when work moves.
4. **Enforce budgets.** A run-level NEAR cap binds the agent; steps that
   would break the budget are skipped with the reason written down.
5. **Audit everything.** Every decision — providers compared, best price,
   tx hash, refunds — lands in a ledger a finance team can read.

## Run it

```bash
pip install pynacl          # the one dependency (signing)
cd app && python3 main.py   # http://localhost:8792
```

Without chain credentials it runs in **simulation mode** (same interface,
deterministic demo). For live NEAR testnet settlement:

```bash
export NEAR_FACILITATOR_ACCOUNT=your.testnet
export NEAR_FACILITATOR_KEY=ed25519:...   # full-access key, hidden input only
export NEAR_PROVIDERS='{"LinguaFast":"linguafast.your.testnet", ...}'
export NEAR_PROVIDER_SECRETS='{"LinguaFast":"ed25519:...", ...}'
cd app && python3 main.py
```

Provider accounts are subaccounts the facilitator creates, so refunds are
signed by the facilitator on the provider's behalf (documented prototype
choice; a production version settles between independent principals).

## Architecture

| File | Role |
|---|---|
| `app/chain.py` | NEAR JSON-RPC, borsh serialization, ed25519 signing (PyNaCl), base58, testnet gateway + simulation gateway |
| `app/agent.py` | task planner, live price routing, budget enforcement |
| `app/store.py` | SQLite audit ledger (runs, steps, tx hashes, refunds) |
| `app/main.py` | stdlib HTTP server: JSON API + control room UI |
| `tests/smoke_test.py` | 25 checks: chain primitives, agent loop, ledger, HTTP integration |

## API

- `POST /api/run` `{task, budget}` — start an agent run
- `GET /api/run?id=` — run detail with the full audit trail and explorer links
- `GET /api/runs` — recent runs
- `POST /api/refund` `{step_id}` — refund a settled step
- `GET /api/providers` — gateway mode + live quotes

## Tools used

- NEAR Protocol: testnet JSON-RPC, native transfers, ed25519 signatures.
- AI: rule-based planner in this prototype; any LLM planner drops in
  behind the same `plan()` interface. The contribution is the payment
  control plane, not the planner.

## License

MIT, see LICENSE.
