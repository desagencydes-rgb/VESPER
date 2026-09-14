#!/bin/sh
# Stands in for the `claude` CLI. MODE decides how it misbehaves, so every
# failure path is driven against a real process rather than mocked.
case "$FAKE_MODE" in
  hang)      sleep 300 ;;
  crash)     echo "boom: not logged in" >&2; exit 1 ;;
  # EXITS NON-ZERO *WITH* USABLE STDOUT, so the exit-code guard can be
  # pinned on its own. The plain `crash` case prints only to stderr, so
  # removing that guard was masked by the empty-output one -- two guards,
  # one mutation, and the red run came back green.
  crash_loud) echo "a plausible looking answer about three classes"; echo "rate limited" >&2; exit 2 ;;
  # EXPLAINS ITSELF ON STDOUT ONLY AND EXITS NON-ZERO. Two research steps failed
  # as "exit 1: no detail" on 2026-09-14 because only stderr was read.
  crash_stdout) echo "You've hit your session limit - resets 9pm"; exit 1 ;;
  empty)     printf "" ;;
  whitespace) printf "   \n\n" ;;
  huge)      i=0; while [ $i -lt 4000 ]; do printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; i=$((i+1)); done ;;
  children)  sleep 300 & sleep 300 ;;
  *)         echo "the file defines three classes and one helper" ;;
esac
