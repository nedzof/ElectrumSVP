# Vault Security Audit

Date: 2026-03-20

Scope:
- Rúnar covenant source and checked-in artifact usage
- ElectrumSV vault metadata and wallet lifecycle
- Vault signing and spend restrictions
- Positive and negative tests for lock and unlock flows

## Gate

Status: no known code-level blocker remains in the audited vault path.

Reason:
- No Critical findings remain in the wallet metadata path that was audited here.
- The implementation now rejects mismatched metadata and malformed wallet-side vault spends.
- Recovery, live negative rejection, artifact verification, rediscovery subscription coverage, and GUI misuse tests are now covered.
- The remaining caution is operational rather than an identified code-level bypass in the audited path.

## Findings

### High: guessed legacy metadata could be promoted into spendable contract metadata

Previous behavior:
- Legacy `vault_contract_whitelist_map` string entries were auto-promoted into full contract metadata by guessing `owner_address`, `owner_keyinstance_id`, and `max_fee`.

Impact:
- A wallet could make unsafe assumptions about spendability or ownership for a covenant output without having the true contract binding data.

Fix:
- Legacy whitelist-only entries are no longer promoted into contract metadata.
- Full metadata is only accepted when it matches the actual locking script.

Evidence:
- [wallet.py](/home/caruk/electrumsvp/electrumsv/wallet.py)
- [test_vault.py](/home/caruk/electrumsvp/electrumsv/tests/test_vault.py)

### High: metadata could be stored even when it did not match the covenant script

Previous behavior:
- Wallet-side metadata storage did not prove that `owner`, `whitelist`, and `max_fee` matched the actual script being registered.

Impact:
- The wallet could cache incorrect security assumptions for a covenant output.

Fix:
- Metadata registration now requires `owner_public_key`.
- The public key must derive to the declared owner address.
- The wallet rebuilds the expected covenant script and rejects mismatched metadata.

Evidence:
- [vault_contract.py](/home/caruk/electrumsvp/electrumsv/vault_contract.py)
- [wallet.py](/home/caruk/electrumsvp/electrumsv/wallet.py)
- [test_vault.py](/home/caruk/electrumsvp/electrumsv/tests/test_vault.py)

### Medium: wallet reload behavior for vault UTXOs was not covered

Previous behavior:
- The happy path worked, but there was no regression proving a vault UTXO survives wallet reload and remains spendable with `ScriptType.NONE`.

Impact:
- Recovery and persistence assumptions for larger funds were unproven.

Fix:
- Added a reload test that stores a vault output, reopens the wallet, re-recognizes the covenant UTXO, and spends it successfully.

Evidence:
- [test_vault.py](/home/caruk/electrumsvp/electrumsv/tests/test_vault.py)

### Medium: vault recovery depended too heavily on local metadata

Previous behavior:
- A vault output could only be reconstructed from the local whitelist metadata map.

Impact:
- Metadata loss made recovery brittle even when the covenant script itself still encoded the owner pubkey, whitelist, and fee bound.

Fix:
- Added direct covenant script parsing in the runtime.
- The wallet now reconstructs metadata from the locking script itself and re-binds it to the matching owner keyinstance when possible.
- Added tests for metadata-loss recovery and for a restored seed wallet recognizing the vault output from the lock transaction alone.

Evidence:
- [vault_contract.py](/home/caruk/electrumsvp/electrumsv/vault_contract.py)
- [wallet.py](/home/caruk/electrumsvp/electrumsv/wallet.py)
- [test_vault.py](/home/caruk/electrumsvp/electrumsv/tests/test_vault.py)

### Medium: malformed vault spends were not explicitly regression-tested

Previous behavior:
- Spend restrictions existed in code, but there were no direct tests for malformed wallet-side spends.

Impact:
- A future refactor could weaken restrictions without being caught.

Fix:
- Added tests rejecting:
- non-whitelist outputs
- multiple vault inputs
- owner binding mismatch
- mismatched script metadata

Evidence:
- [test_vault.py](/home/caruk/electrumsvp/electrumsv/tests/test_vault.py)

### Low: artifact and Python constructor logic had no independent verifier

Previous behavior:
- The checked-in artifact and Python constructor logic were only matched indirectly through runtime success.

Impact:
- A future artifact or constructor-slot drift could go unnoticed until runtime.

Fix:
- Added an independent verifier script that materializes and parses the artifact directly without importing wallet runtime code.
- Added a test that runs that verifier script in CI.

Evidence:
- [verify_artifact.py](/home/caruk/electrumsvp/contrib/vault_whitelist_contract/scripts/verify_artifact.py)
- [test_vault.py](/home/caruk/electrumsvp/electrumsv/tests/test_vault.py)

## Current Coverage

Implemented and passing:
- end-to-end lock and unlock flow with distinct funded, whitelist, and owner roles
- metadata binding validation
- direct script parsing and metadata reconstruction from covenant outputs
- owner-key subscription coverage for registered vault covenant scripts
- no unsafe promotion of legacy whitelist-only entries
- wallet reload and vault UTXO rediscovery
- seed-restored wallet recovery from the lock transaction path
- explicit recovery/import of vault metadata from the covenant script itself
- malformed vault spend rejection for extra outputs
- malformed vault spend rejection for multiple vault inputs
- interpreter-level rejection of a mutated malformed vault spend
- live testnet rejection of a malformed mutated vault spend, followed by recovery spend
- transaction round-trip preservation of vault unlock arguments
- independent artifact verifier script execution
- Qt-backed send-view regression coverage for vault toggle and metadata registration
- GUI misuse-path tests for vault output registration and vault send-plan restrictions
- operator recovery utility for decoding/importing vault covenant scripts

## Residual Risks

Still not fully closed for a large-funds bar:
- Fully blind rediscovery of unknown covenant outputs without either prior wallet history or the covenant script itself is still not a supported scan model.
- The Qt send-view coverage is still targeted regression coverage, not a full end-user GUI automation suite.
- This is still software, not a formal external security audit.

## Minimum Remaining Work Before Large-Funds Use

- Decide whether fully blind rediscovery of covenant outputs with no prior wallet history and no covenant script is a product requirement; if yes, it needs an explicit index/scan design beyond the current known-script and script-import recovery model.
- If you want a higher assurance bar than this internal audit, get an external review of the covenant and spend path.
