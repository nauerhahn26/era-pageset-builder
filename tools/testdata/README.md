# testdata — compiler goldens

Committed output of `tools/compile-page.py` run on the demo spec with the
example profile. The compiler is deterministic (same spec + profile +
`--built` set gives byte-identical batches), so the gate recompiles the demo
pages and diffs against these directories; any difference fails the gate.

Regenerate (from the repo root) after an INTENTIONAL compiler, spec, or
profile change, review the diff, and commit it with the change:

```
python3 tools/compile-page.py spec/example-board.json --page "Demo Home" \
    --profile profiles/example-2736x1824.json --out tools/testdata/home
python3 tools/compile-page.py spec/example-board.json --page "Demo Snacks" \
    --profile profiles/example-2736x1824.json --built home \
    --out tools/testdata/snacks
```

`home/` compiles with nothing built yet, so its door to Snacks is a
link-to-NEW page. `snacks/` compiles with `--built home`, so its door back
is a link-to-EXISTING page and contains an operator stop. Between them the
two pages cover every compiler phase: grid setup, button create+label,
both link flows, rest cells, both style-pass shapes (size+layout and
size-only), the silence phase, and the no-silence case (where the final
checkpoint note folds into the manifest instead).

Each directory holds numbered batch files (`00.txt`, `01.txt`, ... — one
helper command per line, every batch at or under the 38-command cap) plus
`manifest.txt` listing batch sizes and the operator checkpoints between
batches. These files are test fixtures for generic demo content; nothing
here is meant to be replayed against a real page set.
