#!/bin/sh
set -eu

python -m pip install --disable-pip-version-check --quiet pytest pytest-asyncio

task_dir="$(mktemp -d /tmp/qc-backend-qa.XXXXXX)"
trap 'rm -rf "$task_dir"' EXIT HUP INT TERM

mkdir -p "$task_dir/backend"
cp -a /source/backend/. "$task_dir/backend/"
mkdir -p "$task_dir/backend/data"
cp /source/data/require_mapping.json "$task_dir/backend/data/require_mapping.json"
cp /source/data/factroy_mapping.json "$task_dir/backend/data/factroy_mapping.json"

cd "$task_dir/backend"
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
