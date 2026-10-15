#!/usr/bin/env bash
# era-scan.sh <dir> — release-QC scanner (New ERA Communications, L3 gate).
# Scans every non-binary file under <dir> (skipping .git/, node_modules/, data/)
# for (a) generic secret patterns, (b) BLOCK-tier private terms, (c) WARN-tier
# family terms. Exit 1 on any (a)/(b) hit; exit 0 with a report for (c).
# The denylists live ONLY in era-family (private). Public repos get this script's
# generic layer via CI with the denylists injected as secrets.
set -u
DIR="${1:?usage: era-scan.sh <dir>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BLOCK="${ERA_DENYLIST_BLOCK:-$HERE/denylist-block.txt}"
WARN="${ERA_DENYLIST_WARN:-$HERE/denylist-warn.txt}"

EXCL="--binary-files=without-match --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=data --exclude-dir=tts-cache --exclude-dir=symbols-cache --exclude=era-scan.sh"
G="grep -rInE $EXCL"
GF="grep -rInF $EXCL"
fail=0

echo "== era-scan: $DIR =="

# (a) generic secret patterns — always fatal
PATTERNS='-----BEGIN[ A-Z]*PRIVATE KEY|sk-proj-[A-Za-z0-9]|sk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{32,}|gh[ops]_[A-Za-z0-9]{30,}|eyJ[A-Za-z0-9_-]{30,}\.eyJ|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|key_[a-f0-9]{24,}'
hits=$($G "$PATTERNS" "$DIR" 2>/dev/null)
if [ -n "$hits" ]; then echo "FATAL secret-pattern hits:"; echo "$hits" | head -40; fail=1; fi

# carrier-grade NAT IP range (100.64/10) — fatal
hits=$($G '\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}\b' "$DIR" 2>/dev/null)
if [ -n "$hits" ]; then echo "FATAL CGNAT-IP hits:"; echo "$hits" | head -40; fail=1; fi

# (b) BLOCK denylist — fatal
while IFS= read -r term; do
  [ -z "$term" ] && continue
  hits=$($GF -- "$term" "$DIR" 2>/dev/null | grep -v "era-scan.sh")
  if [ -n "$hits" ]; then echo "FATAL denylist term [$term]:"; echo "$hits" | head -20; fail=1; fi
done < "$BLOCK"

# (c) WARN denylist — reported, not fatal
warned=0
while IFS= read -r term; do
  [ -z "$term" ] && continue
  n=$($GF -c -- "$term" "$DIR" 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')
  if [ "$n" -gt 0 ]; then echo "warn [$term]: $n occurrence(s)"; warned=1; fi
done < "$WARN"

if [ "$fail" -eq 1 ]; then echo "== era-scan: FAILED (fatal findings above) =="; exit 1; fi
[ "$warned" -eq 1 ] && echo "== era-scan: PASS with warnings (genericize before public flip) ==" || echo "== era-scan: CLEAN =="
exit 0
