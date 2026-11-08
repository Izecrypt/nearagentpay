# NEAR HACKATHON — judges' walkthrough

Track: **Agent Economy** (AI agents that earn, spend, negotiate and pay for
services). Built for NEAR HACKATHON: Build Beyond Boundaries, Nov 2026.

## What this is

nearagentpay: an AI agent pays for services step by step, on-chain. A human
funds a facilitator float; the agent plans a task into priced steps,
re-quotes providers live, routes each step to the cheapest quote, and
settles every step as a NEAR transfer, inside a run budget, with an
internal audit ledger. Money moves when work moves.

## Try it (do X, see Y)

1. Clone and run: `pip install pynacl && cd app && python3 main.py`
   → open http://localhost:8792. See the console with the live facilitator
   float and the streaming provider market.
2. Type "translate my pitch deck to french and generate a header image",
   set a 2.00 NEAR budget, press **Run agent**.
   → See the run plan into steps, then per-step provider quote bars.
3. Watch the first step settle.
   → See a tx hash appear; click it to see the real transfer on the NEAR
   testnet explorer (facilitator → provider account, FINAL).
4. Watch the deliverable arrive.
   → See a "deliverable received" card under the paid step (the purchased
   work, visible next to its payment).
5. Click **refund step** on any paid step.
   → See a second on-chain transaction return the funds (refund id
   recorded in the ledger row).
6. Open the audit ledger below.
   → See every settled step across all runs: time, task, provider, amount,
   tx link, status, lifetime totals.

## NEAR technologies used

- **Named accounts and sub-accounts**: the facilitator (izagentpay.testnet)
  and all 15 provider accounts are NEAR accounts created on testnet; the
  facilitator self-created provider subaccounts in a single transaction
  each (CreateAccount + AddKey + Transfer actions).
- **Native NEAR transfers**: every agent step settles as a transfer,
  final in seconds, explorer-verifiable.
- Account model follows the hackathon's account-design area (named
  accounts, sub-accounts); NEAR Intents and chain signatures are
  documented in the README as the next step for cross-chain providers and
  policy-managed agent keys.

## Live status

The demo runs on NEAR testnet with a live facilitator and 15 funded
provider accounts. The demo video in the entry post records a real run:
0.217 NEAR settled across two steps, both transactions final on-chain.
