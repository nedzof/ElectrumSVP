import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtWidgets import QApplication, QWidget

from electrumsv.app_state import app_state
from electrumsv.constants import WalletSettings
from electrumsv.networks import Net, SVMainnet
from electrumsv.tests.test_vault import _create_wallet_account, _install_fake_app_state
from electrumsv.gui.qt.send_view import SendView
from electrumsv.transaction import XTxOutput
from electrumsv.vault_contract import CovenantContractRuntime

_QT_APP = None


class _DummyLineEdit:
    def __init__(self, text: str="") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:
        self._text = value


class _DummyTextEdit:
    def __init__(self) -> None:
        self.plain_text = ""
        self.read_only = False

    def setPlainText(self, value: str) -> None:
        self.plain_text = value

    def setReadOnly(self, value: bool) -> None:
        self.read_only = value


class _DummyCheckbox:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _DummyPublicKey:
    def __init__(self, hex_text: str) -> None:
        self._hex_text = hex_text

    def to_hex(self) -> str:
        return self._hex_text


class _DummyAccount:
    def __init__(self, whitelist_by_utxo, owner_public_key: str) -> None:
        self._whitelist_by_utxo = whitelist_by_utxo
        self._owner_public_key = owner_public_key
        self.set_vault_contract_whitelist = Mock()

    def get_vault_contract_whitelist_for_utxo(self, utxo):
        return self._whitelist_by_utxo.get(utxo)

    def get_public_keys_for_id(self, keyinstance_id):
        return [_DummyPublicKey(self._owner_public_key)]


class _DummyView:
    def __init__(self, account: _DummyAccount) -> None:
        self._account = account
        self._errors = []
        self._vault_whitelist_e = _DummyLineEdit()
        self._vault_owner_e = _DummyLineEdit()
        self._vault_max_fee_e = _DummyLineEdit()
        self._vault_lock_checkbox = _DummyCheckbox(True)
        self._vault_owner_keyinstance_id = None
        self._payto_e = _DummyTextEdit()
        self.update_fee = Mock()

    def _report_vault_send_error(self, message: str) -> None:
        self._errors.append(message)

    def _get_vault_max_fee(self):
        return SendView._get_vault_max_fee(self)


class _WalletSettingSignal(QObject):
    signal = pyqtSignal(object, object)


class _DummyConfig:
    def get(self, key, default=None):
        return default


class _DummyMainWindow(QWidget):
    def __init__(self, wallet):
        super().__init__()
        self._wallet = wallet
        self.network = object()
        self.config = _DummyConfig()
        self._signal_host = _WalletSettingSignal()
        self.wallet_setting_changed_signal = self._signal_host.signal
        self.error_messages = []

    def reference(self):
        return self

    def connect_fields(self, *args, **kwargs):
        return None

    def refresh_wallet_display(self):
        return None

    def show_error(self, message):
        self.error_messages.append(message)


def _ensure_qapplication():
    global _QT_APP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _QT_APP = app
    return app


def test_get_vault_send_plan_rejects_mixed_regular_and_vault_utxos() -> None:
    vault_utxo = object()
    regular_utxo = object()
    account = _DummyAccount({vault_utxo: "1LQoWist8KkaUXSPKZHNvEyfrEkPHzSsCd"}, "02" + "11" * 32)
    view = _DummyView(account)

    plan = SendView._get_vault_send_plan(view, [vault_utxo, regular_utxo], strict=True)

    assert plan is None
    assert view._errors == ["Vault UTXOs cannot be combined with regular UTXOs in one transaction"]


def test_register_vault_lock_outputs_uses_owner_public_key() -> None:
    output = XTxOutput(1000, b"\x51")
    account = _DummyAccount({}, "03" + "22" * 32)
    view = _DummyView(account)
    view._vault_whitelist_e.setText("1LQoWist8KkaUXSPKZHNvEyfrEkPHzSsCd")
    view._vault_owner_e.setText("1C6Rc3w25VHud3dLDamutaqfKWqhrLRTaD")
    view._vault_max_fee_e.setText("250")
    view._vault_owner_keyinstance_id = 17

    SendView._register_vault_lock_outputs(view, [output])

    account.set_vault_contract_whitelist.assert_called_once_with(
        output.script_pubkey, "1LQoWist8KkaUXSPKZHNvEyfrEkPHzSsCd", 250,
        "1C6Rc3w25VHud3dLDamutaqfKWqhrLRTaD", 17, "03" + "22" * 32)
    assert view._errors == []


def test_update_vault_lock_script_reports_contract_build_failures(monkeypatch) -> None:
    account = _DummyAccount({}, "02" + "33" * 32)
    view = _DummyView(account)
    view._vault_whitelist_e.setText("1LQoWist8KkaUXSPKZHNvEyfrEkPHzSsCd")
    view._vault_max_fee_e.setText("300")
    view._vault_owner_keyinstance_id = 9

    def _raise(*args, **kwargs):
        raise RuntimeError("contract build failed")

    monkeypatch.setattr(
        "electrumsv.gui.qt.send_view.CovenantContractRuntime.build_contract_locking_script_text",
        _raise)

    SendView._update_vault_lock_script(view)

    assert view._errors == ["contract build failed"]
    assert view._payto_e.plain_text == ""
    view.update_fee.assert_not_called()


def test_send_view_vault_toggle_populates_real_widgets() -> None:
    _ensure_qapplication()
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet.set_boolean_setting(WalletSettings.ADD_SV_OUTPUT, False)
        main_window = _DummyMainWindow(wallet)
        view = SendView(main_window, account.get_id())

        view._vault_lock_checkbox.setChecked(True)
        view._on_vault_lock_toggled(Qt.Checked)

        assert view._vault_whitelist_e.text().strip()
        assert view._vault_owner_e.text().strip()
        assert view._vault_owner_keyinstance_id is not None
        assert view._payto_e.toPlainText().startswith("bitcoin-script:")
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_send_view_vault_new_button_allocates_distinct_keys() -> None:
    _ensure_qapplication()
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet.set_boolean_setting(WalletSettings.ADD_SV_OUTPUT, False)
        main_window = _DummyMainWindow(wallet)
        view = SendView(main_window, account.get_id())

        view._vault_lock_checkbox.setChecked(True)
        view._on_vault_lock_toggled(Qt.Checked)
        first_whitelist = view._vault_whitelist_e.text().strip()
        first_owner_id = view._vault_owner_keyinstance_id

        view._refresh_vault_whitelist()
        second_whitelist = view._vault_whitelist_e.text().strip()
        second_owner_id = view._vault_owner_keyinstance_id

        assert second_whitelist
        assert first_whitelist != second_whitelist
        assert first_owner_id is not None
        assert second_owner_id is not None
        assert first_owner_id != second_owner_id
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)


def test_send_view_registers_vault_metadata_with_real_view() -> None:
    _ensure_qapplication()
    previous_state = _install_fake_app_state()
    Net.set_to(SVMainnet)
    wallet, account = _create_wallet_account()
    try:
        wallet.set_boolean_setting(WalletSettings.ADD_SV_OUTPUT, False)
        main_window = _DummyMainWindow(wallet)
        view = SendView(main_window, account.get_id())

        view._vault_lock_checkbox.setChecked(True)
        view._on_vault_lock_toggled(Qt.Checked)
        max_fee = int(view._vault_max_fee_e.text())
        owner_public_key = account.get_public_keys_for_id(view._vault_owner_keyinstance_id)[0].to_hex()
        locking_script = CovenantContractRuntime.build_contract_locking_script(
            owner_public_key, view._vault_whitelist_e.text().strip(), max_fee)

        view._register_vault_lock_outputs([XTxOutput(1500, locking_script)])

        metadata = account.get_vault_contract_metadata_for_script(locking_script)
        assert metadata is not None
        assert metadata["whitelist"] == view._vault_whitelist_e.text().strip()
        assert metadata["owner_keyinstance_id"] == view._vault_owner_keyinstance_id
    finally:
        wallet.stop()
        app_state.set_proxy(previous_state)
