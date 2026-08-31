#!/bin/sh
set -eu

CUSTOM_CA_ROOT=/usr/local/share/ca-certificates/arachne

if [ -d "$CUSTOM_CA_ROOT" ] && find "$CUSTOM_CA_ROOT" -type f -name '*.crt' -print -quit | grep -q .; then
    echo "[arachne] updating CA trust store from $CUSTOM_CA_ROOT"
    update-ca-certificates
fi

exec "$@"
