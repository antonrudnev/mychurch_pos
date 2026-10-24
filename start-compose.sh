#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir"

read_env_value() {
    awk -v key="$1" '
        /^[[:space:]]*#/ { next }
        {
            line = $0
            sub(/^[[:space:]]*/, "", line)
            if (line !~ ("^" key "[[:space:]]*=")) {
                next
            }
            value = substr(line, index(line, "=") + 1)
            sub(/[[:space:]]+#.*/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            if (value ~ /^".*"$/ || value ~ /^'\''.*'\''$/) {
                value = substr(value, 2, length(value) - 2)
            }
            print value
            exit
        }
    ' .env
}

dynu_client_id=${DYNU_CLIENT_ID:-}
if [ -z "$dynu_client_id" ]; then
    unset DYNU_CLIENT_ID
    if [ -f .env ]; then
        dynu_client_id=$(read_env_value DYNU_CLIENT_ID)
    fi
fi

dynu_client_secret=${DYNU_CLIENT_SECRET:-}
if [ -z "$dynu_client_secret" ]; then
    unset DYNU_CLIENT_SECRET
    if [ -f .env ]; then
        dynu_client_secret=$(read_env_value DYNU_CLIENT_SECRET)
    fi
fi

if [ -n "$dynu_client_id" ] && [ -n "$dynu_client_secret" ]; then
    profile=dns-01
else
    profile=http-01
fi

exec docker compose --profile "$profile" up -d --build "$@"
