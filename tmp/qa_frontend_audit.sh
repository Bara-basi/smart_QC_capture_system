#!/bin/sh
set -eu

task_dir="$(mktemp -d /tmp/qc-frontend-audit.XXXXXX)"
trap 'rm -rf "$task_dir"' EXIT HUP INT TERM

cp -a /source/. "$task_dir/"
cd "$task_dir"
npm ci --silent

set +e
if [ "${QA_AUDIT_OMIT_DEV:-0}" = "1" ]; then
  npm audit --omit=dev --json >"$task_dir/audit.json"
else
  npm audit --json >"$task_dir/audit.json"
fi
set -e

node - "$task_dir/audit.json" <<'NODE'
const fs = require('fs')
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const vulnerabilities = Object.entries(report.vulnerabilities || {}).map(([name, value]) => ({
  name,
  severity: value.severity,
  direct: Boolean(value.isDirect),
  via: (value.via || []).map(item => typeof item === 'string' ? item : {
    title: item.title,
    severity: item.severity,
    range: item.range,
    url: item.url,
  }),
  fixAvailable: value.fixAvailable,
}))
console.log(JSON.stringify({
  metadata: report.metadata,
  vulnerabilities,
}, null, 2))
NODE
