#!/usr/bin/env bash
# Recreate the project's locked environment; optionally validate the SimPy model.
set -euo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--verify" ) ]]; then
  echo "Usage: bash .codex/setup.sh [--verify]" >&2
  exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"

command -v uv >/dev/null || {
  echo "uv is required. Install uv before running this setup script." >&2
  exit 1
}

# .python-version selects Python; uv.lock supplies exact dependency versions.
# Keep the existing dev group (including sufe-cli) alongside the SimPy runtime.
uv sync --locked
uv pip check --python "$project_root/.venv/bin/python"
uv run --locked python - <<'PY'
import sys
from importlib.metadata import version

import soft_procedure

assert sys.version_info >= (3, 12), "Python 3.12+ is required"
print(f"Python {sys.version.split()[0]} | SimPy {version('simpy')}")
print(f"Model: {soft_procedure.__file__}")
PY

if [[ "${1:-}" == "--verify" ]]; then
  uv run --locked python -m unittest discover -s tests -v
  # A fresh directory keeps earlier experiments and formal results intact.
  mkdir -p outputs
  validation_output="$(mktemp -d "$project_root/outputs/cloud-validation.XXXXXX")"
  uv run --locked soft-procedure experiments --scenario-set core \
    --replications 10 --seed 42 --output "$validation_output"
  uv run --locked python tools/check_case22_core_results.py "$validation_output/results.json"
  echo "Validation output: $validation_output"
fi
