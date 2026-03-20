import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget

from electrumsv.app_state import app_state
from electrumsv.constants import RECEIVING_SUBPATH
from electrumsv.networks import Net, SVMainnet
from electrumsv.tests.test_benford import _make_utxo
from electrumsv.tests.test_vault import _create_wallet_account, _install_fake_app_state
from electrumsv.gui.qt.benford_tab import BenfordTab
from electrumsv.wallet_database.cache import TxData
from electrumsv.transaction import TransactionContext

_QT_APP = None


class _AccountSignalHost(QObject):
    signal = pyqtSignal(int, object)


class _DummyConfig:
    def get(self, key, default=None):
        return default

    def fee_per_kb(self):
        return 1000

    def estimate_fee(self, size):
        return max(1, (size + 999) // 1000)


class _DummyMainWindow(QWidget):
    def __init__(self, wallet, account):
        super().__init__()
        self._wallet = wallet
        self._account = account
        self.config = _DummyConfig()
        signal_host = _AccountSignalHost()
        self.account_change_signal = signal_host.signal
        self._signal_host = signal_host
        self.question_prompts = []
        self.error_messages = []
        self.info_messages = []
        self.broadcasts = []
        self.password_requests = []

    def question(self, message):
        self.question_prompts.append(message)
        return True

    def show_error(self, message):
        self.error_messages.append(message)

    def show_message(self, message):
        self.info_messages.append(message)

    def password_dialog(self, message, parent=None, fields=None):
        self.password_requests.append(message)
        return ""

    def sign_tx_with_password(self, tx, callback, password, window=None, tx_context=None):
        self._account.sign_transaction(tx, None, tx_context=TransactionContext())
        callback(True)

    def broadcast_transaction(self, account, tx, success_text=None, window=None):
        self.broadcasts.append((account, tx, success_text))
        return tx.txid()

    def show_transaction(self, account, tx):
        raise AssertionError("show_transaction should not be used for a signed Benford split")


def _ensure_qapplication():
    global _QT_APP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _QT_APP = app
    return app


def test_benford_tab_builds_preview_and_broadcasts_transaction() -> None:
    _ensure_qapplication()
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet._storage.put("stored_height", 10_000)
        key_rows = account.get_fresh_keys(RECEIVING_SUBPATH, 2)
        created_utxos = [
            _make_utxo(account, key_rows[0].keyinstance_id, 60_000, 11),
            _make_utxo(account, key_rows[1].keyinstance_id, 45_000, 12),
        ]

        metadata_map = {utxo.tx_hash: TxData(height=9_500) for utxo in created_utxos}
        account.get_utxos = lambda **kwargs: list(created_utxos)
        account.get_transaction_metadata = lambda tx_hash: metadata_map[tx_hash]
        account.is_frozen_key = lambda key_id: False

        main_window = _DummyMainWindow(wallet, account)
        tab = BenfordTab(main_window)
        main_window.account_change_signal.emit(account.get_id(), account)

        tab._privacy_slider.setValue(4)
        tab._min_split_value.setValue(2_000)
        tab._max_split_value.setValue(20_000)
        tab._on_split_clicked()

        preview_text = tab._preview_edit.toPlainText()
        assert "Selected inputs" in preview_text
        assert "Benford MAD" in preview_text
        assert "Output amounts" in preview_text
        assert len(main_window.question_prompts) == 1
        assert len(main_window.password_requests) == 1
        assert len(main_window.broadcasts) == 1
        broadcast_tx = main_window.broadcasts[0][1]
        assert broadcast_tx.is_complete()
        assert max(output.value for output in broadcast_tx.outputs) <= 20_000
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_benford_tab_random_button_prefills_ranges() -> None:
    _ensure_qapplication()
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        main_window = _DummyMainWindow(wallet, account)
        tab = BenfordTab(main_window)
        main_window.account_change_signal.emit(account.get_id(), account)

        tab._privacy_slider.setValue(4)
        random.seed(7)
        tab._on_randomize_clicked()

        assert tab._min_age_days.value() >= 0
        assert tab._max_age_days.value() >= tab._min_age_days.value()
        assert tab._min_utxo_value.value() >= 0
        assert tab._max_utxo_value.value() == 0 or \
            tab._max_utxo_value.value() >= tab._min_utxo_value.value()
        assert tab._min_split_value.value() > 0
        assert tab._max_split_value.value() >= tab._min_split_value.value()
        assert tab._preview_edit.toPlainText() == ""
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)
