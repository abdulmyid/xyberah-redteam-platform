#!/bin/sh
set -eu

# Serves the frontend over HTTPS. Default: Caddy's internal self-signed cert.
# If the backend has written a company cert to /certs/custom/{tls.crt,tls.key}
# we use that instead, and a watcher hot-reloads Caddy when it changes.

SNIPPET=/etc/caddy/tls_snippet.caddy
CUSTOM_CRT=/certs/custom/tls.crt
CUSTOM_KEY=/certs/custom/tls.key

write_snippet() {
	if [ -s "$CUSTOM_CRT" ] && [ -s "$CUSTOM_KEY" ]; then
		echo "(tls_directive) {" > "$SNIPPET"
		echo "  tls $CUSTOM_CRT $CUSTOM_KEY" >> "$SNIPPET"
		echo "}" >> "$SNIPPET"
		echo "custom"
	else
		printf '(tls_directive) {\n  tls internal\n}\n' > "$SNIPPET"
		echo "self_signed"
	fi
}

fingerprint() {
	cat "$CUSTOM_CRT" "$CUSTOM_KEY" 2>/dev/null | sha256sum 2>/dev/null | cut -d' ' -f1 || echo none
}

mkdir -p /etc/caddy /certs/custom /srv
mode=$(write_snippet)
echo "[proxy] starting with $mode certificate"

caddy start --config /etc/caddy/Caddyfile --adapter caddyfile
last=$(fingerprint)

# Watch for cert changes uploaded through the Settings UI
while true; do
	sleep 5
	now=$(fingerprint)
	if [ "$now" != "$last" ]; then
		mode=$(write_snippet)
		echo "[proxy] certificate changed -> $mode, reloading"
		caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || echo "[proxy] reload failed"
		last="$now"
	fi
done
