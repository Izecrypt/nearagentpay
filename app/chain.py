"""NEAR chain adapter: JSON-RPC client, transaction signing (ed25519 via
PyNaCl), borsh serialization, base58. Testnet by default.

The gateway interface matches the agent loop's expectations:
  create_order(amount, receiver) -> {"ok", "order_id"(=tx hash), ...}
  capture(order_id)              -> polls inclusion, {"ok", "capture_id"}
  refund(amount, receiver)       -> transfer back (provider subaccounts are
                                    facilitator-created, so it can re-sign)
"""
import base64
import hashlib
import json
import os
import time
import urllib.request

import nacl.signing

try:
    import certifi
    import ssl as _ssl
    CTX = _ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = None

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58 = {c: i for i, c in enumerate(ALPHABET)}


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    pad = 0
    for b in raw:
        if b == 0:
            pad += 1
        else:
            break
    return "1" * pad + (out or "")


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def _u32(n): return n.to_bytes(4, "little")
def _u64(n): return n.to_bytes(8, "little")
def _u128(n): return n.to_bytes(16, "little")


def _bstr(s: str) -> bytes:
    b = s.encode()
    return _u32(len(b)) + b


def _bvec(items):  # borsh vec: u32 count + items
    return _u32(len(items)) + b"".join(items)


SCHEMA_HASH_TRANSFER = 3  # Action enum index for Transfer


class NearRPC:
    def __init__(self, url="https://rpc.testnet.near.org", explorer=None):
        self.url = url
        self.explorer = explorer or url.replace("rpc.", "explorer.").rstrip("/")

    def _call(self, method, params):
        req = urllib.request.Request(
            self.url, method="POST",
            data=json.dumps({"jsonrpc": "2.0", "id": 1,
                             "method": method, "params": params}).encode(),
            headers={"Content-Type": "application/json"})
        kw = {"timeout": 30}
        if CTX is not None:
            kw["context"] = CTX
        try:
            with urllib.request.urlopen(req, **kw) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"rpc http {e.code} {method}: {e.read().decode()[:500]}")
        if "error" in body:
            raise RuntimeError(f"rpc error {method}: {body['error']}")
        return body["result"]

    def latest_block_hash(self):
        return self._call("status", {})["sync_info"]["latest_block_hash"]

    def access_key_nonce(self, account, public_key_b58):
        r = self._call("query", {
            "request_type": "view_access_key",
            "finality": "optimistic",
            "account_id": account,
            "public_key": public_key_b58,
        })
        return r["nonce"]

    def account_exists(self, account):
        try:
            self._call("query", {"request_type": "view_account",
                                 "finality": "final", "account_id": account})
            return True
        except RuntimeError:
            return False

    def tx_outcome(self, sender, tx_hash_b58):
        r = self._call("tx", {"tx_hash": tx_hash_b58,
                              "sender_account_id": sender,
                              "wait_until": "EXECUTED"})
        status = r.get("status", {})
        failure = status.get("Failure")
        return {"executed": failure is None, "failure": failure}

    def broadcast_tx_commit(self, signed_borsh_b58):
        return self._call("broadcast_tx_commit", [signed_borsh_b58])


class Key:
    def __init__(self, secret_b58):
        seed = b58decode(secret_b58.replace("ed25519:", ""))
        self.sk = nacl.signing.SigningKey(seed)
        self.pk_bytes = bytes(self.sk.verify_key)
        self.public_key_b58 = "ed25519:" + b58encode(self.pk_bytes)

    def sign(self, msg_32: bytes) -> bytes:
        return self.sk.sign(msg_32).signature  # 64 bytes


def build_and_sign(sender, receiver, amount_yocto, actions, key, rpc):
    """actions: list of (tag, payload_bytes).
    Returns (tx_hash_b58, signed_tx_b64) — nearcore RPC takes base64."""
    import base64
    block_hash = b58decode(rpc.latest_block_hash())
    nonce = rpc.access_key_nonce(sender, key.public_key_b58) + 1
    action_bytes = [bytes([tag]) + payload for tag, payload in actions]
    tx = (
        _bstr(sender)
        + b"\x00" + key.pk_bytes              # PublicKey: ed25519 enum
        + _u64(nonce)
        + _bstr(receiver)
        + block_hash
        + _bvec(action_bytes)
    )
    payload = hashlib.sha256(tx).digest()
    sig = key.sign(payload)
    signed = tx + b"\x00" + sig               # Signature: ed25519 enum
    return b58encode(payload), base64.b64encode(signed).decode()


def transfer_action(amount_yocto):
    return (SCHEMA_HASH_TRANSFER, _u128(amount_yocto))


def create_account_action():
    return (0, b"")


def add_key_action(pk_bytes):
    # Action::AddKey(PublicKey, AccessKey{nonce: u64,
    # permission: FullAccess = enum variant 1})
    return (5, b"\x00" + pk_bytes + _u64(0) + b"\x01")


NEAR = 10 ** 18


def to_yocto(near):
    return int(round(near * NEAR))


class NearGateway:
    name = "near-testnet"

    def __init__(self, account, secret_b58,
                 rpc_url="https://rpc.testnet.near.org",
                 provider_map=None, provider_secrets=None):
        self.account = account
        self.key = Key(secret_b58)
        self.rpc = NearRPC(rpc_url)
        self.provider_map = provider_map or {}
        self.provider_keys = {p: Key(s) for p, s in (provider_secrets or {}).items()}

    def explorer_url(self, tx_hash):
        return f"{self.rpc.explorer}/transactions/{tx_hash}"

    def _submit(self, signer, key, receiver, actions):
        tx_hash, signed = build_and_sign(signer, receiver, 0, actions, key, self.rpc)
        self.rpc.broadcast_tx_commit(signed)
        return tx_hash

    def transfer(self, signer, key, receiver, amount_near):
        return self._submit(signer, key, receiver,
                            [transfer_action(to_yocto(amount_near))])

    # gateway interface used by the agent loop
    def create_order(self, amount, receiver=None):
        receiver = receiver or self.provider_map.get(receiver)
        if not receiver:
            return {"ok": False, "error": "unknown receiver"}
        tx = self.transfer(self.account, self.key, receiver, amount)
        return {"ok": True, "order_id": tx, "status": "SUBMITTED",
                "approval_url": None}

    def capture(self, order_id):
        try:
            outcome = self.rpc.tx_outcome(self.account, order_id)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)[:300]}
        if not outcome["executed"]:
            return {"ok": False, "error": str(outcome["failure"])[:300]}
        return {"ok": True, "capture_id": order_id, "status": "FINAL"}

    def refund(self, capture_id, amount, receiver=None, provider=None):
        # refunds are signed by the provider subaccount (facilitator-created)
        pkey = self.provider_keys.get(provider)
        paccount = self.provider_map.get(provider)
        if not pkey or not paccount:
            return {"ok": False, "error": "no provider key for refund"}
        tx = self.transfer(paccount, pkey, self.account, amount)
        return {"ok": True, "refund_id": tx, "status": "FINAL"}


class SimGateway:
    """Zero-credential chain simulation with the same interface."""
    name = "sim"
    seq = 0

    def _next(self, prefix):
        SimGateway.seq += 1
        return f"{prefix}-SIM-{int(time.time())}-{SimGateway.seq:04d}"

    def explorer_url(self, tx_hash):
        return None

    def create_order(self, amount, receiver=None):
        return {"ok": True, "order_id": self._next("TX"), "status": "EXECUTED",
                "approval_url": None}

    def capture(self, order_id):
        return {"ok": True, "capture_id": order_id, "status": "FINAL"}

    def refund(self, capture_id, amount, receiver=None, provider=None):
        return {"ok": True, "refund_id": self._next("RFND"), "status": "FINAL"}


def get_gateway(env):
    acct, sec = env.get("NEAR_FACILITATOR_ACCOUNT"), env.get("NEAR_FACILITATOR_KEY")
    if acct and sec:
        providers = json.loads(env.get("NEAR_PROVIDERS", "{}"))
        secrets = json.loads(env.get("NEAR_PROVIDER_SECRETS", "{}"))
        return NearGateway(acct, sec,
                           env.get("NEAR_RPC_URL", "https://rpc.testnet.near.org"),
                           providers, secrets)
    return SimGateway()
