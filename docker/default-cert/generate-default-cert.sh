#!/bin/sh
set -eu

: "${DOMAIN:?DOMAIN must be set}"

cert_dir=/etc/nginx/certs
cert_file="$cert_dir/$DOMAIN.crt"
key_file="$cert_dir/$DOMAIN.key"

if [ ! -s "$cert_file" ] ||
    [ ! -s "$key_file" ] ||
    ! openssl x509 -in "$cert_file" -noout -checkhost "$DOMAIN" >/dev/null 2>&1; then
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$key_file" \
        -out "$cert_file" \
        -subj "/CN=$DOMAIN" \
        -addext "subjectAltName=DNS:$DOMAIN"
fi

if [ ! -s "$cert_dir/default.crt" ] ||
    [ ! -s "$cert_dir/default.key" ] ||
    ! openssl x509 -in "$cert_dir/default.crt" -noout -checkhost "$DOMAIN" >/dev/null 2>&1; then
    cp "$cert_file" "$cert_dir/default.crt"
    cp "$key_file" "$cert_dir/default.key"
fi
