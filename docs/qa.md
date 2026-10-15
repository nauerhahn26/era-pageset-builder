# Database QA: verifying a built page against its spec

The read half of the builder. After pages are built in the TD Snap editor,
`tools/qa-db.py` proves -- from the page set's own SQLite database -- that
what exists on the device matches the spec. A QA failure is a build failure:
**no page set revision reaches the user until qa-db passes.**

## Why verify in the database, not by screenshot

Screenshots feel like proof but miss exactly the things that go wrong:

- **Font size is unreliable on screen.** `Button.FontSize` is a multiplier
  (3.0 = 300% in the editor UI). A screenshot cannot tell 2.8 from 3.0, and
  rendering differences between devices make eyeballing worse than useless.
- **A button's silent/speaking state is invisible.** A navigation button that
  wrongly keeps its speak action looks identical to a silent one; the user
  only discovers it when the button dumps text into the message bar before
  navigating. In the database it is one row: the presence or absence of a
  speak entry in the button's serialized command sequence.
- **Link targets can look right and be wrong.** Two pages can share a label
  or near-identical titles (page sets accumulate duplicate "Foods" pages over
  years of edits). The command sequence stores the target page's `UniqueId`;
  resolving that id back to a title is the only proof of where a link lands.
- **Layout and grid are exact values, not impressions.** `SmartSymLayout` and
  `PageLayoutSetting` are integers/strings the spec pins precisely.

Screenshots still have a place (a human sanity pass), but the database is
the ground truth, so the gate reads the database.

## Copy-first, read-only discipline

Never point qa-db at the live page set file:

1. TD Snap keeps the database open with write-ahead logging. Reading the
   file underneath the running app can see a torn or stale view.
2. QA must be incapable of causing the thing it checks for.

So the rule is: **copy the page set file, run QA on the copy.** Copy while
the app is closed, or include the `-wal`/`-shm` sidecar files so the copy is
consistent. As a second layer, qa-db opens the database with SQLite's
`mode=ro` URI -- the connection itself cannot write, ever.

## Running it

```
python3 tools/qa-db.py <spec.json> <pageset-copy.sqlite> [--page <title>]
```

- Exit 0 and `RESULT: PASS` -- every checked page matches the spec.
- Exit 1 and `RESULT: FAIL` -- one `FINDING:` line per mismatch. The build
  stops here.
- `--page <title>` (repeatable) limits the run to specific pages, e.g. the
  page you just built. The default run checks every page in the spec.

## What each check covers

| Check | Database source | Fails when |
|---|---|---|
| Grid dimensions | `PageLayout.PageLayoutSetting` (`"cols,rows,..."`) | no layout matches the spec's `grid: [cols, rows]` |
| Button presence + label | `Button.Label` joined through `ElementReference` -> `ElementPlacement.GridPosition` | the spec cell is empty, or the label differs (exact match, trimmed) |
| Font size | `Button.FontSize` | differs from spec `fontSize` by more than 0.01 (checked only where the spec specifies one) |
| Symbol layout | `Button.SmartSymLayout` | differs from the spec `layout` name's value (checked only where specified) |
| Page links | `CommandSequence.SerializedCommands` link entries -> `Page.UniqueId` -> `Page.Title` | the resolved target title is not the spec's `navTo` page |
| Silent vs speaking | speak entries in the same command sequence | a silent button speaks, or a `speakToo` button doesn't |
| Rest cells | all of the above | the cell is missing, has a label, or has a speak command |

A wrong label short-circuits the deeper checks for that cell (the cell holds
the wrong button; reporting its font would be noise).

`SmartSymLayout` value map used by both tools: 0 label-top, 1 stacked
(symbol above text), 2 label-left, 3 symbol-left, 4 text-only,
5 symbol-only, NULL/6 inherit the page-set default. Spec files use the
names; the database stores the numbers.

## Spec shape (the subset qa-db reads)

```json
{
  "pages": [
    {
      "id": "food",
      "title": "Food",
      "grid": [4, 3],
      "buttons": [
        {"pos": [0, 0], "label": "apple", "kind": "speak",
         "fontSize": 3.0, "layout": "symbol-left"},
        {"pos": [1, 1], "kind": "rest"},
        {"pos": [0, 2], "label": "back", "kind": "nav", "navTo": "home"},
        {"pos": [3, 2], "label": "play", "kind": "nav", "navTo": "play",
         "speakToo": true}
      ]
    }
  ]
}
```

`navTo` references another page's `id`; qa-db resolves it to that page's
`title` before comparing. A `nav` button without `speakToo` must be silent.
`fontSize` and `layout` are optional; unspecified means unchecked.

## Testing the tester: tools/make-fixture.py

QA that is never seen to fail cannot be trusted. `make-fixture.py` builds a
fully synthetic SQLite file from a spec -- same tables and columns qa-db
reads, invented ids throughout, no exported page set file involved:

```
python3 tools/make-fixture.py spec.json fixture.sqlite            # faithful
python3 tools/make-fixture.py spec.json broken.sqlite --defects 3 # sabotaged
```

The faithful fixture must PASS. `--defects N` seeds N deliberate mismatches
(wrong label, wrong position, wrong font, wrong layout, broken link,
speak-on-silent, labeled rest cell, wrong grid), prints each one, and qa-db
must FAIL reporting all N -- at most one defect is seeded per target so
defects can never mask each other. `--seed` makes the selection
reproducible. Wire both directions into CI: the gate is only green when the
faithful fixture passes AND the sabotaged one fails with the right count.

## The rule

QA failure blocks the build. Not "note it and fix later" -- the failing
revision does not get deployed, synced, or shown. A communication device is
the user's voice; a wrong link or a button that speaks when it should not is
a real cost to a real person, and the cheapest place to catch it is a SELECT
statement before the build ships.
