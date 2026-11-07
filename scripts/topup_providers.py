"""Top up provider subaccounts so refunds always cover chain fees."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from chain import NearRPC, Key, build_and_sign, transfer_action, to_yocto  # noqa: E402
from agent import CATALOG  # noqa: E402

TOPUP_NEAR = 0.5

def main():
    account = os.environ.get("NEAR_FACILITATOR_ACCOUNT", "izagentpay.testnet")
    key = Key(os.environ["NEAR_FACILITATOR_KEY"])
    rpc = NearRPC(os.environ.get("NEAR_RPC_URL", "https://rpc.testnet.fastnear.com"))
    providers = sorted({p for plist in CATALOG.values() for p, _ in plist})
    for name in providers:
        sub = f"{name.lower()}.{account}"
        tx, signed = build_and_sign(account, sub, 0,
                                    [transfer_action(to_yocto(TOPUP_NEAR))], key, rpc)
        rpc.broadcast_tx_commit(signed)
        print(f"topped up {sub} +{TOPUP_NEAR} NEAR tx={tx[:14]}...")
        time.sleep(0.4)

if __name__ == "__main__":
    main()
