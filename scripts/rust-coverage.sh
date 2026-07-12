#!/usr/bin/env bash
# Per-crate Rust line coverage (LCOV DA) via cargo-llvm-cov; each crate ≥ FAIL_UNDER %.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAIL_UNDER="${RUST_COV_FAIL_UNDER:-90}"
PY="${PYO3_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
export PYO3_PYTHON="$PY"

PY_LIB="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")')"
if [[ -n "$PY_LIB" ]]; then
  export LD_LIBRARY_PATH="$PY_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

CRATES=(
  "$ROOT|mcp-stepik-core"
  "$ROOT/packages/mcp-stepik-state|mcp-stepik-state"
)

if ! command -v cargo-llvm-cov >/dev/null 2>&1; then
  echo "cargo-llvm-cov not found; install: cargo install cargo-llvm-cov && rustup component add llvm-tools-preview" >&2
  exit 1
fi

python_check='
import sys
from pathlib import Path
fail = float(sys.argv[1])
lcov = Path(sys.argv[2])
name = sys.argv[3]
total = hit = 0
for line in lcov.read_text().splitlines():
    if line.startswith("DA:"):
        _n, counts = line[3:].split(",", 1)
        total += 1
        if counts != "0":
            hit += 1
pct = 100.0 if total == 0 else (100.0 * hit / total)
print(f"{name}: {hit}/{total} lines = {pct:.2f}%")
if pct + 1e-9 < fail:
    print(f"FAIL: {name} coverage {pct:.2f}% < {fail:.0f}%", file=sys.stderr)
    sys.exit(1)
'

status=0
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

for entry in "${CRATES[@]}"; do
  crate="${entry%%|*}"
  name="${entry##*|}"
  echo "==> rust coverage: $name (fail-under ${FAIL_UNDER}%)"
  lcov_out="$tmpdir/$name.lcov"
  if ! (
    cd "$crate"
    cargo llvm-cov --no-default-features --lcov --output-path "$lcov_out"
  ); then
    echo "FAIL: cargo llvm-cov failed for $name" >&2
    status=1
    continue
  fi
  (cd "$crate" && cargo llvm-cov report --summary-only) || true
  if ! python3 -c "$python_check" "$FAIL_UNDER" "$lcov_out" "$name"; then
    status=1
  fi
done

exit "$status"
