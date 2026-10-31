#!/usr/bin/env bash
# Local development CA + server certificates. In production, certs come from the
# real CA (cloud) and from the edge installer (LAN, pinned by fingerprint).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dev/certs"
mkdir -p "$OUT"

if [[ -f "$OUT/ca.pem" && -f "$OUT/cloud.pem" && -f "$OUT/edge.pem" ]]; then
  echo "[skip] certs already exist"
  exit 0
fi

openssl genrsa -out "$OUT/ca.key" 4096 2>/dev/null
openssl req -x509 -new -nodes -key "$OUT/ca.key" -sha256 -days 3650 \
  -subj "/CN=GameNet Dev CA/O=GameNet" -out "$OUT/ca.pem"

issue() { # name cn sans
  local name="$1" cn="$2" sans="$3"
  openssl genrsa -out "$OUT/$name.key" 2048 2>/dev/null
  openssl req -new -key "$OUT/$name.key" -subj "/CN=$cn/O=GameNet" -out "$OUT/$name.csr"
  openssl x509 -req -in "$OUT/$name.csr" -CA "$OUT/ca.pem" -CAkey "$OUT/ca.key" \
    -CAcreateserial -days 825 -sha256 -extfile <(printf "subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth" "$sans") \
    -out "$OUT/$name.pem" 2>/dev/null
  rm -f "$OUT/$name.csr"
}

issue cloud "cloud.local" "DNS:localhost,IP:127.0.0.1"
issue edge  "edge.local"  "DNS:localhost,IP:127.0.0.1"

FP="$(openssl x509 -in "$OUT/edge.pem" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':')"
echo "$FP" > "$OUT/edge.fingerprint"
echo "[ok] edge cert sha256: $FP"
