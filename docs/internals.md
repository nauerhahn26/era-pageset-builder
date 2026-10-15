# internals.md — the read-only database facts verification needs

Everything below was learned by observing page set files on our own devices,
for one purpose: verifying that a build matches its spec. It is the minimum
`tools/qa-db.py` needs. This toolkit opens the database READ-ONLY, always on
a COPY, and never writes page content to it. Page sets are signed by the
editor; this toolkit writes only through the editor and does not attempt to
forge signatures.

## Getting a safe copy

- A TD Snap page set is a SQLite database (`.sps` file) under the app's
  LocalState. The live file is locked open by TD Snap but copies fine while
  the app runs (plain file copy). Always analyze the copy, never the live
  file, and account for WAL: copy the `-wal`/`-shm` siblings with it, or
  copy from the app's restore-point folder for a settled snapshot.
- Open with a read-only URI: `sqlite3 'file:copy.sps?mode=ro'`.

## Schema (the verification subset)

- `Page` — Title, GridDimension, UniqueId, Timestamp (.NET ticks).
- `PageLayout` — PageLayoutSetting, a string like `4,3,False,0`
  (columns, rows, ...). A page KEEPS one layout row for every grid it has
  ever had. Naive joins across all layouts produce phantom duplicates; when
  verifying placements, query only the active layout.
- `ElementReference` — joins a page to its buttons.
- `ElementPlacement` — GridPosition as `"x,y"` (0-based), GridSpan.
- `Button` — Label, Message, FontSize, SmartSymLayout, LibrarySymbolId,
  ElementReferenceId. FontSize is a multiplier (3.0 shows as 300% in the
  editor UI). Very long labels auto-fit smaller on screen while FontSize is
  unchanged in the DB — judge fonts by DB only.
- `CommandSequence` — SerializedCommands, a JSON list of actions:
  `$type` 2 = navigate, with a LinkedPageId referencing the target page's
  UniqueId; `$type` 3 = speak/insert message. A "silent" navigation button
  is one whose sequence has a navigate action and NO speak action.
- `PageSetProperties` — FriendlyName, DefaultHomePageUniqueId.

## SmartSymLayout (per-button symbol/label layout)

| Value | Meaning (editor UI name) |
|---|---|
| 0 | Label Top, Image Bottom |
| 1 | Label Bottom, Image Top |
| 2 | Label Left, Image Right |
| 3 | Label Right, Image Left |
| 4 | Label Only |
| 5 | Image Only |
| 6 / NULL | Match Page Set setting (inherit) |

A practical eye-gaze lesson: keep one font size page-wide; give long words
the stacked layout (1) so the text gets the full cell width, and short words
a side-by-side layout (3), on the same page. Never shrink the font per word.

## Verification rules that came from real defects

- Links bind by UniqueId, not by title. Renaming a page never breaks links,
  so "build under a temporary title, rename at the end" is safe.
- When comparing two devices' copies of a page set, join by page Title +
  button Label, never by row ids (ids differ per device).
- Rest cells (a plain black, actionless cell some eye-gaze users need as a
  visual resting place) verify as: present at the specified position, black
  background, no actions.
- Grid checks pass if ANY PageLayout row matches the spec's grid (see the
  layout-multiplicity note above), but placements must come from the active
  layout only.
