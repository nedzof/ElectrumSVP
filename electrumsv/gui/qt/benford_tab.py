import weakref
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QSlider, QSpinBox, QVBoxLayout, QWidget)

from electrumsv.benford import BenfordSettings, create_benford_plan, format_plan_preview
from electrumsv.exceptions import NotEnoughFunds
from electrumsv.i18n import _
from electrumsv.logs import logs
from electrumsv.transaction import TransactionContext
from electrumsv.wallet import AbstractAccount

from .main_window import ElectrumWindow
from .util import EnterButton, HelpDialogButton


logger = logs.get_logger("benford-tab")


class BenfordTab(QWidget):
    def __init__(self, main_window: ElectrumWindow) -> None:
        super().__init__()

        self._main_window = weakref.proxy(main_window)
        self._wallet = main_window._wallet
        self._account: Optional[AbstractAccount] = None
        self._account_id: Optional[int] = None
        self._last_preview_text = ""

        self._main_window.account_change_signal.connect(self._on_account_change)
        self._create_layout()
        self._update_state()

    def _create_layout(self) -> None:
        self._intro_label = QLabel(_(
            "Split your own coins into fresh wallet destinations using varied output amounts that "
            "approximate Benford-style leading digits."
        ))
        self._intro_label.setWordWrap(True)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)

        self._privacy_value_label = QLabel()
        self._privacy_slider = QSlider(Qt.Horizontal)
        self._privacy_slider.setMinimum(1)
        self._privacy_slider.setMaximum(5)
        self._privacy_slider.setValue(3)
        self._privacy_slider.valueChanged.connect(self._on_privacy_level_changed)

        self._min_age_days = QSpinBox()
        self._min_age_days.setRange(0, 3650)
        self._min_age_days.setSuffix(_(" days"))

        self._max_age_days = QSpinBox()
        self._max_age_days.setRange(0, 3650)
        self._max_age_days.setSuffix(_(" days"))

        self._min_utxo_value = QSpinBox()
        self._min_utxo_value.setRange(0, 2_100_000_000)
        self._min_utxo_value.setSingleStep(1000)
        self._min_utxo_value.setSuffix(_(" sats"))

        self._max_utxo_value = QSpinBox()
        self._max_utxo_value.setRange(0, 2_100_000_000)
        self._max_utxo_value.setSingleStep(1000)
        self._max_utxo_value.setSuffix(_(" sats"))

        privacy_row = QHBoxLayout()
        privacy_row.addWidget(self._privacy_slider, 1)
        privacy_row.addWidget(self._privacy_value_label, 0)

        filters_box = QGroupBox(_("Filters"))
        filters_form = QFormLayout()
        filters_form.addRow(_("Privacy level"), privacy_row)
        filters_form.addRow(_("Minimum UTXO age"), self._min_age_days)
        filters_form.addRow(_("Maximum UTXO age"), self._max_age_days)
        filters_form.addRow(_("Minimum UTXO size"), self._min_utxo_value)
        filters_form.addRow(_("Maximum UTXO size"), self._max_utxo_value)
        filters_box.setLayout(filters_form)

        self._preview_edit = QPlainTextEdit()
        self._preview_edit.setReadOnly(True)
        self._preview_edit.setMinimumHeight(240)

        preview_box = QGroupBox(_("Preview"))
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self._preview_edit)
        preview_box.setLayout(preview_layout)

        self._action_button = EnterButton(_("Analyze and Split"), self._on_split_clicked)
        self._help_button = HelpDialogButton(self, "misc", "coinsplitting-tab", _("Help"))

        actions_row = QGridLayout()
        actions_row.addWidget(self._action_button, 0, 0, 1, 1, Qt.AlignLeft)
        actions_row.addWidget(self._help_button, 0, 1, 1, 1, Qt.AlignLeft)
        actions_row.setColumnStretch(2, 1)

        layout = QVBoxLayout()
        layout.addWidget(self._intro_label)
        layout.addWidget(self._status_label)
        layout.addWidget(filters_box)
        layout.addWidget(preview_box, 1)
        layout.addLayout(actions_row)
        self.setLayout(layout)

        self._on_privacy_level_changed(self._privacy_slider.value())

    def _on_account_change(self, new_account_id: int, new_account: AbstractAccount) -> None:
        self._account_id = new_account_id
        self._account = new_account
        self._update_state()

    def _on_privacy_level_changed(self, privacy_level: int) -> None:
        self._privacy_value_label.setText(str(privacy_level))

    def _get_settings(self) -> BenfordSettings:
        return BenfordSettings(
            privacy_level=self._privacy_slider.value(),
            min_age_days=self._min_age_days.value(),
            max_age_days=self._max_age_days.value(),
            min_utxo_value=self._min_utxo_value.value(),
            max_utxo_value=self._max_utxo_value.value(),
        )

    def _update_state(self) -> None:
        if self._account is None:
            self._status_label.setText(_("No active account."))
            self._action_button.setEnabled(False)
            return
        if self._account.is_watching_only():
            self._status_label.setText(_("Watching-only accounts cannot create Benford splits."))
            self._action_button.setEnabled(False)
            return
        if not self._account.can_spend():
            self._status_label.setText(_("This account cannot sign Benford split transactions."))
            self._action_button.setEnabled(False)
            return

        self._status_label.setText(_("Confirmed, mature, unfrozen coins matching the filters will "
            "be split into fresh destinations in this wallet."))
        self._action_button.setEnabled(True)

    def _on_split_clicked(self) -> None:
        if self._account is None:
            self._main_window.show_error(_("No active account."))
            return

        try:
            plan = create_benford_plan(self._account, self._main_window.config, self._get_settings())
        except NotEnoughFunds:
            self._preview_edit.clear()
            self._main_window.show_message(_("No confirmed spendable coins matched the current "
                "Benford filters."))
            return
        except Exception as exc:
            self._preview_edit.clear()
            self._main_window.show_error(str(exc))
            return

        preview_text = format_plan_preview(plan)
        self._last_preview_text = preview_text
        self._preview_edit.setPlainText(preview_text)

        prompt = "\n".join([
            _("Review the Benford split preview in this tab."),
            "",
            _("Inputs") + f": {len(plan.utxos)}",
            _("Outputs") + f": {len(plan.output_values)}",
            _("Mining fee") + f": {plan.tx.get_fee()} sats",
            "",
            _("Do you want to sign and broadcast this Benford split transaction?"),
        ])
        if not self._main_window.question(prompt):
            return

        password = self._main_window.password_dialog(
            _("Enter your password to sign the Benford split transaction."))
        if password is None:
            return

        plan.tx.context = TransactionContext(description=_("ElectrumSV Benford split"))

        def sign_done(success: bool) -> None:
            if not success:
                return
            if not plan.tx.is_complete():
                dialog = self._main_window.show_transaction(self._account, plan.tx)
                dialog.exec()
                return
            self._main_window.broadcast_transaction(self._account, plan.tx,
                success_text=_("Your coins have now been Benford-split."))

        self._main_window.sign_tx_with_password(plan.tx, sign_done, password)
