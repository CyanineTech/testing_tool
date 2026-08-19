#!/bin/sh
set -eu

case "${PLATFORM_AUTH_ENABLED:-1}" in
  1|true|TRUE|yes|YES|on|ON)
    : "${PLATFORM_USER:?PLATFORM_USER must be set when auth is enabled}"
    : "${PLATFORM_PASSWORD:?PLATFORM_PASSWORD must be set when auth is enabled}"
    printf '%s:$apr1$%s\n' "$PLATFORM_USER" "$(openssl passwd -apr1 "$PLATFORM_PASSWORD" | cut -d '$' -f 3-)" > /etc/nginx/.htpasswd
    printf 'auth_basic "Testing Tool";\nauth_basic_user_file /etc/nginx/.htpasswd;\n' > /etc/nginx/conf.d/auth.inc
    ;;
  0|false|FALSE|no|NO|off|OFF)
    printf 'auth_basic off;\n' > /etc/nginx/conf.d/auth.inc
    ;;
  *)
    echo "PLATFORM_AUTH_ENABLED must be true or false" >&2
    exit 1
    ;;
esac
exec "$@"
