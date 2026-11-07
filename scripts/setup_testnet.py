"""One-time testnet setup: create provider subaccounts under the facilitator.

Usage: python3 scripts/setup_testnet.py
Reads facilitator credentials from the environment, creates any missing
provider subaccounts (CreateAccount + AddKey + funding transfer in one tx),
and writes a local env file (gitignored) with the provider map and secrets.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from chain import (NearRPC, Key, build_and_sign, b58encode, b58decode,  # noqa: E402
                   create_account_action, add_key_action, transfer_action)

from agent import CATALOG  # noqa: E402

FUND_NEAR = 0.5
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env.testnet")


def main():
    account = os.environ.get("NEAR_FACILITATOR_ACCOUNT", "izagentpay.testnet")
    secret = os.environ["NEAR_FACILITATOR_KEY"]
    rpc = NearRPC(os.environ.get("NEAR_RPC_URL", "https://rpc.testnet.near.org"))
    key = Key(secret)

    providers = {p for plist in CATALOG.values() for p, _ in plist}
    provider_map, provider_secrets = {}, {}
    for name in sorted(providers):
        sub = f"{name.lower()}.{account}"
        provider_map[name] = sub
        if rpc.account_exists(sub):
            print(f"exists  {sub}")
            continue
        pkey = Key(b58encode(__import__("nacl.signing")
                             .signing.SigningKey.generate()._seed))
        provider_secrets[name] = "ed25519:" + b58encode(pkey.sk._seed)
        actions = [create_account_action(),
                   add_key_action(pkey.pk_bytes),
                   transfer_action(int(FUND_NEAR * 10 ** 18))]
        tx_hash, signed = build_and_sign(account, sub, 0, actions, key, rpc)
        rpc.broadcast_tx_commit(signed)
        print(f"created {sub} tx={tx_hash[:16]}...")
        time.sleep(0.5)

    with open(ENV_PATH, "w") as f:
        f.write(f"NEAR_FACILITATOR_ACCOUNT={account}\n")
        f.write(f"NEAR_FACILITATOR_KEY={secret}\n")
        f.write(f"NEAR_PROVIDERS='{json.dumps(provider_map, separators=(',', ':'))}'\n")
        if provider_secrets:
            f.write(f"NEAR_PROVIDER_SECRETS='{json.dumps(provider_secrets, separators=(',', ':'))}'\n")
    print(f"wrote {ENV_PATH}")


if __name__ == "__main__":
    main()
