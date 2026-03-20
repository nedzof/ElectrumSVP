import asyncio
from unittest.mock import Mock

from bitcoinx import Address

from electrumsv.app_state import app_state
from electrumsv.constants import RECEIVING_SUBPATH, ScriptType, TransactionOutputFlag
from electrumsv.keystore import from_seed
from electrumsv.networks import Net, SVMainnet
from electrumsv.tests.test_wallet import MockStorage
from electrumsv.transaction import Transaction, TransactionContext, XTxOutput
from electrumsv.vault_contract import CovenantContractRuntime
from electrumsv.wallet import StandardAccount, UTXO, Wallet
from electrumsv.wallet_database.tables import AccountRow


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


def test_vault_spend_end_to_end() -> None:
    fake_state = _FakeAppState()
    previous_state = app_state._proxy
    app_state.set_proxy(fake_state)
    Net.set_to(SVMainnet)
    wallet = None

    try:
        storage = MockStorage()
        storage.close = lambda: None
        wallet = Wallet(storage)
        keystore = from_seed(
            "cycle rocket west magnet parrot shuffle foot correct salt library feed song", "")
        masterkey_row = wallet.create_masterkey_from_keystore(keystore)
        account_row = AccountRow(1, masterkey_row.masterkey_id, ScriptType.P2PKH, "vault-test")
        account = StandardAccount(wallet, account_row, [], [])
        account.requests.check_paid_requests = lambda *args, **kwargs: None
        wallet.register_account(account.get_id(), account)

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
