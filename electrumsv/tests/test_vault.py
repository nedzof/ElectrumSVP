import asyncio
import subprocess
import sys
from unittest.mock import Mock

import pytest
from bitcoinx import Address, Tx, TxInput, TxOutput
from electrumsv.bitcoin import scripthash_hex

from electrumsv.app_state import app_state
from electrumsv.constants import RECEIVING_SUBPATH, ScriptType, TransactionOutputFlag
from electrumsv.keystore import from_seed
from electrumsv.networks import Net, SVMainnet
from electrumsv.tests.test_wallet import MockStorage
from electrumsv.transaction import Transaction, TransactionContext, XTxOutput
from electrumsv.vault_contract import CovenantContractRuntime
from electrumsv.wallet import StandardAccount, UTXO, Wallet
class _FakeAsync:
    def event(self):
        return asyncio.Event()

    def spawn_and_wait(self, func):
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
        self.decimal_point = 8

    def base_unit(self):
        return "BSV"


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


def _create_vault_setup(account: StandardAccount, input_value: int=10_000, max_fee: int=200):
    key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 3)
    funded_key, whitelist_key, owner_key = key_rows
    funded_address = account.get_script_template_for_id(funded_key.keyinstance_id).to_string()
    whitelist_address = account.get_script_template_for_id(
        whitelist_key.keyinstance_id).to_string()
    owner_address = account.get_script_template_for_id(owner_key.keyinstance_id).to_string()
    owner_public_key = account.get_public_keys_for_id(owner_key.keyinstance_id)[0].to_hex()

    locking_script = CovenantContractRuntime.build_contract_locking_script(
        owner_public_key, whitelist_address, max_fee)
    account.set_vault_contract_whitelist(
        locking_script, whitelist_address, max_fee, owner_address,
        owner_key.keyinstance_id, owner_public_key)

    funded_utxo = UTXO(
        value=input_value,
        script_pubkey=Address.from_string(funded_address, Net.COIN).to_script(),
        script_type=ScriptType.P2PKH,
        tx_hash=b"\x11" * 32,
        out_index=0,
        keyinstance_id=funded_key.keyinstance_id,
        address=None,
        is_coinbase=False,
        flags=TransactionOutputFlag.NONE,
    )
    lock_tx = account.make_unsigned_transaction(
        [funded_utxo], [XTxOutput(all, locking_script)], Mock(), fixed_fee=max_fee)
    account.sign_transaction(lock_tx, None, TransactionContext())

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
    whitelist_script = Address.from_string(whitelist_address, Net.COIN).to_script()
    return {
        "funded_key": funded_key,
        "whitelist_key": whitelist_key,
        "owner_key": owner_key,
        "funded_address": funded_address,
        "whitelist_address": whitelist_address,
        "owner_address": owner_address,
        "owner_public_key": owner_public_key,
        "locking_script": locking_script,
        "lock_tx": lock_tx,
        "vault_utxo": vault_utxo,
        "whitelist_script": whitelist_script,
        "max_fee": max_fee,
    }


def test_vault_metadata_rejects_owner_binding_mismatch() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 2)
        whitelist_key, owner_key = key_rows
        whitelist_address = account.get_script_template_for_id(
            whitelist_key.keyinstance_id).to_string()
        owner_address = account.get_script_template_for_id(owner_key.keyinstance_id).to_string()
        wrong_owner_public_key = account.get_public_keys_for_id(
            whitelist_key.keyinstance_id)[0].to_hex()

        with pytest.raises(ValueError, match="owner address does not match owner public key"):
            CovenantContractRuntime.build_contract_metadata(
                owner_address, whitelist_address, 200, owner_key.keyinstance_id,
                wrong_owner_public_key)
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_wallet_rejects_mismatched_vault_script_metadata() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 3)
        whitelist_key, owner_key, wrong_whitelist_key = key_rows
        whitelist_address = account.get_script_template_for_id(
            whitelist_key.keyinstance_id).to_string()
        wrong_whitelist_address = account.get_script_template_for_id(
            wrong_whitelist_key.keyinstance_id).to_string()
        owner_address = account.get_script_template_for_id(owner_key.keyinstance_id).to_string()
        owner_public_key = account.get_public_keys_for_id(owner_key.keyinstance_id)[0].to_hex()
        locking_script = CovenantContractRuntime.build_contract_locking_script(
            owner_public_key, whitelist_address, 200)

        with pytest.raises(ValueError, match="does not match the output script"):
            account.set_vault_contract_whitelist(
                locking_script, wrong_whitelist_address, 200, owner_address,
                owner_key.keyinstance_id, owner_public_key)
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_wallet_does_not_promote_legacy_whitelist_entries_to_contract_metadata() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 2)
        whitelist_key, owner_key = key_rows
        whitelist_address = account.get_script_template_for_id(
            whitelist_key.keyinstance_id).to_string()
        owner_public_key = account.get_public_keys_for_id(owner_key.keyinstance_id)[0].to_hex()
        locking_script = CovenantContractRuntime.build_contract_locking_script(
            owner_public_key, whitelist_address, 200)

        wallet._storage.put("vault_contract_whitelist_map", {
            scripthash_hex(locking_script): whitelist_address,
        })

        assert wallet.get_vault_contract_whitelist_for_script(locking_script) == whitelist_address
        metadata = wallet.get_vault_contract_metadata_for_script(locking_script)
        assert metadata is not None
        assert metadata["owner_public_key"] == owner_public_key
        assert metadata["whitelist"] == whitelist_address
        assert metadata["max_fee"] == 200
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_contract_script_metadata_roundtrip() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        setup = _create_vault_setup(account)
        metadata = CovenantContractRuntime.parse_contract_locking_script(setup["locking_script"])
        assert metadata == {
            "version": CovenantContractRuntime.CURRENT_VERSION,
            "contract_type": CovenantContractRuntime.CONTRACT_TYPE,
            "owner_address": setup["owner_address"],
            "owner_public_key": setup["owner_public_key"],
            "whitelist": setup["whitelist_address"],
            "max_fee": setup["max_fee"],
            "owner_keyinstance_id": None,
        }
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_owner_key_advertises_known_vault_script_for_subscription() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        setup = _create_vault_setup(account)
        scripts = account.get_possible_scripts_for_id(setup["owner_key"].keyinstance_id)

        assert (ScriptType.NONE, setup["locking_script"]) in scripts
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_checked_in_artifact_verifier_script() -> None:
    subprocess.run([
        sys.executable,
        "contrib/vault_whitelist_contract/scripts/verify_artifact.py",
    ], check=True)


def test_vault_utxo_survives_wallet_reload_and_can_be_spent() -> None:
    previous_state = _install_fake_app_state()
    storage = MockStorage()
    storage.close = lambda: None
    wallet = Wallet(storage)
    reopened_wallet = None
    try:
        keystore = from_seed(
            "cycle rocket west magnet parrot shuffle foot correct salt library feed song", "")
        account = wallet.create_account_from_keystore(keystore)
        assert isinstance(account, StandardAccount)
        account.requests.check_paid_requests = lambda *args, **kwargs: None

        setup = _create_vault_setup(account)
        lock_tx = setup["lock_tx"]
        wallet.add_transaction(lock_tx.hash(), lock_tx, 0)

        wallet.stop()

        reopened_wallet = Wallet(storage)
        reopened_account = reopened_wallet.get_accounts()[0]
        reopened_account.requests.check_paid_requests = lambda *args, **kwargs: None
        reopened_vault_utxo = reopened_account.get_utxo(lock_tx.hash(), 0)

        assert reopened_vault_utxo is not None
        assert reopened_vault_utxo.script_pubkey == setup["locking_script"]
        assert reopened_vault_utxo.script_type == ScriptType.NONE
        assert reopened_vault_utxo.keyinstance_id == setup["owner_key"].keyinstance_id
        assert reopened_account.get_vault_contract_metadata_for_utxo(reopened_vault_utxo) == {
            "version": CovenantContractRuntime.CURRENT_VERSION,
            "contract_type": CovenantContractRuntime.CONTRACT_TYPE,
            "owner_address": setup["owner_address"],
            "owner_public_key": setup["owner_public_key"],
            "whitelist": setup["whitelist_address"],
            "max_fee": setup["max_fee"],
            "owner_keyinstance_id": setup["owner_key"].keyinstance_id,
        }

        spend_tx = reopened_account.make_unsigned_transaction(
            [reopened_vault_utxo], [XTxOutput(all, setup["whitelist_script"])], Mock(),
            fixed_fee=setup["max_fee"])
        reopened_account.sign_transaction(spend_tx, None, TransactionContext())

        assert spend_tx.is_complete()
        assert spend_tx.outputs[0].script_pubkey == setup["whitelist_script"]
    finally:
        if reopened_wallet is not None and not reopened_wallet._stopped:
            reopened_wallet.stop()
        if wallet is not None and not wallet._stopped:
            wallet.stop()
        app_state.set_proxy(previous_state)


def test_vault_utxo_recovers_after_metadata_loss() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        setup = _create_vault_setup(account)
        lock_tx = setup["lock_tx"]
        wallet.add_transaction(lock_tx.hash(), lock_tx, 0)
        if account.get_utxo(lock_tx.hash(), 0) is None:
            account.process_key_usage(lock_tx.hash(), lock_tx, None)
        wallet._storage.put("vault_contract_whitelist_map", {})
        with wallet.get_transactionoutput_table() as table:
            account._load_txos(list(table.read(key_ids=list(account._keyinstances))))

        recovered_utxo = account.get_utxo(lock_tx.hash(), 0)
        assert recovered_utxo is not None
        assert recovered_utxo.script_pubkey == setup["locking_script"]
        assert recovered_utxo.script_type == ScriptType.NONE

        recovered_metadata = account.get_vault_contract_metadata_for_utxo(recovered_utxo)
        assert recovered_metadata is not None
        assert recovered_metadata["owner_public_key"] == setup["owner_public_key"]
        assert recovered_metadata["whitelist"] == setup["whitelist_address"]
        assert recovered_metadata["owner_keyinstance_id"] == setup["owner_key"].keyinstance_id
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_restored_seed_wallet_recovers_vault_output_from_lock_transaction() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    restored_wallet = None
    try:
        setup = _create_vault_setup(account)
        lock_tx = setup["lock_tx"]

        restored_wallet, restored_account = _create_wallet_account()
        # Mirror the same deterministic key lifecycle so the owner key is available for matching.
        restored_account.get_fresh_keys(RECEIVING_SUBPATH, 3)
        restored_account.requests.check_paid_requests = lambda *args, **kwargs: None

        restored_wallet.add_transaction(lock_tx.hash(), lock_tx, 0)
        recovered_utxo = restored_account.get_utxo(lock_tx.hash(), 0)

        assert recovered_utxo is not None
        assert recovered_utxo.script_type == ScriptType.NONE
        assert recovered_utxo.script_pubkey == setup["locking_script"]
        recovered_metadata = restored_account.get_vault_contract_metadata_for_utxo(recovered_utxo)
        assert recovered_metadata is not None
        assert recovered_metadata["owner_public_key"] == setup["owner_public_key"]
        assert recovered_metadata["whitelist"] == setup["whitelist_address"]
        assert recovered_metadata["max_fee"] == setup["max_fee"]
    finally:
        if restored_wallet is not None and not restored_wallet._stopped:
            restored_wallet.stop()
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_vault_spend_fails_consensus_verification_if_outputs_are_mutated() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        setup = _create_vault_setup(account)
        tx = account.make_unsigned_transaction(
            [setup["vault_utxo"]], [XTxOutput(all, setup["whitelist_script"])], Mock(),
            fixed_fee=setup["max_fee"])
        account.sign_transaction(tx, None, TransactionContext())

        bitcoinx_tx = Tx(
            tx.version,
            [TxInput(txin.prev_hash, txin.prev_idx, txin.script_sig, txin.sequence,
                TxOutput(txin.value, txin.prev_script)) for txin in tx.inputs],
            [TxOutput(output.value, output.script_pubkey) for output in tx.outputs],
            tx.locktime)
        bitcoinx_tx.verify_inputs()

        mutated_tx = Tx(
            tx.version,
            [TxInput(txin.prev_hash, txin.prev_idx, txin.script_sig, txin.sequence,
                TxOutput(txin.value, txin.prev_script)) for txin in tx.inputs],
            [TxOutput(output.value - 1, output.script_pubkey) for output in tx.outputs],
            tx.locktime)
        with pytest.raises(Exception, match="failed to verify"):
            mutated_tx.verify_inputs()
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_vault_spend_rejects_non_whitelist_outputs() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        setup = _create_vault_setup(account)
        key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 1)
        extra_address = account.get_script_template_for_id(key_rows[0].keyinstance_id).to_string()
        extra_script = Address.from_string(extra_address, Net.COIN).to_script()

        tx = account.make_unsigned_transaction(
            [setup["vault_utxo"]],
            [XTxOutput(1_000, setup["whitelist_script"]), XTxOutput(500, extra_script)],
            Mock(),
            fixed_fee=setup["max_fee"])

        with pytest.raises(ValueError, match="cannot include non-whitelist outputs"):
            account.sign_transaction(tx, None, TransactionContext())
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_vault_spend_rejects_multiple_vault_inputs() -> None:
    previous_state = _install_fake_app_state()
    wallet, account = _create_wallet_account()
    try:
        first = _create_vault_setup(account, input_value=10_000, max_fee=200)
        second = _create_vault_setup(account, input_value=12_000, max_fee=200)

        tx = account.make_unsigned_transaction(
            [first["vault_utxo"], second["vault_utxo"]],
            [XTxOutput(all, first["whitelist_script"])],
            Mock(),
            fixed_fee=first["max_fee"])

        with pytest.raises(ValueError, match="support exactly one vault UTXO"):
            account.sign_transaction(tx, None, TransactionContext())
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_vault_spend_end_to_end() -> None:
    fake_state = _FakeAppState()
    previous_state = app_state._proxy
    app_state.set_proxy(fake_state)
    Net.set_to(SVMainnet)
    wallet = None

    try:
        wallet, account = _create_wallet_account()

        # Allocate all roles up front so this test models a real wallet lifecycle with
        # distinct funded, whitelist and owner keys.
        key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 3)
        funded_key, whitelist_key, owner_key = key_rows
        assert len({funded_key.keyinstance_id, whitelist_key.keyinstance_id,
            owner_key.keyinstance_id}) == 3

        funded_address = account.get_script_template_for_id(
            funded_key.keyinstance_id).to_string()
        whitelist_address = account.get_script_template_for_id(
            whitelist_key.keyinstance_id).to_string()
        owner_address = account.get_script_template_for_id(owner_key.keyinstance_id).to_string()
        owner_public_key = account.get_public_keys_for_id(owner_key.keyinstance_id)[0].to_hex()
        assert len({funded_address, whitelist_address, owner_address}) == 3

        max_fee = 200
        input_value = 10_000
        locking_script = CovenantContractRuntime.build_contract_locking_script(
            owner_public_key, whitelist_address, max_fee)
        account.set_vault_contract_whitelist(
            locking_script, whitelist_address, max_fee, owner_address,
            owner_key.keyinstance_id, owner_public_key)

        utxo = UTXO(
            value=input_value,
            script_pubkey=Address.from_string(funded_address, Net.COIN).to_script(),
            script_type=ScriptType.P2PKH,
            tx_hash=b"\x11" * 32,
            out_index=0,
            keyinstance_id=funded_key.keyinstance_id,
            address=None,
            is_coinbase=False,
            flags=TransactionOutputFlag.NONE,
        )
        lock_tx = account.make_unsigned_transaction(
            [utxo], [XTxOutput(all, locking_script)], Mock(), fixed_fee=max_fee)
        account.sign_transaction(lock_tx, None, TransactionContext())

        assert lock_tx.is_complete()
        assert len(lock_tx.inputs) == 1
        assert lock_tx.inputs[0].script_type == ScriptType.P2PKH
        assert lock_tx.outputs[0].script_pubkey == locking_script
        assert lock_tx.outputs[0].value == input_value - max_fee

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
        whitelist_script = Address.from_string(whitelist_address, Net.COIN).to_script()
        tx = account.make_unsigned_transaction(
            [vault_utxo], [XTxOutput(all, whitelist_script)], Mock(), fixed_fee=max_fee)

        account.sign_transaction(tx, None, TransactionContext())

        assert tx.is_complete()
        assert len(tx.inputs) == 1
        txin = tx.inputs[0]
        assert txin.script_type == ScriptType.NONE
        assert txin.keyinstance_id == owner_key.keyinstance_id
        assert len(txin.contract_args) == 3
        assert len(tx.outputs) == 1
        assert tx.outputs[0].script_pubkey == whitelist_script
        assert tx.outputs[0].value == lock_tx.outputs[0].value - max_fee

        reparsed = Transaction.from_extended_bytes(tx.to_bytes())
        reparsed_input = reparsed.inputs[0]
        assert reparsed_input.script_type == ScriptType.NONE
        assert len(reparsed_input.signatures) == 1
        assert len(reparsed_input.contract_args) == 3
        assert reparsed.outputs[0].script_pubkey == whitelist_script
        assert reparsed.outputs[0].value == lock_tx.outputs[0].value - max_fee
    finally:
        if wallet is not None and not wallet._stopped:
            wallet.stop()
        app_state.set_proxy(previous_state)
