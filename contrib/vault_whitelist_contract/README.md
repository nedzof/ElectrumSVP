# Vault whitelist covenant

This directory contains the on-chain covenant used by the ElectrumSV vault flow.

Contract semantics:

1. The vault owner must provide a valid signature.
2. The contract verifies the real spending transaction via `check_preimage`.
3. The spending transaction must contain exactly one payout output to the committed whitelist address.
4. The payout amount must be positive.
5. The fee burn is bounded by `max_fee`.

ElectrumSV runtime notes:

1. ElectrumSV ships the compiled artifact in `artifacts/VaultWhitelist.runar.json`.
2. The wallet runtime is pure Python. It does not invoke Node or Rúnar at spend time.
3. The send tab derives a fresh whitelist key and a fresh owner key for each new vault output.
4. Wallet metadata stores `contract_type`, `owner_address`, `owner_public_key`, `owner_keyinstance_id`, `whitelist`, and `max_fee`.

Rebuild the artifact:

```bash
cd contrib/vault_whitelist_contract
./scripts/build_contract.sh
```

The artifact is the audited source of truth for the locking-script template. ElectrumSV splices constructor arguments into that template locally and computes the `OP_PUSH_TX` unlock data in Python.
