#!/bin/sh
set -eu

# Serves the frontend over HTTPS. Default: an OpenSSL self-signed cert generated
# here. If the backend has written a company cert to /certs/custom/{tls.crt,tls.key}
# we use that instead, and a watcher hot-reloads Caddy when it changes.

CUSTOM_CRT=/certs/custom/tls.crt
CUSTOM_KEY=/certs/custom/tls.key
# Persist the self-signed cert in the certs volume so it is stable across restarts
# (regenerating it each boot would break fetches in already-open browser tabs).
SELF_DIR=/certs/selfsigned
TLS_CONF=/etc/caddy/tls.conf

mkdir -p /etc/caddy /certs/custom "$SELF_DIR" /srv

ensure_selfsigned() {
	if [ ! -s "$SELF_DIR/tls.crt" ] || [ ! -s "$SELF_DIR/tls.key" ]; then
		openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
			-keyout "$SELF_DIR/tls.key" -out "$SELF_DIR/tls.crt" \
			-subj "/CN=xyberah.local" \
			-addext "subjectAltName=DNS:localhost,DNS:xyberah.local,IP:127.0.0.1" >/dev/null 2>&1
	fi
}

write_tls() {
	if [ -s "$CUSTOM_CRT" ] && [ -s "$CUSTOM_KEY" ]; then
		echo "tls $CUSTOM_CRT $CUSTOM_KEY" > "$TLS_CONF"
		echo "custom"
	else
		ensure_selfsigned
		echo "tls $SELF_DIR/tls.crt $SELF_DIR/tls.key" > "$TLS_CONF"
		echo "self_signed"
	fi
}

fingerprint() {
	cat "$CUSTOM_CRT" "$CUSTOM_KEY" 2>/dev/null | sha256sum 2>/dev/null | cut -d' ' -f1 || echo none
}

mode=$(write_tls)
echo "[proxy] starting with $mode certificate"
caddy start --config /etc/caddy/Caddyfile --adapter caddyfile
last=$(fingerprint)

# Watch for cert changes uploaded through the Settings UI
while true; do
	sleep 5
	now=$(fingerprint)
	if [ "$now" != "$last" ]; then
		mode=$(write_tls)
		echo "[proxy] certificate changed -> $mode, reloading"
		caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || echo "[proxy] reload failed"
		last="$now"
	fi
done
