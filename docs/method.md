# method.md — driving TD Snap's editor (the playbook)

This is the distilled method from a real ~65-page production build (final
structural sweep: zero defects), including every edge case that bit us.
The agent does exactly what a human editor does, through synthesized mouse
and keyboard input, in visible batches, with verification points.

Prerequisites: an edit station (`edit-station.md`), a calibrated profile
(`calibration.md`), a compiled spec page (`tools/compile-page.py`), the
helper running (`tools/qahelper/build.md`).

## The shape of a page build

1. **Navigate to the parent page** in edit mode, select the door button that
   will lead to the new page, and use Link to Page → link to NEW page. The
   editor creates and names the page and jumps into it. Building the door
   first means the new page is born linked, never orphaned.
2. **Set the grid**: Page tab → Grid Size → toggle **Match Page Set OFF
   first** (law 3 in AGENTS.md; with Match ON you resize the entire page
   set) → pick the tile or custom rows/columns.
3. **Create buttons**: click an empty cell, type the label. TD Snap
   auto-fills the message AND auto-picks a symbol from the user's licensed
   library (high hit rate, including photos already in the page set's
   library). This auto-fill is why the toolkit never needs to touch symbols.
4. **Links to existing pages**: select button → Link to Page → link to
   EXISTING page → a search dialog finds any page by name. This step is an
   OPERATOR STOP in compiled batches: a person or the agent must visually
   confirm the right row (see search quirks below) before continuing.
5. **Rest cell** (if the spec has one): select the cell → Style →
   Background Color → pure black. Leave it action-free.
6. **Styles at scale**: use the multi-select icon, tap each target cell,
   **verify the selection badge equals the group size in a screenshot**,
   then apply Size / Layout once to the whole group. Inside the Size and
   Layout pickers, toggle "Match Page Set setting" OFF to reveal the lists.
7. **Silent navigation buttons**: Content tab → delete the "Speak or Insert
   Message" action row (a red confirm appears). Without this, a navigation
   button dumps its message into the message bar before navigating. Keep the
   speak action when saying the word is the point.
8. **Exit edit mode with Done**, leave the board on its home page with a
   cleared message bar.
9. **Verify the page in the database** (`qa.md`), update your build state,
   checkpoint on cadence.

## Batching discipline

- The helper silently drops batches over ~38 commands. The compiler chunks
  at logical boundaries; drivers refuse oversized batches. Never hand-edit a
  batch past the cap.
- Write command files atomically (write a temp file, then rename). The
  helper polls; a half-written file executes half a batch.
- Blind-chain only proven, toggle-free sequences. Anything involving a
  panel/collapse toggle or a selection diverges when run blind; those get a
  screenshot verification point.
- Screenshots are the token/attention budget killer. The winning loop reads
  one or two per page (grid verify + final) and checks everything else in
  the database for free.

## Edge-case catalog (all hit in production)

1. **Panel open vs collapsed is the #1 failure source.** Editor tabs sit at
   different heights depending on panel state, and grid cells under an open
   panel are unclickable. Your calibration profile must record both states
   and a known-safe "normalizer" click that lands harmlessly in either
   state. Screenshot when unsure.
2. **Drawer wedge**: tab clicks highlight but no drawer rises. Cause: an ESC
   keypress or a blind collapse-toggle. Recovery: restart TD Snap from the
   interactive session. Prevention is law 9: never ESC, never blind-toggle.
3. **Fake edit mode**: entering edit from some overlays yields a view where
   buttons still navigate. Verify REAL edit mode by its distinct banner and
   tab row before any batch. If buttons navigate, you are not in edit mode.
4. **Update dialogs appear frequently on edit-mode entry.** Screenshot
   first, cancel at the dialog's actual coordinates. Blind cancel clicks
   land on grid cells and create stray buttons. Never accept (law 6).
5. **Stray selection carry-in**: the last single-selected cell (often the
   just-styled black rest cell) silently joins the next multi-select. Always
   badge-check before applying styles.
6. **Search dialog quirks**: punctuation can break substring search (search
   a distinctive word from the title instead); select-all shortcuts do
   nothing in these fields (use the clear-X or repeated Backspace); when
   several rows share a name, a blank thumbnail is your just-created shell
   and a content thumbnail is a built or stock page.
7. **File dialogs** (importing a local page set copy): typed backslashes are
   eaten and the file-name field rejects forward slashes; type a plain
   filename there and drive the folder via the address bar's empty
   breadcrumb area instead.
8. **Auto-fit is not a font bug**: long labels render smaller with the font
   unchanged in the DB. Judge fonts by DB (law 5).
9. **Layout-row multiplicity**: pages keep a layout row per grid they ever
   had; verify placements against the active layout only (`internals.md`).
10. **Foreground stealers**: anything that pops or focuses another window
    mid-batch sends your clicks into it. Keep the edit station quiet: no
    scheduled tasks, notifications silenced, nothing else running.
11. **Editing existing pages**: small changes interactively with a DB check
    after; adding buttons goes into empty cells; never rearrange positions
    the AAC user has already learned. When a grid grows, the editor re-packs
    buttons into the first cells; restoring learned anchor positions needs a
    human (drag has no scripted equivalent; the helper deliberately has no
    drag command).
12. **The one true disaster pattern** (the reason for laws 2/3/4): a grid
    change with Match Page Set ON resized an entire page set, then
    delete-and-recreate of system buttons destroyed unrebuildable button
    configuration, then undo made it worse. Match OFF first; copy or move,
    never delete-and-recreate, buttons with system actions; recover by
    checkpoint restore, not undo.

## Cadence

Checkpoint every 4-10 pages. Verify every page in the DB before moving on.
Track built/shell/kept state in a small state file so recompiles know what
already exists (a door to an already-built page must compile as
link-to-existing, and a door to an unbuilt page as link-to-new). Report
progress to the human at checkpoints.
