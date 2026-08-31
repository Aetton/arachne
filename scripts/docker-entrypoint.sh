#!/bin/sh
set -eu

CUSTOM_CA_ROOT=/usr/local/share/ca-certificates/arachne

if [ -d "$CUSTOM_CA_ROOT" ] && find "$CUSTOM_CA_ROOT" -type f -name '*.crt' -print -quit | grep -q .; then
    echo "[arachne] updating CA trust store from $CUSTOM_CA_ROOT"
    update-ca-certificates
fi

if [ -n "${TOFU_PROVIDER_MIRROR:-}" ]; then
    mirror_url="$TOFU_PROVIDER_MIRROR"
    case "$mirror_url" in
        */) ;;
        *) mirror_url="${mirror_url}/" ;;
    esac

    echo "[arachne] configuring OpenTofu provider mirror: $mirror_url"
    cat > /root/.tofurc <<EOF
provider_installation {
  network_mirror {
    url     = "$mirror_url"
    include = ["registry.terraform.io/*/*"]
  }

  direct {
    exclude = ["registry.terraform.io/*/*"]
  }
}
EOF
else
    rm -f /root/.tofurc
fi

exec "$@"
