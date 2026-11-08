#!/bin/bash
# Bind VESPER's rung-2 Claude credential to VESPER'S OWN account.
#
# WHY THIS SCRIPT EXISTS. Running `CLAUDE_CONFIG_DIR=... claude` on 2026-08-25
# silently reused the login the BROWSER already held, so the isolated config
# came up bound to the owner's personal account -- the exact opposite of the
# design, which exists so VESPER never competes with the owner for one pool.
#
# The failure was invisible: a working session, no error, wrong account. So
# this script CLEARS the credential first and VERIFIES the result after,
# rather than trusting that a login flow logged in as whom you meant.
set -u

DIR="$HOME/.config/vesper/claude-vesper"
# YOUR personal Claude login -- the one VESPER must NOT share. Read from the
# environment so no address is committed: VESPER_OWNER_EMAIL=you@example.com
OWNER_EMAIL="${VESPER_OWNER_EMAIL:?set VESPER_OWNER_EMAIL to your own Claude account email first}"

read_acct() {
  python3 -c "
import json,pathlib,sys
p=pathlib.Path('$DIR/.claude.json')
print(json.loads(p.read_text()).get('oauthAccount',{}).get('emailAddress','') if p.exists() else '')
" 2>/dev/null
}

echo "=== 1. current binding ==="
BEFORE="$(read_acct)"
echo "    ${BEFORE:-(none)}"

echo
echo "=== 2. clearing the isolated credential ==="
# Per-config-dir keychain service, hashed from the path. Only VESPER's entry is
# touched; the owner's default 'Claude Code-credentials' is never named here.
for svc in $(security dump-keychain 2>/dev/null \
             | grep -o '"Claude Code-credentials-[a-f0-9]*"' | tr -d '"' | sort -u); do
  security delete-generic-password -s "$svc" >/dev/null 2>&1 \
    && echo "    removed keychain item: $svc"
done
if [ -f "$DIR/.claude.json" ]; then
  python3 -c "
import json,pathlib
p=pathlib.Path('$DIR/.claude.json'); d=json.loads(p.read_text())
d.pop('oauthAccount',None)
p.write_text(json.dumps(d,indent=2))
" && echo "    cleared oauthAccount from the isolated config"
fi

echo
echo "=== 3. SIGN IN AS VESPER'S ACCOUNT ==============================="
echo "    A Claude session is about to open. At the prompt, type:  /login"
echo
echo "    IMPORTANT -- the browser is what picks the account:"
echo "      * sign out of claude.ai first, OR use a private window"
echo "      * otherwise it silently reuses the session already open,"
echo "        which is what went wrong last time"
echo
echo "    Sign in as VESPER'S account -- NOT $OWNER_EMAIL"
echo "    Then type /exit to come back here."
echo "================================================================="
echo
read -r -p "    press return to open the session... " _
CLAUDE_CONFIG_DIR="$DIR" claude

echo
echo "=== 4. verify (a login flow that ran is not a login that took) ==="
AFTER="$(read_acct)"
echo "    now bound to: ${AFTER:-(none)}"
echo
if [ -z "$AFTER" ]; then
  echo "    RESULT: FAIL -- not logged in. Re-run this script."; exit 1
elif [ "$AFTER" = "$OWNER_EMAIL" ]; then
  echo "    RESULT: FAIL -- still the OWNER's account."
  echo "    The browser reused your session. Sign out of claude.ai"
  echo "    completely, then re-run this script."; exit 1
else
  echo "    RESULT: PASS -- rung 2 is bound to a separate account."
  echo
  echo "    Last step, on THAT account (it is per-account):"
  echo "      Settings -> Privacy -> Help Improve Claude -> OFF"
  echo "      (on = up to 5 years in training pipelines; off = 30 days)"
fi
