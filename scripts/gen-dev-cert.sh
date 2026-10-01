#!/usr/bin/env bash
# Generate a self-signed TLS certificate for local HTTPS (encryption in transit).
# Prefer `mkcert` if installed (trusted by your browser); falls back to openssl.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$DIR"
if command -v mkcert >/dev/null 2>&1; then
  mkcert -install
  mkcert -key-file "$DIR/dev-key.pem" -cert-file "$DIR/dev-cert.pem" localhost 127.0.0.1 ::1
else
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout "$DIR/dev-key.pem" -out "$DIR/dev-cert.pem" \
    -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi
chmod 600 "$DIR/dev-key.pem"
echo "Certificates written to $DIR (git-ignored)."
