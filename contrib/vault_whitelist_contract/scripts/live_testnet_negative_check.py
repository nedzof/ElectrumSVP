#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock

import requests

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from electrumsv.app_state import app_state
from electrumsv.constants import RECEIVING_SUBPATH, ScriptType, TransactionOutputFlag
from electrumsv.keystore import from_seed
from electrumsv.networks import Net, SVTestnet
from electrumsv.tests.test_wallet import MockStorage
from electrumsv.transaction import TransactionContext, XTxOutput
from electrumsv.vault_contract import CovenantContractRuntime
from electrumsv.wallet import StandardAccount, UTXO, Wallet
from electrumsv.wallet_database.tables import AccountRow


FAUCET_URL = "https://witnessonchain.com/v1/faucet/tbsv"
WOC_BROADCAST_URL = "https://api.whatsonchain.com/v1/bsv/test/tx/raw"
WOC_UNCONFIRMED_UNSPENT = (
    "https://api.whatsonchain.com/v1/bsv/test/address/{address}/unconfirmed/unspent"
)


class _FakeAsync:
    def event(self):
        import asyncio
        return asyncio.Event()

    def spawn_and_wait(self, func):
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return asyncio.run(func())
        if asyncio.iscoroutine(func):
            return asyncio.run(func)
        return func()


class _FakeAppState:
    def __init__(self):
        self.async_ = _FakeAsync()
        self.app = Mock()
        self.fx = None


def _install_fake_app_state():
    fake_state = _FakeAppState()
    previous_state = app_state._proxy
    app_state.set_proxy(fake_state)
    return previous_state


def _create_wallet_account() -> tuple[Wallet, StandardAccount]:
    storage = MockStorage()
    storage.close = lambda: None
    wallet = Wallet(storage)
    keystore = from_seed(
        "cycle rocket west magnet parrot shuffle foot correct salt library feed song", "")
    account = wallet.create_account_from_keystore(keystore)
    assert isinstance(account, StandardAccount)
    account.requests.check_paid_requests = lambda *args, **kwargs: None
    return wallet, account


def _request_faucet(address: str) -> dict:
    response = requests.post(FAUCET_URL, json={"address": address, "channel": "scrypt.io"},
        timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"faucet request failed: {payload}")
    return payload


def _get_unspent(address: str) -> dict:
    response = requests.get(WOC_UNCONFIRMED_UNSPENT.format(address=address), timeout=30)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result", [])
    if not result:
        raise RuntimeError(f"no unspent outputs found for {address}: {payload}")
    return result[0]


def _find_funded_triplet(account: StandardAccount):
    keys = account.get_fresh_keys(RECEIVING_SUBPATH, 24)
    for start_index in range(7, len(keys) - 2):
        funded_key, whitelist_key, owner_key = keys[start_index:start_index + 3]
        funded_pub = account.get_public_keys_for_id(funded_key.keyinstance_id)[0]
        funded_address = str(funded_pub.to_address(network=Net.COIN))
        try:
            utxo = _get_unspent(funded_address)
            return funded_key, whitelist_key, owner_key, None, utxo
        except Exception:
            pass
        try:
            faucet_payload = _request_faucet(funded_address)
            utxo = _get_unspent(funded_address)
            return funded_key, whitelist_key, owner_key, faucet_payload, utxo
        except Exception:
            continue
    raise RuntimeError("could not obtain a funded testnet UTXO from existing addresses or faucet")


def _broadcast(tx_hex: str) -> requests.Response:
    return requests.post(WOC_BROADCAST_URL, json={"txhex": tx_hex}, timeout=30)


def main() -> None:
    Net.set_to(SVTestnet)
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        funded_key, whitelist_key, owner_key, faucet_payload, utxo = _find_funded_triplet(account)
        funded_pub = account.get_public_keys_for_id(funded_key.keyinstance_id)[0]
        whitelist_pub = account.get_public_keys_for_id(whitelist_key.keyinstance_id)[0]
        owner_pub = account.get_public_keys_for_id(owner_key.keyinstance_id)[0]

        funded_address = str(funded_pub.to_address(network=Net.COIN))
        whitelist_address = str(whitelist_pub.to_address(network=Net.COIN))
        owner_address = str(owner_pub.to_address(network=Net.COIN))
        owner_public_key = owner_pub.to_hex()
        max_fee = 500

        locking_script = CovenantContractRuntime.build_contract_locking_script(
            owner_public_key, whitelist_address, max_fee)
        account.set_vault_contract_whitelist(locking_script, whitelist_address, max_fee,
            owner_address, owner_key.keyinstance_id, owner_public_key)

        funded_utxo = UTXO(
            value=utxo["value"],
            script_pubkey=funded_pub.to_address(network=Net.COIN).to_script(),
            script_type=ScriptType.P2PKH,
            tx_hash=bytes.fromhex(utxo["tx_hash"])[::-1],
            out_index=utxo["tx_pos"],
            keyinstance_id=funded_key.keyinstance_id,
            address=None,
            is_coinbase=False,
            flags=TransactionOutputFlag.NONE,
        )
        lock_tx = account.make_unsigned_transaction(
            [funded_utxo], [XTxOutput(all, locking_script)], Mock(), fixed_fee=max_fee)
        account.sign_transaction(lock_tx, None, TransactionContext())

        lock_response = _broadcast(lock_tx.to_hex())
        lock_response.raise_for_status()
        lock_txid = json.loads(lock_response.text)

        vault_utxo = UTXO(
            value=lock_tx.outputs[0].value,
            script_pubkey=locking_script,
            script_type=ScriptType.NONE,
            tx_hash=lock_tx.hash(),
            out_index=0,
            keyinstance_id=owner_key.keyinstance_id,
            address=None,
            is_coinbase=False,
            flags=TransactionOutputFlag.NONE,
        )
        whitelist_script = whitelist_pub.to_address(network=Net.COIN).to_script()
        spend_tx = account.make_unsigned_transaction(
            [vault_utxo], [XTxOutput(all, whitelist_script)], Mock(), fixed_fee=max_fee)
        account.sign_transaction(spend_tx, None, TransactionContext())

        good_hex = spend_tx.to_hex()
        good_txid = spend_tx.txid()
        spend_tx.outputs[0].value -= 1
        bad_response = _broadcast(spend_tx.to_hex())
        if bad_response.status_code == 200:
            raise RuntimeError(f"malformed spend unexpectedly accepted: {bad_response.text}")

        bad_text = bad_response.text
        if "verify" not in bad_text and "script" not in bad_text and "CHECK" not in bad_text:
            raise RuntimeError(f"malformed spend failed for unexpected reason: {bad_text}")

        good_response = _broadcast(good_hex)
        good_response.raise_for_status()
        confirmed_good_txid = json.loads(good_response.text)

        print(json.dumps({
            "funded_address": funded_address,
            "whitelist_address": whitelist_address,
            "owner_address": owner_address,
            "faucet_txid": faucet_payload["txid"] if faucet_payload is not None else None,
            "lock_txid": lock_txid,
            "malformed_spend_txid": good_txid,
            "malformed_rejection_status": bad_response.status_code,
            "malformed_rejection_body": bad_text,
            "recovery_spend_txid": confirmed_good_txid,
        }, indent=2))
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


if __name__ == "__main__":
    main()
