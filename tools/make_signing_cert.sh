#!/bin/sh
# A stable local code-signing identity for VESPER.
#
# WHAT THIS FIXES, AND WHAT IT DOES NOT. TCC permission grants are keyed to a
# code signature's designated requirement. Ad-hoc signing (`codesign -s -`) has no
# stable identity, so macOS may re-prompt for every permission each time the binary
# changes. A self-signed certificate gives a STABLE identity and the grants stick.
#
# It does NOT make Gatekeeper call VESPER identified. System Settings will still say
# "Item from unidentified developer" -- that requires a Developer ID certificate
# from the paid Apple Developer Program plus notarisation, and no local certificate
# substitutes for it. This is about permissions persisting, nothing more.
#
# Local to this machine. The private key never leaves the login keychain.
set -e
CN="VESPER Local Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CN"; then
  echo "already present: $CN"
  exit 0
fi

openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
  -subj "/CN=$CN/O=VESPER" \
  -addext "basicConstraints=critical,CA:false" \
  -addext "keyUsage=critical,digitalSignature" \
  -addext "extendedKeyUsage=critical,codeSigning" 2>/dev/null

# A REAL PASSWORD, not an empty one. An empty-password PKCS#12 imports as "MAC
# verification failed (wrong password?)" on this platform -- an error that sends
# you hunting for an algorithm mismatch. It is not the algorithm: macOS's openssl
# is LibreSSL, whose defaults are already compatible. The password is transient and
# the file is deleted on exit.
P12PASS=vesper-transient
openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
  -out "$TMP/vesper.p12" -passout "pass:$P12PASS" -name "$CN" 2>/dev/null

# -T /usr/bin/codesign lets codesign use the key without prompting on every sign.
security import "$TMP/vesper.p12" -k "$KEYCHAIN" -P "$P12PASS" \
  -T /usr/bin/codesign -T /usr/bin/security >/dev/null

# TRUST IS NOT OPTIONAL. Importing succeeds and `find-identity -v -p codesigning`
# still reports zero: -v lists VALID identities, and an untrusted self-signed cert
# is not one. Code signing for code signing only, user trust domain, no sudo --
# macOS asks for the login password once.
security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" "$TMP/cert.pem" \
  || echo "NOTE: trust step declined or failed -- signing may still work, verification will not"

# Stop the keychain prompting on each use by this identity.
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "" "$KEYCHAIN" >/dev/null 2>&1 || true

echo
security find-identity -v -p codesigning | grep "$CN" || echo "identity not visible yet"
