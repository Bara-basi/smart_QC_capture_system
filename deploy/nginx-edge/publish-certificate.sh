#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
    printf 'Usage: %s [cert-name]\n' "$0" >&2
    exit 2
fi

edge_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cert_name=${1:-}
if [ -z "$cert_name" ] && [ -n "${RENEWED_LINEAGE:-}" ]; then
    cert_name=${RENEWED_LINEAGE##*/}
fi
if [ -z "$cert_name" ]; then
    printf 'Usage: %s <cert-name>, or run through a Certbot deploy hook\n' "$0" >&2
    exit 2
fi

source_dir="/etc/letsencrypt/live/$cert_name"
target_dir="$edge_dir/certs/$cert_name"

test -f "$source_dir/fullchain.pem"
test -f "$source_dir/privkey.pem"
install -d -m 755 "$target_dir"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
cp -L "$source_dir/fullchain.pem" "$temporary/fullchain.pem"
cp -L "$source_dir/privkey.pem" "$temporary/privkey.pem"
install -m 644 "$temporary/fullchain.pem" "$target_dir/fullchain.pem"
install -m 600 "$temporary/privkey.pem" "$target_dir/privkey.pem"

if docker inspect mtsco-edge-nginx >/dev/null 2>&1; then
    docker exec mtsco-edge-nginx nginx -t
    docker exec mtsco-edge-nginx nginx -s reload
fi

printf '%s\n' "Certificate $cert_name published and Nginx reloaded"
