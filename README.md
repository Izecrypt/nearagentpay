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

Wallet interaction: no connect-wallet in the agent loop (the agent spends
the facilitator float; humans never sign per action). The wallet touchpoint
is funding the float, done properly with @near-wallet-selector (MyNearWallet
module on testnet): connect / disconnect / switch from the in-app wallet bar,
and top up the float with an in-app, wallet-signed transfer. A deep-link to
the MyNearWallet send page remains as the no-JS fallback. Production path
for agent keys stays MPC / chain signatures.

## Alignment with NEAR hackathon themes

The announcement names NEAR Intents, chain signatures, chain abstraction,
and NEAR AI Cloud. Where this build stands on each, honestly:

- **Native settlement today:** every agent step is a NEAR transfer, final
  in seconds, explorer-verifiable. This is the core contribution.
- **NEAR Intents (next step, not yet implemented):** the provider-routing
  layer is exactly where Intents fit — an agent buying a step from a
  provider that lives on another chain should route through 1-click intents
  rather than bridging manually. The control plane (`plan`, routing,
  budget, ledger) is unchanged when a step's settlement moves to intents.
- **Chain signatures (direction):** facilitator keys today are ed25519
  full-access keys held in server env. MPC/chain-signatures would let the
  facilitator policy live on-chain (spend limits enforced by the chain
  itself, not just the agent loop). Documented as the production path.
- **NEAR AI Cloud (direction):** the deterministic `plan()` is deliberately
  swappable; an LLM planner hosted on NEAR AI infrastructure drops behind
  the same interface.

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
- `GET /api/facilitator` — facilitator account, live balance, explorer link
- `GET /api/ledger` — cross-run audit trail with lifetime totals

## Tools used

- NEAR Protocol: testnet JSON-RPC, native transfers, ed25519 signatures.
- AI: rule-based planner in this prototype; any LLM planner drops in
  behind the same `plan()` interface. The contribution is the payment
  control plane, not the planner.

## For NEAR hackathon judges

See [HACKATHON.md](HACKATHON.md) for a do-X-see-Y walkthrough, the
technologies used (named accounts, sub-accounts, native NEAR transfers),
and the entry's track (Agent Economy).

## License

MIT, see LICENSE.
