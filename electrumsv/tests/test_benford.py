from unittest.mock import Mock

from bitcoinx import Address

from electrumsv.app_state import app_state
from electrumsv.benford import BenfordSettings, create_benford_plan, filter_benford_utxos
from electrumsv.constants import RECEIVING_SUBPATH, ScriptType, TransactionOutputFlag
from electrumsv.networks import Net, SVMainnet
from electrumsv.tests.test_vault import _create_wallet_account, _install_fake_app_state
from electrumsv.wallet import UTXO
from electrumsv.wallet_database.cache import TxData


def _make_utxo(account, keyinstance_id: int, value: int, token: int) -> UTXO:
    address = account.get_script_template_for_id(keyinstance_id).to_string()
    return UTXO(
        value=value,
        script_pubkey=Address.from_string(address, Net.COIN).to_script(),
        script_type=ScriptType.P2PKH,
        tx_hash=bytes([token]) * 32,
        out_index=0,
        keyinstance_id=keyinstance_id,
        address=None,
        is_coinbase=False,
        flags=TransactionOutputFlag.NONE,
    )


def test_filter_benford_utxos_respects_age_and_size_constraints() -> None:
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet._storage.put("stored_height", 10_000)
        keys = account.get_fresh_keys(RECEIVING_SUBPATH, 3)
        young_utxo = _make_utxo(account, keys[0].keyinstance_id, 2_000, 1)
        middle_utxo = _make_utxo(account, keys[1].keyinstance_id, 8_000, 2)
        old_utxo = _make_utxo(account, keys[2].keyinstance_id, 30_000, 3)
        metadata_map = {
            young_utxo.tx_hash: TxData(height=9_950),
            middle_utxo.tx_hash: TxData(height=9_600),
            old_utxo.tx_hash: TxData(height=8_000),
        }
        account.get_transaction_metadata = lambda tx_hash: metadata_map[tx_hash]

        settings = BenfordSettings(min_age_days=2, max_age_days=5, min_utxo_value=5_000,
            max_utxo_value=20_000)
        filtered = filter_benford_utxos(account, settings, [young_utxo, middle_utxo, old_utxo])

        assert filtered == [middle_utxo]
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


class _DummyConfig:
    def get(self, key, default=None):
        return default

    def fee_per_kb(self):
        return 1000

    def estimate_fee(self, size):
        return max(1, (size + 999) // 1000)


def test_create_benford_plan_builds_self_split_transaction() -> None:
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet._storage.put("stored_height", 10_000)
        keys = account.get_fresh_keys(RECEIVING_SUBPATH, 2)
        utxos = [
            _make_utxo(account, keys[0].keyinstance_id, 60_000, 4),
            _make_utxo(account, keys[1].keyinstance_id, 45_000, 5),
        ]
        metadata_map = {utxo.tx_hash: TxData(height=9_500) for utxo in utxos}
        account.get_utxos = lambda **kwargs: list(utxos)
        account.get_transaction_metadata = lambda tx_hash: metadata_map[tx_hash]
        account.is_frozen_key = lambda key_id: False

        plan = create_benford_plan(account, _DummyConfig(), BenfordSettings(privacy_level=4))

        assert len(plan.utxos) == 2
        assert len(plan.output_values) >= 2
        assert sum(plan.output_values) + plan.tx.get_fee() == sum(utxo.value for utxo in utxos)
        assert len({output.script_pubkey.to_bytes() for output in plan.tx.outputs}) == \
            len(plan.tx.outputs)
        assert len(plan.first_digit_counts) >= 2
        assert plan.benford_mad >= 0.0
        assert 1 in plan.first_digit_ratios
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_create_benford_plan_respects_maximum_split_value() -> None:
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet._storage.put("stored_height", 10_000)
        keys = account.get_fresh_keys(RECEIVING_SUBPATH, 2)
        utxos = [
            _make_utxo(account, keys[0].keyinstance_id, 80_000, 6),
            _make_utxo(account, keys[1].keyinstance_id, 70_000, 7),
        ]
        metadata_map = {utxo.tx_hash: TxData(height=9_500) for utxo in utxos}
        account.get_utxos = lambda **kwargs: list(utxos)
        account.get_transaction_metadata = lambda tx_hash: metadata_map[tx_hash]
        account.is_frozen_key = lambda key_id: False

        plan = create_benford_plan(account, _DummyConfig(),
            BenfordSettings(privacy_level=2, max_split_value=20_000))

        assert max(plan.output_values) <= 20_000
        assert len(plan.output_values) > 6
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)
