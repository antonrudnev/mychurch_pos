#!/bin/sh
set -eu

: "${DOMAIN:?DOMAIN must be set}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL must be set}"
: "${Dynu_ClientId:?Set DYNU_CLIENT_ID in .env for DNS-01}"
: "${Dynu_Secret:?Set DYNU_CLIENT_SECRET in .env for DNS-01}"

acme.sh --set-default-ca --server letsencrypt
acme.sh --issue --dns dns_dynu -d "$DOMAIN" --accountemail "$LETSENCRYPT_EMAIL"
acme.sh --install-cert -d "$DOMAIN" \
    --key-file "/etc/nginx/certs/$DOMAIN.key" \
    --fullchain-file "/etc/nginx/certs/$DOMAIN.crt" \
    --reloadcmd "docker restart nginx-proxy"

exec /entry.sh daemon
