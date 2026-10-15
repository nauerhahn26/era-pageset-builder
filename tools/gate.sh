#!/usr/bin/env bash
# gate.sh — must pass before any commit reaches the public repo.
# Suites: syntax, compiler goldens, qa-db fixture round-trip, drivers,
# doc-link integrity, content scrub. Run from anywhere.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FAIL=0
t() { # t <name> <cmd...>
  local name="$1"; shift
  if "$@" >/tmp/gate.$$ 2>&1; then echo "ok   $name"
  else echo "FAIL $name"; sed 's/^/     /' /tmp/gate.$$ | head -15; FAIL=1; fi
}

# 1. Python syntax
t "py-syntax" bash -c 'for f in $(find tools -name "*.py"); do python3 -m py_compile "$f" || exit 1; done'

# 2. JSON validity
t "json-valid" bash -c 'for f in spec/*.json profiles/*.json; do python3 -m json.tool "$f" >/dev/null || exit 1; done'

# 3. Compiler determinism vs goldens (both demo pages)
t "compile-goldens" bash -c '
  out=$(mktemp -d)
  python3 tools/compile-page.py spec/example-board.json --page "Demo Home" \
    --profile profiles/example-2736x1824.json --out "$out/home" || exit 1
  python3 tools/compile-page.py spec/example-board.json --page "Demo Snacks" \
    --profile profiles/example-2736x1824.json --built home --out "$out/snacks" || exit 1
  diff -r tools/testdata/home "$out/home" || exit 1
  diff -r tools/testdata/snacks "$out/snacks" || exit 1
  rm -rf "$out"'

# 4. Batch cap: no golden batch exceeds 38 commands
t "batch-cap" bash -c '
  for f in tools/testdata/*/[0-9]*.txt; do
    n=$(grep -cve "^\s*$" "$f")
    [ "$n" -le 38 ] || { echo "$f has $n commands"; exit 1; }
  done'

# 5. qa-db round-trip: faithful fixture passes, seeded defects all caught
t "qa-pass" bash -c '
  fx=$(mktemp -u).sqlite
  python3 tools/make-fixture.py spec/example-board.json "$fx" || exit 1
  python3 tools/qa-db.py spec/example-board.json "$fx" || exit 1
  rm -f "$fx"'
t "qa-fail-catches-3" bash -c '
  fx=$(mktemp -u).sqlite
  python3 tools/make-fixture.py spec/example-board.json "$fx" --defects 3 --seed 7 || exit 1
  if python3 tools/qa-db.py spec/example-board.json "$fx" >/tmp/qa.$$ 2>&1; then
    echo "qa-db passed a defective fixture"; exit 1; fi
  n=$(grep -c "FAIL" /tmp/qa.$$); rm -f "$fx"
  [ "$n" -ge 3 ] || { echo "only $n findings for 3 defects"; cat /tmp/qa.$$; exit 1; }'

# 6. Shell drivers parse
t "sh-syntax" bash -c 'bash -n tools/drive-ssh.sh && bash -n tools/gate.sh'

# 7. Doc-link integrity: every repo-relative path mentioned in the docs exists
t "doc-links" bash -c '
  refs=$(grep -rhoE "(docs|tools|spec|profiles)/[A-Za-z0-9_.-]+" AGENTS.md README.md docs/*.md | sort -u)
  for r in $refs; do [ -e "$r" ] || { echo "dangling reference: $r"; exit 1; }; done'

# 8. Content scrub (beyond era-scan): integrity-scheme vocabulary is banned
#    outside the single canonical sentence; circumvention vocabulary is banned
#    everywhere. Tracked+staged files only.
t "scrub-vocab" bash -c '
  files=$( (git ls-files; git diff --cached --name-only; git ls-files --others --exclude-standard) | sort -u | grep -v "^tools/gate.sh$" )
  python3 - $files <<"PYEOF"
import re, sys
bad = 0
BANNED = re.compile(r"hmac|tamper|circumvent|key.?extract", re.I)
ALLOWED = re.compile(r"signed by the editor|forge signatures", re.I)
for path in sys.argv[1:]:
    try: text = open(path, encoding="utf-8", errors="replace").read()
    except IsADirectoryError: continue
    for m in BANNED.finditer(text):
        print(f"{path}: banned term {m.group(0)!r}"); bad = 1
    flat = re.sub(r"\s+", " ", text)
    for sent in re.split(r"(?<=[.!?])\s", flat):
        if re.search(r"signat", sent, re.I) and not ALLOWED.search(sent):
            print(f"{path}: stray signature talk: {sent[:100]}"); bad = 1
sys.exit(bad)
PYEOF'

# 9. era-scan (family scanner if present, else the committed generic layer)
if [ -f "$HOME/new-era/era-family/tools/era-scan.sh" ]; then
  t "era-scan" bash "$HOME/new-era/era-family/tools/era-scan.sh" "$ROOT"
else
  t "era-scan-generic" bash .github/era-scan.sh "$ROOT"
fi

rm -f /tmp/gate.$$ /tmp/qa.$$ 2>/dev/null
if [ "$FAIL" -eq 0 ]; then echo "== gate: GREEN =="; else echo "== gate: RED =="; exit 1; fi
