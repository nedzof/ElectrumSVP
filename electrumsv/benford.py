from collections import Counter
from dataclasses import dataclass
from typing import Counter as CounterType, Dict, List, Optional, Sequence

from .constants import RECEIVING_SUBPATH
from .exceptions import NotEnoughFunds
from .i18n import _
from .transaction import Transaction, XTxOutput
from .wallet import AbstractAccount, UTXO


BLOCKS_PER_DAY = 144
BENFORD_DIGIT_WEIGHTS = {
    1: 0.301,
    2: 0.176,
    3: 0.125,
    4: 0.097,
    5: 0.079,
    6: 0.067,
    7: 0.058,
    8: 0.051,
    9: 0.046,
}
PRIVACY_OUTPUT_COUNTS = {
    1: 4,
    2: 6,
    3: 9,
    4: 13,
    5: 18,
}
PRIVACY_FACTORS = {
    1: (0.95, 1.10, 0.90, 1.05),
    2: (0.75, 1.30, 0.90, 1.10, 0.65, 1.20),
    3: (0.55, 1.40, 0.80, 1.15, 0.65, 1.30, 0.95, 1.20),
    4: (0.45, 1.55, 0.70, 1.20, 0.60, 1.40, 0.85, 1.25, 0.50, 1.35),
    5: (0.35, 1.80, 0.60, 1.25, 0.50, 1.50, 0.80, 1.35, 0.45, 1.60, 0.95, 1.20),
}


@dataclass(frozen=True)
class BenfordSettings:
    privacy_level: int = 3
    min_age_days: int = 0
    max_age_days: int = 0
    min_utxo_value: int = 0
    max_utxo_value: int = 0
    min_split_value: int = 0
    max_split_value: int = 0


@dataclass(frozen=True)
class BenfordPlan:
    tx: Transaction
    utxos: Sequence[UTXO]
    output_values: Sequence[int]
    first_digit_counts: CounterType[int]
    first_digit_ratios: Dict[int, float]
    benford_mad: float
    privacy_level: int
    min_age_days: int
    max_age_days: int
    min_utxo_value: int
    max_utxo_value: int
    min_split_value: int
    max_split_value: int


def _leading_digit(value: int) -> int:
    for char in str(abs(value)):
        if char != "0":
            return int(char)
    return 0


def _quantile_digit(quantile: float) -> int:
    cumulative = 0.0
    for digit in range(1, 10):
        cumulative += BENFORD_DIGIT_WEIGHTS[digit]
        if quantile <= cumulative:
            return digit
    return 9


def _get_utxo_age_blocks(account: AbstractAccount, utxo: UTXO) -> Optional[int]:
    metadata = account.get_transaction_metadata(utxo.tx_hash)
    if metadata is None or metadata.height is None or metadata.height <= 0:
        return None
    local_height = account._wallet.get_local_height()
    if local_height <= 0:
        return None
    return max(local_height - metadata.height + 1, 0)


def filter_benford_utxos(account: AbstractAccount, settings: BenfordSettings,
        utxos: Optional[Sequence[UTXO]]=None) -> List[UTXO]:
    if settings.min_age_days and settings.max_age_days and \
            settings.min_age_days > settings.max_age_days:
        raise ValueError(_("Minimum age cannot exceed maximum age."))
    if settings.min_utxo_value and settings.max_utxo_value and \
            settings.min_utxo_value > settings.max_utxo_value:
        raise ValueError(_("Minimum UTXO value cannot exceed maximum UTXO value."))
    if settings.min_split_value and settings.max_split_value and \
            settings.min_split_value > settings.max_split_value:
        raise ValueError(_("Minimum split value cannot exceed maximum split value."))

    if utxos is None:
        utxos = account.get_utxos(exclude_frozen=True, mature=True, confirmed_only=True)
        utxos = [utxo for utxo in utxos if not account.is_frozen_key(utxo.keyinstance_id)]

    min_age_blocks = settings.min_age_days * BLOCKS_PER_DAY
    max_age_blocks = settings.max_age_days * BLOCKS_PER_DAY

    filtered_utxos: List[UTXO] = []
    for utxo in utxos:
        if settings.min_utxo_value and utxo.value < settings.min_utxo_value:
            continue
        if settings.max_utxo_value and utxo.value > settings.max_utxo_value:
            continue
        if min_age_blocks or max_age_blocks:
            age_blocks = _get_utxo_age_blocks(account, utxo)
            if age_blocks is None:
                continue
            if min_age_blocks and age_blocks < min_age_blocks:
                continue
            if max_age_blocks and age_blocks > max_age_blocks:
                continue
        filtered_utxos.append(utxo)

    return filtered_utxos


def _smallest_amount_with_digit(digit: int, minimum_value: int) -> int:
    if minimum_value <= digit:
        return digit
    exp = max(0, len(str(minimum_value)) - 1)
    while True:
        lower = digit * (10 ** exp)
        upper = ((digit + 1) * (10 ** exp)) - 1 if digit < 9 else (10 ** (exp + 1)) - 1
        if upper >= minimum_value:
            return max(lower, minimum_value)
        exp += 1


def _choose_benford_amount(digit: int, minimum_value: int, maximum_value: int) -> Optional[int]:
    if maximum_value < minimum_value:
        return None
    candidate = _smallest_amount_with_digit(digit, minimum_value)
    if candidate > maximum_value:
        return None

    exp = len(str(maximum_value))
    while exp >= 0:
        base = 10 ** exp
        lower = digit * base
        upper = ((digit + 1) * base) - 1 if digit < 9 else (10 ** (exp + 1)) - 1
        if upper < minimum_value:
            exp -= 1
            continue
        candidate = min(maximum_value, upper)
        if candidate >= max(minimum_value, lower):
            return candidate
        exp -= 1
    return candidate


def _target_output_count(total_value: int, dust_threshold: int, privacy_level: int,
        maximum_output_value: Optional[int]=None) -> int:
    privacy_level = max(1, min(5, privacy_level))
    requested_count = PRIVACY_OUTPUT_COUNTS[privacy_level]
    max_count_by_value = max(2, min(24, total_value // max(dust_threshold * 2, 1000)))
    minimum_count_for_cap = 2
    if maximum_output_value is not None and maximum_output_value > 0:
        minimum_count_for_cap = max(2, (total_value + maximum_output_value - 1) // maximum_output_value)
    return max(minimum_count_for_cap, min(requested_count, max_count_by_value))


def _build_fixed_amounts(total_value: int, output_count: int, dust_threshold: int,
        privacy_level: int, minimum_output_value: int, maximum_output_value: Optional[int]) \
            -> List[int]:
    fixed_amounts: List[int] = []
    remaining_value = total_value
    factors = PRIVACY_FACTORS[max(1, min(5, privacy_level))]

    for output_index in range(output_count - 1):
        fixed_outputs_remaining = (output_count - 1) - output_index
        reserved_for_last_output = minimum_output_value
        reserved_for_other_fixed_outputs = minimum_output_value * (fixed_outputs_remaining - 1)
        maximum_value = remaining_value - reserved_for_last_output - reserved_for_other_fixed_outputs
        minimum_value = minimum_output_value
        if maximum_value < minimum_output_value:
            raise NotEnoughFunds()
        if maximum_output_value is not None:
            maximum_value = min(maximum_value, maximum_output_value)
            minimum_value = max(minimum_value,
                remaining_value - (fixed_outputs_remaining * maximum_output_value))
            if maximum_value < minimum_output_value:
                raise NotEnoughFunds()
            if maximum_value < minimum_value:
                raise NotEnoughFunds()

        quantile = (output_index + 0.5) / max(output_count - 1, 1)
        digit = _quantile_digit(quantile)
        average_target = max(minimum_value, maximum_value // (fixed_outputs_remaining + 1))
        factor = factors[output_index % len(factors)]
        target_value = max(minimum_value, int(average_target * factor))
        target_value = min(target_value, maximum_value)
        amount = _choose_benford_amount(digit, minimum_value, target_value)
        if amount is None:
            amount = minimum_value
            if amount > maximum_value:
                raise NotEnoughFunds()
        fixed_amounts.append(amount)
        remaining_value -= amount

    return fixed_amounts


def _build_output_templates(account: AbstractAccount, output_count: int, fixed_amounts: Sequence[int]) \
        -> List[XTxOutput]:
    key_rows = account.create_keys(output_count, RECEIVING_SUBPATH)
    outputs: List[XTxOutput] = []
    for output_index, key_row in enumerate(key_rows):
        script = account.get_script_for_id(key_row.keyinstance_id)
        value = fixed_amounts[output_index] if output_index < len(fixed_amounts) else all
        outputs.append(XTxOutput(value, script))
    return outputs


def _build_first_digit_counts(values: Sequence[int]) -> CounterType[int]:
    return Counter(_leading_digit(value) for value in values if value > 0)


def _build_first_digit_ratios(values: Sequence[int]) -> Dict[int, float]:
    counts = _build_first_digit_counts(values)
    total = max(1, sum(counts.values()))
    return {digit: counts.get(digit, 0) / total for digit in range(1, 10)}


def _calculate_benford_mad(values: Sequence[int]) -> float:
    ratios = _build_first_digit_ratios(values)
    return sum(abs(ratios[digit] - BENFORD_DIGIT_WEIGHTS[digit]) for digit in range(1, 10)) / 9.0


def create_benford_plan(account: AbstractAccount, config, settings: BenfordSettings,
        fixed_fee: Optional[int]=None) -> BenfordPlan:
    utxos = filter_benford_utxos(account, settings)
    if not utxos:
        raise NotEnoughFunds()

    total_value = sum(utxo.value for utxo in utxos)
    dust_threshold = account.dust_threshold()
    minimum_output_value = max(dust_threshold, 546, settings.min_split_value or 0)
    maximum_output_value = settings.max_split_value or None
    output_count = _target_output_count(total_value, dust_threshold, settings.privacy_level,
        maximum_output_value)
    maximum_output_count = max(output_count, 24 if maximum_output_value is not None else output_count)
    last_error: Optional[Exception] = None

    while 2 <= output_count <= maximum_output_count:
        try:
            fixed_amounts = _build_fixed_amounts(total_value, output_count, dust_threshold,
                settings.privacy_level, minimum_output_value, maximum_output_value)
            outputs = _build_output_templates(account, output_count, fixed_amounts)
            tx = account.make_unsigned_transaction(list(utxos), outputs, config, fixed_fee=fixed_fee)
            output_values = [tx_output.value for tx_output in tx.outputs]
            if any(value < dust_threshold for value in output_values):
                raise NotEnoughFunds()
            if maximum_output_value is not None and any(value > maximum_output_value
                    for value in output_values):
                raise NotEnoughFunds()
            first_digit_counts = _build_first_digit_counts(output_values)
            first_digit_ratios = _build_first_digit_ratios(output_values)
            return BenfordPlan(
                tx=tx,
                utxos=tuple(utxos),
                output_values=tuple(output_values),
                first_digit_counts=first_digit_counts,
                first_digit_ratios=first_digit_ratios,
                benford_mad=_calculate_benford_mad(output_values),
                privacy_level=settings.privacy_level,
                min_age_days=settings.min_age_days,
                max_age_days=settings.max_age_days,
                min_utxo_value=settings.min_utxo_value,
                max_utxo_value=settings.max_utxo_value,
                min_split_value=settings.min_split_value,
                max_split_value=settings.max_split_value,
            )
        except Exception as exc:
            last_error = exc
            output_count = output_count - 1 if maximum_output_value is None else output_count + 1

    if last_error is not None:
        raise last_error
    raise NotEnoughFunds()


def format_plan_preview(plan: BenfordPlan) -> str:
    digit_parts = []
    for digit in range(1, 10):
        count = plan.first_digit_counts.get(digit, 0)
        if count:
            ratio = plan.first_digit_ratios.get(digit, 0.0) * 100.0
            target = BENFORD_DIGIT_WEIGHTS[digit] * 100.0
            digit_parts.append(f"{digit}:{count} ({ratio:.1f}% vs {target:.1f}%)")

    lines = [
        _("Selected inputs") + f": {len(plan.utxos)}",
        _("Input total") + f": {sum(utxo.value for utxo in plan.utxos)} sats",
        _("Planned outputs") + f": {len(plan.output_values)}",
        _("Mining fee") + f": {plan.tx.get_fee()} sats",
        _("Benford MAD") + f": {plan.benford_mad:.4f}",
        _("Leading digits") + ": " + (", ".join(digit_parts) if digit_parts else _("none")),
        "",
        _("Output amounts") + ":",
    ]
    for output_index, value in enumerate(plan.output_values, start=1):
        lines.append(f"{output_index}. {value} sats")
    return "\n".join(lines)
