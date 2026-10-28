#!/bin/sh
set -eu

task_dir="$(mktemp -d /tmp/qc-frontend-qa.XXXXXX)"
trap 'rm -rf "$task_dir"' EXIT HUP INT TERM

cp -a /source/. "$task_dir/"
cd "$task_dir"

# The test container has no source mount write access. Dependencies are
# installed only in this disposable copy.
npm ci
npm run build
