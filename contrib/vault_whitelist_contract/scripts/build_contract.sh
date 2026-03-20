#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
npm install
mkdir -p artifacts
npx runar-cli compile src/contracts/VaultWhitelist.runar.py --output artifacts
