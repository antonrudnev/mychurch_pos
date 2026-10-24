#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir"

if [ -n "${DYNU_CLIENT_ID:-}" ]; then
    dynu_client_id=$DYNU_CLIENT_ID
else
    unset DYNU_CLIENT_ID
    if [ -f .env ]; then
        dynu_client_id=$(awk '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*DYNU_CLIENT_ID[[:space:]]*=/ {
            value = substr($0, index($0, "=") + 1)
            sub(/[[:space:]]+#.*/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            if (value ~ /^".*"$/ || value ~ /^'\''.*'\''$/) {
                value = substr(value, 2, length(value) - 2)
            }
            print value
            exit
        }
        ' .env)
    else
        dynu_client_id=
    fi
fi

if [ -n "$dynu_client_id" ]; then
    profile=dns-01
else
    profile=http-01
fi

exec docker compose --profile "$profile" up -d --build "$@"
