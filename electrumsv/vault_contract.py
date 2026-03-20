from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
import struct
from typing import Any, Dict, Optional

from bitcoinx import Address, P2PKH_Address, PublicKey, Script

from .bip276 import PREFIX_BIP276_SCRIPT, bip276_encode
from .constants import PREFIX_ASM_SCRIPT
from .networks import Net


class CovenantContractRuntime:
    """Helpers for the bundled Rúnar vault covenant."""

    CURRENT_VERSION = 2
    CONTRACT_TYPE = "runar_vault_whitelist_v1"
    DEFAULT_MAX_FEE = 1000
    PROJECT_PATH = Path(__file__).resolve().parent.parent / "contrib" / "vault_whitelist_contract"
    ARTIFACT_PATH = PROJECT_PATH / "artifacts" / "VaultWhitelist.runar.json"
    OP_PUSH_TX_SIGHASH = 0x41
    LEGACY_CONTRACT_TYPES = {"scrypt_vault_whitelist_v1", "runar_vault_whitelist_v1"}

    @classmethod
    @lru_cache(maxsize=1)
    def _load_artifact(cls) -> Dict[str, Any]:
        if not cls.ARTIFACT_PATH.exists():
            raise RuntimeError(
                f"missing vault artifact: {cls.ARTIFACT_PATH}. "
                "Run contrib/vault_whitelist_contract/scripts/build_contract.sh"
            )
        with cls.ARTIFACT_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _encode_push_data(data_hex: str) -> str:
        data_len = len(data_hex) // 2
        if data_len <= 75:
            return f"{data_len:02x}{data_hex}"
        if data_len <= 0xFF:
            return f"4c{data_len:02x}{data_hex}"
        if data_len <= 0xFFFF:
            return "4d" + data_len.to_bytes(2, "little").hex() + data_hex
        return "4e" + data_len.to_bytes(4, "little").hex() + data_hex

    @classmethod
    def _encode_arg_hex(cls, value: Any) -> str:
        if isinstance(value, bool):
            return "51" if value else "00"
        if isinstance(value, int):
            data = cls.encode_script_number(value)
            return cls._encode_push_data(data.hex()) if data else "00"
        if isinstance(value, bytes):
            return cls._encode_push_data(value.hex())
        if isinstance(value, str):
            return cls._encode_push_data(value)
        raise TypeError(f"unsupported contract argument type {type(value)!r}")

    @staticmethod
    def encode_script_number(value: int) -> bytes:
        if value == 0:
            return b""
        negative = value < 0
        abs_value = abs(value)
        encoded = bytearray()
        while abs_value:
            encoded.append(abs_value & 0xFF)
            abs_value >>= 8
        if encoded[-1] & 0x80:
            encoded.append(0x80 if negative else 0x00)
        elif negative:
            encoded[-1] |= 0x80
        return bytes(encoded)

    @staticmethod
    def decode_script_number(data: bytes) -> int:
        if not data:
            return 0
        raw = bytearray(data)
        negative = bool(raw[-1] & 0x80)
        if negative:
            raw[-1] &= 0x7F
        value = 0
        for index, byte in enumerate(raw):
            value |= byte << (8 * index)
        return -value if negative else value

    @staticmethod
    def _read_push_data(script_bytes: bytes, offset: int) -> tuple[bytes, int]:
        if offset >= len(script_bytes):
            raise ValueError("unexpected end of script")
        opcode = script_bytes[offset]
        if opcode == 0:
            return b"", offset + 1
        if 1 <= opcode <= 75:
            start = offset + 1
            end = start + opcode
            return script_bytes[start:end], end
        if opcode == 0x4C:
            data_len = script_bytes[offset + 1]
            start = offset + 2
            end = start + data_len
            return script_bytes[start:end], end
        if opcode == 0x4D:
            data_len = int.from_bytes(script_bytes[offset + 1:offset + 3], "little")
            start = offset + 3
            end = start + data_len
            return script_bytes[start:end], end
        if opcode == 0x4E:
            data_len = int.from_bytes(script_bytes[offset + 1:offset + 5], "little")
            start = offset + 5
            end = start + data_len
            return script_bytes[start:end], end
        raise ValueError(f"expected pushdata opcode at offset {offset}, got 0x{opcode:02x}")

    @classmethod
    def parse_contract_locking_script(cls, script: Script) -> Optional[dict]:
        artifact = cls._load_artifact()
        constructor = artifact.get("abi", {}).get("constructor", {})
        params = constructor.get("params", [])
        slots = sorted(artifact.get("constructorSlots", []), key=lambda entry: entry["byteOffset"])
        base_script = bytes.fromhex(artifact["script"])
        script_bytes = script.to_bytes()

        values: dict[int, Any] = {}
        base_offset = 0
        script_offset = 0
        try:
            for slot in slots:
                slot_offset = slot["byteOffset"]
                prefix = base_script[base_offset:slot_offset]
                if script_bytes[script_offset:script_offset + len(prefix)] != prefix:
                    return None
                script_offset += len(prefix)
                data, script_offset = cls._read_push_data(script_bytes, script_offset)
                param = params[slot["paramIndex"]]
                param_type = param["type"]
                if param_type == "PubKey":
                    values[slot["paramIndex"]] = PublicKey.from_bytes(data).to_hex()
                elif param_type == "Addr":
                    if len(data) != 20:
                        return None
                    values[slot["paramIndex"]] = str(P2PKH_Address(data, Net.COIN))
                elif param_type in ("bigint", "int"):
                    values[slot["paramIndex"]] = cls.decode_script_number(data)
                else:
                    return None
                base_offset = slot_offset + 1
        except Exception:
            return None

        suffix = base_script[base_offset:]
        if script_bytes[script_offset:] != suffix:
            return None

        owner_public_key = values.get(0)
        whitelist = values.get(1)
        max_fee = values.get(2)
        if not isinstance(owner_public_key, str) or not isinstance(whitelist, str) or \
                not isinstance(max_fee, int) or max_fee < 0:
            return None

        owner_address = str(PublicKey.from_hex(owner_public_key).to_address(network=Net.COIN))
        return {
            "version": cls.CURRENT_VERSION,
            "contract_type": cls.CONTRACT_TYPE,
            "owner_address": owner_address,
            "owner_public_key": owner_public_key,
            "whitelist": whitelist,
            "max_fee": max_fee,
            "owner_keyinstance_id": None,
        }

    @classmethod
    def _adjust_code_separator_offset(cls, base_offset: int, constructor_args: list[Any]) -> int:
        artifact = cls._load_artifact()
        shift = 0
        for slot in artifact.get("constructorSlots", []):
            if slot["byteOffset"] >= base_offset:
                continue
            encoded = cls._encode_arg_hex(constructor_args[slot["paramIndex"]])
            shift += len(encoded) // 2 - 1
        return base_offset + shift

    @classmethod
    def get_code_separator_index(cls, constructor_args: list[Any]) -> int:
        artifact = cls._load_artifact()
        indices = artifact.get("codeSeparatorIndices")
        if indices:
            return cls._adjust_code_separator_offset(indices[0], constructor_args)
        index = artifact.get("codeSeparatorIndex")
        if index is None:
            return -1
        return cls._adjust_code_separator_offset(index, constructor_args)

    @classmethod
    def build_contract_locking_script(cls, owner_public_key_hex: str, whitelist_address: str,
            max_fee: int) -> Script:
        owner_public_key = PublicKey.from_hex(owner_public_key_hex).to_hex()
        whitelist = Address.from_string(whitelist_address, Net.COIN).hash160().hex()
        if max_fee < 0:
            raise ValueError("max fee cannot be negative")

        artifact = cls._load_artifact()
        constructor_args = [owner_public_key, whitelist, int(max_fee)]
        script_hex = artifact["script"]
        for slot in sorted(artifact.get("constructorSlots", []),
                key=lambda entry: entry["byteOffset"], reverse=True):
            encoded = cls._encode_arg_hex(constructor_args[slot["paramIndex"]])
            offset = slot["byteOffset"] * 2
            script_hex = script_hex[:offset] + encoded + script_hex[offset + 2:]
        return Script(bytes.fromhex(script_hex))

    @classmethod
    def build_contract_locking_script_text(cls, owner_public_key_hex: str,
            whitelist_address: str, max_fee: int) -> str:
        script = cls.build_contract_locking_script(owner_public_key_hex, whitelist_address, max_fee)
        return bip276_encode(PREFIX_BIP276_SCRIPT, script.to_bytes(), Net.BIP276_VERSION)

    @classmethod
    def validate_owner_binding(cls, owner_address: str, owner_public_key: str) -> tuple[str, str]:
        normalized_public_key = PublicKey.from_hex(owner_public_key).to_hex()
        normalized_address = str(Address.from_string(owner_address, Net.COIN))
        expected_address = str(PublicKey.from_hex(normalized_public_key).to_address(
            network=Net.COIN))
        if expected_address != normalized_address:
            raise ValueError("owner address does not match owner public key")
        return normalized_address, normalized_public_key

    @classmethod
    def build_contract_metadata(cls, owner_address: str, whitelist_address: str, max_fee: int,
            owner_keyinstance_id: Optional[int]=None, owner_public_key: Optional[str]=None) -> dict:
        if max_fee < 0:
            raise ValueError("max fee cannot be negative")
        owner_address_text = str(Address.from_string(owner_address, Net.COIN))
        metadata = {
            "version": cls.CURRENT_VERSION,
            "contract_type": cls.CONTRACT_TYPE,
            "owner_address": owner_address_text,
            "whitelist": str(Address.from_string(whitelist_address, Net.COIN)),
            "max_fee": int(max_fee),
            "owner_keyinstance_id": owner_keyinstance_id,
        }
        if owner_public_key is not None:
            owner_address_text, owner_public_key = cls.validate_owner_binding(
                owner_address_text, owner_public_key)
            metadata["owner_address"] = owner_address_text
            metadata["owner_public_key"] = owner_public_key
        return metadata

    @classmethod
    def parse_contract_metadata(cls, value) -> Optional[dict]:
        if not isinstance(value, dict):
            return None
        contract_type = value.get("contract_type", cls.CONTRACT_TYPE)
        if contract_type not in cls.LEGACY_CONTRACT_TYPES:
            return None
        whitelist = value.get("whitelist")
        owner_address = value.get("owner_address")
        max_fee = value.get("max_fee")
        if not isinstance(whitelist, str) or not isinstance(owner_address, str):
            return None
        if not isinstance(max_fee, int) or max_fee < 0:
            return None
        owner_keyinstance_id = value.get("owner_keyinstance_id")
        if owner_keyinstance_id is not None and not isinstance(owner_keyinstance_id, int):
            owner_keyinstance_id = None
        owner_public_key = value.get("owner_public_key")
        if owner_public_key is not None:
            try:
                owner_address, owner_public_key = cls.validate_owner_binding(
                    owner_address, owner_public_key)
            except Exception:
                owner_public_key = None
        return {
            "version": int(value.get("version", cls.CURRENT_VERSION)),
            "contract_type": cls.CONTRACT_TYPE,
            "owner_address": str(Address.from_string(owner_address, Net.COIN)),
            "owner_public_key": owner_public_key,
            "whitelist": str(Address.from_string(whitelist, Net.COIN)),
            "max_fee": max_fee,
            "owner_keyinstance_id": owner_keyinstance_id,
        }

    @classmethod
    def script_matches_metadata(cls, script: Script, metadata: dict) -> bool:
        owner_public_key = metadata.get("owner_public_key")
        if not isinstance(owner_public_key, str):
            return False
        expected_script = cls.build_contract_locking_script(
            owner_public_key, metadata["whitelist"], metadata["max_fee"])
        return expected_script == script

    @classmethod
    def parse_whitelist_map_value(cls, value) -> Optional[str]:
        metadata = cls.parse_contract_metadata(value)
        if metadata is not None:
            return metadata["whitelist"]
        if isinstance(value, str):
            return str(Address.from_string(value, Net.COIN))
        if isinstance(value, dict):
            for key in ("whitelist", "whitelist_address", "address"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return str(Address.from_string(candidate, Net.COIN))
            legacy = value.get("v1")
            if isinstance(legacy, str):
                return str(Address.from_string(legacy, Net.COIN))
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], str):
            return str(Address.from_string(value[0], Net.COIN))
        return None

    @staticmethod
    def normalise_whitelist_metadata(whitelist: str) -> str:
        return str(Address.from_string(whitelist, Net.COIN))

    @classmethod
    def build_spend_items(cls, tx_hex: str, input_index: int, input_script: Script,
            input_value: int, payout_amount: int, constructor_args: list[Any]) -> list[bytes]:
        if payout_amount <= 0:
            raise ValueError("vault payout must be positive")
        code_separator_index = cls.get_code_separator_index(constructor_args)
        op_push_sig_hex, preimage_hex = cls._compute_op_push_tx(
            tx_hex, input_index, input_script.to_bytes().hex(), input_value, code_separator_index)
        return [
            bytes.fromhex(op_push_sig_hex),
            cls.encode_script_number(payout_amount),
            bytes.fromhex(preimage_hex),
        ]

    @classmethod
    def _compute_op_push_tx(cls, tx_hex: str, input_index: int, subscript_hex: str,
            satoshis: int, code_separator_index: int=-1) -> tuple[str, str]:
        effective_subscript = subscript_hex
        if code_separator_index >= 0:
            trim_pos = (code_separator_index + 1) * 2
            if trim_pos <= len(subscript_hex):
                effective_subscript = subscript_hex[trim_pos:]
        tx = cls._parse_raw_tx(bytes.fromhex(tx_hex))
        preimage = cls._bip143_preimage(tx, input_index, bytes.fromhex(effective_subscript), satoshis)
        sighash = cls._sha256d(preimage)
        sig_r = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
        curve_order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        sig_s = (int.from_bytes(sighash, "big") + sig_r) % curve_order
        if sig_s > (curve_order >> 1):
            sig_s = curve_order - sig_s
        der = cls._der_encode(sig_r, sig_s)
        return der.hex() + f"{cls.OP_PUSH_TX_SIGHASH:02x}", preimage.hex()

    @staticmethod
    def _der_encode(r: int, s: int) -> bytes:
        def encode_int(value: int) -> bytes:
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            if raw[0] & 0x80:
                raw = b"\x00" + raw
            return raw

        r_bytes = encode_int(r)
        s_bytes = encode_int(s)
        payload = b"\x02" + bytes([len(r_bytes)]) + r_bytes + b"\x02" + bytes([len(s_bytes)]) + s_bytes
        return b"\x30" + bytes([len(payload)]) + payload

    @staticmethod
    def _sha256d(data: bytes) -> bytes:
        return hashlib.sha256(hashlib.sha256(data).digest()).digest()

    @classmethod
    def _bip143_preimage(cls, tx: Dict[str, Any], input_index: int, subscript: bytes,
            satoshis: int) -> bytes:
        prevouts = b"".join(
            entry["prev_txid_bytes"] + struct.pack("<I", entry["prev_output_index"])
            for entry in tx["inputs"]
        )
        sequences = b"".join(struct.pack("<I", entry["sequence"]) for entry in tx["inputs"])
        outputs = b"".join(
            struct.pack("<Q", entry["satoshis"]) +
            cls._encode_varint(len(entry["script"])) + entry["script"]
            for entry in tx["outputs"]
        )
        txin = tx["inputs"][input_index]
        return b"".join([
            struct.pack("<I", tx["version"]),
            cls._sha256d(prevouts),
            cls._sha256d(sequences),
            txin["prev_txid_bytes"],
            struct.pack("<I", txin["prev_output_index"]),
            cls._encode_varint(len(subscript)),
            subscript,
            struct.pack("<Q", satoshis),
            struct.pack("<I", txin["sequence"]),
            cls._sha256d(outputs),
            struct.pack("<I", tx["locktime"]),
            struct.pack("<I", cls.OP_PUSH_TX_SIGHASH),
        ])

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        if value < 0xFD:
            return bytes([value])
        if value <= 0xFFFF:
            return b"\xfd" + struct.pack("<H", value)
        if value <= 0xFFFFFFFF:
            return b"\xfe" + struct.pack("<I", value)
        return b"\xff" + struct.pack("<Q", value)

    @classmethod
    def _parse_raw_tx(cls, data: bytes) -> Dict[str, Any]:
        offset = 0

        def read(size: int) -> bytes:
            nonlocal offset
            result = data[offset:offset + size]
            offset += size
            return result

        def read_varint() -> int:
            nonlocal offset
            first = data[offset]
            offset += 1
            if first < 0xFD:
                return first
            if first == 0xFD:
                value = struct.unpack("<H", read(2))[0]
                return value
            if first == 0xFE:
                value = struct.unpack("<I", read(4))[0]
                return value
            return struct.unpack("<Q", read(8))[0]

        version = struct.unpack("<I", read(4))[0]
        inputs = []
        for _ in range(read_varint()):
            prev_txid = read(32)
            prev_output_index = struct.unpack("<I", read(4))[0]
            script_len = read_varint()
            read(script_len)
            sequence = struct.unpack("<I", read(4))[0]
            inputs.append({
                "prev_txid_bytes": prev_txid,
                "prev_output_index": prev_output_index,
                "sequence": sequence,
            })

        outputs = []
        for _ in range(read_varint()):
            satoshis = struct.unpack("<Q", read(8))[0]
            script_len = read_varint()
            outputs.append({
                "satoshis": satoshis,
                "script": read(script_len),
            })

        locktime = struct.unpack("<I", read(4))[0]
        return {"version": version, "inputs": inputs, "outputs": outputs, "locktime": locktime}

    @staticmethod
    def build_lock_script_to_bip276(script: Script) -> str:
        return bip276_encode(PREFIX_BIP276_SCRIPT, script.to_bytes(), Net.BIP276_VERSION)

    @staticmethod
    def is_bip276_script(script_text: str) -> bool:
        return script_text.startswith(PREFIX_BIP276_SCRIPT + ":")

    @staticmethod
    def is_asm_script(script_text: str) -> bool:
        return script_text.startswith(PREFIX_ASM_SCRIPT)
