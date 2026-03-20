#!/usr/bin/env python3

import json
from pathlib import Path
from typing import Any

from bitcoinx import Address, Bitcoin, P2PKH_Address, PublicKey, Script


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "artifacts" / "VaultWhitelist.runar.json"


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


def encode_push(data: bytes) -> bytes:
    data_len = len(data)
    if data_len <= 75:
        return bytes([data_len]) + data
    if data_len <= 0xFF:
        return b"\x4c" + bytes([data_len]) + data
    if data_len <= 0xFFFF:
        return b"\x4d" + data_len.to_bytes(2, "little") + data
    return b"\x4e" + data_len.to_bytes(4, "little") + data


def read_push(script_bytes: bytes, offset: int) -> tuple[bytes, int]:
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
    raise ValueError(f"expected push opcode, got 0x{opcode:02x}")


def encode_arg(param_type: str, value: Any) -> bytes:
    if param_type == "PubKey":
        return encode_push(bytes.fromhex(value))
    if param_type == "Addr":
        return encode_push(bytes.fromhex(value))
    if param_type in ("bigint", "int"):
        return b"\x00" if value == 0 else encode_push(encode_script_number(int(value)))
    raise ValueError(f"unsupported constructor type {param_type}")


def materialize_script(artifact: dict, owner_public_key: str, whitelist_hash160: str,
        max_fee: int) -> Script:
    params = [owner_public_key, whitelist_hash160, max_fee]
    script_hex = artifact["script"]
    for slot in sorted(artifact["constructorSlots"], key=lambda item: item["byteOffset"],
            reverse=True):
        param_type = artifact["abi"]["constructor"]["params"][slot["paramIndex"]]["type"]
        encoded = encode_arg(param_type, params[slot["paramIndex"]]).hex()
        offset = slot["byteOffset"] * 2
        script_hex = script_hex[:offset] + encoded + script_hex[offset + 2:]
    return Script(bytes.fromhex(script_hex))


def parse_script(artifact: dict, script: Script) -> dict:
    script_bytes = script.to_bytes()
    template = bytes.fromhex(artifact["script"])
    params = artifact["abi"]["constructor"]["params"]
    slots = sorted(artifact["constructorSlots"], key=lambda item: item["byteOffset"])
    values = {}
    template_offset = 0
    script_offset = 0
    for slot in slots:
        prefix = template[template_offset:slot["byteOffset"]]
        if script_bytes[script_offset:script_offset + len(prefix)] != prefix:
            raise ValueError("script prefix mismatch")
        script_offset += len(prefix)
        data, script_offset = read_push(script_bytes, script_offset)
        param_type = params[slot["paramIndex"]]["type"]
        if param_type == "PubKey":
            values[slot["paramIndex"]] = PublicKey.from_bytes(data).to_hex()
        elif param_type == "Addr":
            values[slot["paramIndex"]] = data.hex()
        elif param_type in ("bigint", "int"):
            values[slot["paramIndex"]] = decode_script_number(data)
        else:
            raise ValueError(f"unsupported constructor type {param_type}")
        template_offset = slot["byteOffset"] + 1
    if script_bytes[script_offset:] != template[template_offset:]:
        raise ValueError("script suffix mismatch")
    return values


def main() -> None:
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    owner_public_key = PublicKey.from_hex(
        "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798").to_hex()
    whitelist_address = "1LQoWist8KkaUXSPKZHNvEyfrEkPHzSsCd"
    whitelist_hash160 = Address.from_string(whitelist_address, Bitcoin).hash160().hex()
    max_fee = 321

    script = materialize_script(artifact, owner_public_key, whitelist_hash160, max_fee)
    parsed = parse_script(artifact, script)

    assert parsed[0] == owner_public_key
    assert str(P2PKH_Address(bytes.fromhex(parsed[1]), network=Bitcoin)) == whitelist_address
    assert parsed[2] == max_fee


if __name__ == "__main__":
    main()
