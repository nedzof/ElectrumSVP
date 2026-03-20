#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bitcoinx import Script

from electrumsv.bip276 import PREFIX_BIP276_SCRIPT, bip276_decode
from electrumsv.vault_contract import CovenantContractRuntime


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover vault covenant metadata from a locking script.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--script-hex", help="Raw locking script hex")
    group.add_argument("--bip276", help="BIP276 bitcoin-script text")
    args = parser.parse_args()

    if args.script_hex is not None:
        script = Script(bytes.fromhex(args.script_hex))
    else:
        prefix, version, script_bytes, network = bip276_decode(args.bip276)
        if prefix != PREFIX_BIP276_SCRIPT:
            raise SystemExit("expected a bitcoin-script BIP276 payload")
        script = Script(script_bytes)

    metadata = CovenantContractRuntime.parse_contract_locking_script(script)
    if metadata is None:
        raise SystemExit("script is not a supported vault covenant")

    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
