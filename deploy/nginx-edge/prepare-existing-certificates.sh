#!/bin/sh
set -eu

edge_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cert_dir="$edge_dir/certs"
caddy_container=${CADDY_CONTAINER:-qc_capture_system-caddy-1}
caddy_root=/data/caddy/certificates/acme-v02.api.letsencrypt.org-directory
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

mkdir -p "$cert_dir"

install -d -m 755 "$cert_dir/47.96.9.22"
cp -L /etc/letsencrypt/live/47.96.9.22/fullchain.pem "$temporary/ip.crt"
cp -L /etc/letsencrypt/live/47.96.9.22/privkey.pem "$temporary/ip.key"
install -m 644 "$temporary/ip.crt" "$cert_dir/47.96.9.22/fullchain.pem"
install -m 600 "$temporary/ip.key" "$cert_dir/47.96.9.22/privkey.pem"

for domain in mtalloypiping.com www.mtalloypiping.com; do
    docker cp "$caddy_container:$caddy_root/$domain/$domain.crt" \
        "$temporary/$domain.crt"
    docker cp "$caddy_container:$caddy_root/$domain/$domain.key" \
        "$temporary/$domain.key"
    install -d -m 755 "$cert_dir/$domain"
    install -m 644 "$temporary/$domain.crt" "$cert_dir/$domain/fullchain.pem"
    install -m 600 "$temporary/$domain.key" "$cert_dir/$domain/privkey.pem"
done

printf '%s\n' "Existing certificates copied to $cert_dir"
