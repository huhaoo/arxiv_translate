#!/usr/bin/env bash
set -u

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir" || exit 1

if command -v python3 >/dev/null 2>&1; then
  python3 -m arxiv_translate "$@"
elif command -v python >/dev/null 2>&1; then
  python -m arxiv_translate "$@"
else
  echo "Python was not found. Please install Python 3.10+ or add it to PATH." >&2
  exit 1
fi
