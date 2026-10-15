#!/usr/bin/env python3
"""compile-page.py -- compile one spec page into helper command batches.

Turns one page of a board spec (spec/spec-schema.json) into numbered batch
files of input-automation commands for the helper (tools/qahelper/). The
helper executes them in the TD Snap for Windows editor exactly as a human
would: click a cell, type a label, set the grid, wire page links, apply
styles. See docs/method.md for the full playbook this compiler encodes.

Usage:
    python3 tools/compile-page.py <spec.json> --page <title> \
        --profile <profile.json> --out <dir> [--built id1,id2,...]

    <spec.json>   the board spec (all pages; links resolve across pages)
    --page        title (or id) of the ONE page to compile
    --profile     calibration profile for THIS machine (docs/calibration.md);
                  every screen coordinate comes from here, none are built in
    --out         output directory: writes 00.txt, 01.txt, ... + manifest.txt
    --built       comma-separated ids (or titles) of pages that already exist
                  on the edit station, so links to them compile as
                  link-to-EXISTING (an operator stop) instead of link-to-new

Preconditions (the operator/agent establishes these before batch 00):
  * TD Snap is in REAL edit mode (verify the banner; see docs/method.md on
    fake edit mode) and showing the EMPTY target page.
  * The helper is running and the update dialog, if any, has been dismissed.

Command syntax emitted (one command per line, executed in order):
    CLICK x y | TYPE text | SLEEP ms
(The helper also supports MOVE/DBL/RCLICK/KEY/SCROLL; this compiler does not
need them.) Batches are capped at the profile's max_batch_commands
(default 38): the helper silently drops longer batches.

Phases per page (docs/method.md, "The shape of a page build"):
  A  grid      Page tab -> Grid Size -> Match Page Set OFF FIRST (law 3)
               -> rows -> columns. Checkpoint: verify the grid.
  B  buttons   per button: select cell, type label (the editor auto-fills
               message and symbol), and for door buttons wire the page link.
               Links to not-yet-built pages use link-to-NEW (the editor
               creates the shell page); links to built pages use
               link-to-EXISTING, which ends the batch at an OPERATOR STOP so
               a human/agent can pick the right search row.
  C  rest      rest cells (plain black, action-free cells that give an
               eye-gaze user somewhere safe to look) get Style -> Background
               Color -> black. Checkpoint: verify labels + black cells.
  D  styles    multi-select passes grouped by (fontSize, layout). Checkpoint
               between selecting and applying: verify the selection badge.
  E  silence   buttons that must not speak (page links without "speakToo",
               and any button marked "silent") get their speak action row
               deleted in the Content tab.

Deterministic: the same spec + profile + --built set always produces
byte-identical batches, so goldens under tools/testdata/ can gate changes.

Python 3 standard library only.
"""

import argparse
import json
import sys
from pathlib import Path

# Layout names a spec may use (must match tools/qa-db.py LAYOUT_VALUES).
# The compiler only APPLIES layouts the profile has a picker position for
# (profile key style_layout_options); qa-db can verify all of these.
KNOWN_LAYOUTS = (
    "label-top", "stacked", "label-left", "symbol-left", "text-only",
    "symbol-only",
)

BUTTON_KINDS = ("speak", "nav", "rest")

# Points the compiler clicks. The profile must define each one under
# "points" as {"xy": [x, y], "sleep_ms": n, "note": "..."}.
REQUIRED_POINTS = (
    "panel_collapse",        # chevron: collapse the edit panel
    "button_tab_collapsed",  # Button tab, panel collapsed (the normalizer)
    "page_tab",              # Page tab, panel open
    "page_grid_size",        # Page tab left menu: Grid Size
    "grid_match_toggle",     # Match Page Set toggle inside Grid Size
    "grid_size_picker",      # opens the grid size picker
    "grid_rows_arrow",       # Rows row arrow in the picker
    "grid_back",             # back arrow to the Grid Size root
    "grid_columns_scroll",   # scrollbar TRACK click revealing Columns
    "grid_columns_arrow",    # Columns row arrow in the picker
    "button_content_tab",    # Button panel left menu: Content
    "button_label_field",    # the Label text field
    "button_link_tab",       # Button panel left menu: Link to Page
    "link_existing",         # "link to existing page" entry
    "link_search_field",     # search field in the existing-page dialog
    "link_create_confirm",   # Create button (clicked by the OPERATOR)
    "link_new",              # "link to new page" entry
    "link_new_create",       # Create button in the new-page dialog
    "button_style_tab",      # Button panel left menu: Style
    "style_bg_color_arrow",  # Background Color row arrow
    "style_color_black",     # black swatch in the color picker
    "multiselect_toggle",    # multi-select icon (badge shows the count)
    "style_scroll_track",    # Style panel scrollbar TRACK
    "style_size_row",        # Size row in the Style panel
    "style_match_toggle",    # Match Page Set toggle inside Size/Layout
    "style_size_list_scroll",   # size list scrollbar TRACK
    "style_back",            # back arrow to the Style root
    "style_layout_row",      # Layout row in the Style panel
    "style_layout_list_scroll", # layout list scrollbar TRACK
    "content_speak_delete",  # trash icon on the speak action row
    "delete_confirm",        # red confirm for the deletion
)

# Fallbacks only; profiles normally carry their own timings_ms block.
DEFAULT_TIMINGS_MS = {
    "panel_normalize_ms": 1000,   # settle after the batch-00 normalizer click
    "cell_select_ms": 800,        # settle after selecting a grid cell
    "multiselect_tap_ms": 250,    # settle between multi-select cell taps
    "selection_settle_ms": 400,   # settle after the last multi-select tap
    "panel_race_guard_ms": 800,   # guard after re-opening the panel mid-pass
    "style_tab_multiselect_ms": 1400,  # Style tab is slower with a selection
    "label_type_settle_ms": 600,  # settle after typing a label
    "link_type_settle_ms": 400,   # settle after typing a new page title
    "link_search_settle_ms": 1500,  # settle after typing into page search
    "picker_option_ms": 1100,     # settle after clicking a list option
    "multiselect_off_ms": 600,    # settle after toggling multi-select off
}


class CompileError(Exception):
    """Input problem (spec or profile); reported without a traceback."""


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------

class Profile:
    """Calibration profile: every coordinate and settle time for one machine."""

    def __init__(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            raise CompileError(f"cannot read profile {path}: {exc}")
        self.data = data
        self.name = data.get("name", Path(path).stem)
        self.max_batch = int(data.get("max_batch_commands", 38))
        if self.max_batch < 10:
            raise CompileError("profile max_batch_commands is implausibly small")
        self.points = data.get("points", {})
        missing = [p for p in REQUIRED_POINTS if p not in self.points]
        if missing:
            raise CompileError(
                "profile is missing point(s): " + ", ".join(missing)
                + " -- run the calibration pass (docs/calibration.md)")
        for name, pt in self.points.items():
            xy = pt.get("xy") if isinstance(pt, dict) else None
            if (not isinstance(xy, list) or len(xy) != 2
                    or not all(isinstance(v, int) for v in xy)):
                raise CompileError(
                    f"profile point '{name}' must be an object with"
                    ' "xy": [x, y] (integers)')
        self.timings = dict(DEFAULT_TIMINGS_MS)
        self.timings.update(data.get("timings_ms", {}))
        if "value_list" not in data:
            raise CompileError('profile is missing the "value_list" block')

    def xy(self, name):
        return tuple(self.points[name]["xy"])

    def settle(self, name):
        return int(self.points[name].get("sleep_ms", 0))

    def timing(self, key):
        return int(self.timings[key])

    def grid_axis(self, axis, n, page_title):
        table = self.data.get("grid", {}).get(axis, {})
        if str(n) not in table:
            raise CompileError(
                f"profile has no grid.{axis} entry for {n} cells (needed by"
                f" page '{page_title}') -- calibrate that grid size and add it")
        centers = table[str(n)]
        if len(centers) != n:
            raise CompileError(
                f"profile grid.{axis}[{n}] must list exactly {n} centers")
        return centers

    def value_row(self, n):
        """Click position for row n of the rows/columns value list."""
        vl = self.data["value_list"]
        if str(n) not in vl.get("row_y", {}):
            raise CompileError(
                f"profile value_list.row_y has no entry for value {n}"
                " -- calibrate more list rows (or scroll support) to use it")
        return int(vl["x"]), int(vl["row_y"][str(n)])

    def size_option(self, size_key):
        opts = self.data.get("style_size_options", {})
        if size_key not in opts:
            raise CompileError(
                f"profile style_size_options has no entry for fontSize"
                f" {size_key} (have: {', '.join(sorted(opts)) or 'none'})")
        return tuple(opts[size_key])

    def layout_option(self, layout):
        opts = self.data.get("style_layout_options", {})
        if layout not in opts:
            raise CompileError(
                f"profile style_layout_options has no entry for layout"
                f" '{layout}' (have: {', '.join(sorted(opts)) or 'none'})")
        return tuple(opts[layout])


# --------------------------------------------------------------------------
# batch emitter
# --------------------------------------------------------------------------

class Emitter:
    """Collects commands into batches capped at max_batch commands.

    A "unit" is an atomic command run that must not straddle a batch
    boundary (e.g. select cell + open panel + type label): if a unit would
    overflow the current batch, it moves whole into a new one.
    """

    def __init__(self, max_batch):
        self.max_batch = max_batch
        self.batches = [[]]
        self.notes = [""]  # notes[i] = operator note BEFORE running batch i
        self.panel_open = True
        self._unit = None

    def cmd(self, *lines):
        target = self._unit if self._unit is not None else self.batches[-1]
        target.extend(lines)

    def unit_begin(self):
        self._unit = []

    def unit_end(self):
        unit, self._unit = self._unit, None
        if len(self.batches[-1]) + len(unit) > self.max_batch:
            self.batches.append([])
            self.notes.append("(continued; no checkpoint needed)")
        self.batches[-1].extend(unit)

    def split(self, note):
        """End the current batch; `note` tells the operator what to do
        before running the next one."""
        self.batches.append([])
        self.notes.append(note)


# --------------------------------------------------------------------------
# spec validation
# --------------------------------------------------------------------------

def size_key(font_size):
    """Canonical profile key for a fontSize multiplier: 3.0 -> "3"."""
    return f"{float(font_size):g}"


def validate_spec(spec):
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CompileError('spec must have a non-empty "pages" array')
    ids, titles = set(), set()
    for page in pages:
        pid, title = page.get("id"), page.get("title")
        if not pid or not title:
            raise CompileError('every page needs both "id" and "title"')
        if pid in ids:
            raise CompileError(f"duplicate page id '{pid}'")
        if title in titles:
            raise CompileError(f"duplicate page title '{title}'")
        ids.add(pid)
        titles.add(title)
        if "\\" in title:
            raise CompileError(
                f"page '{pid}': backslash in title (the helper's TYPE"
                " command drops backslashes)")
        grid = page.get("grid")
        if (not isinstance(grid, list) or len(grid) != 2
                or not all(isinstance(v, int) and v >= 1 for v in grid)):
            raise CompileError(
                f"page '{pid}': grid must be [columns, rows] (integers >= 1)")
        cols, rows = grid
        seen_pos = set()
        for btn in page.get("buttons", []):
            pos = btn.get("pos")
            if (not isinstance(pos, list) or len(pos) != 2
                    or not all(isinstance(v, int) for v in pos)):
                raise CompileError(
                    f"page '{pid}': every button needs pos [col, row]")
            x, y = pos
            if not (0 <= x < cols and 0 <= y < rows):
                raise CompileError(
                    f"page '{pid}': button at ({x},{y}) is outside the"
                    f" {cols}x{rows} grid (positions are 0-based)")
            if (x, y) in seen_pos:
                raise CompileError(
                    f"page '{pid}': two buttons share position ({x},{y})")
            seen_pos.add((x, y))
            kind = btn.get("kind", "speak")
            if kind not in BUTTON_KINDS:
                raise CompileError(
                    f"page '{pid}' ({x},{y}): unknown kind '{kind}'"
                    f" (use one of: {', '.join(BUTTON_KINDS)})")
            if kind == "rest":
                if btn.get("label") or btn.get("navTo"):
                    raise CompileError(
                        f"page '{pid}' ({x},{y}): rest cells carry no label"
                        " and no link")
                continue
            label = btn.get("label")
            if not label or not label.strip():
                raise CompileError(
                    f"page '{pid}' ({x},{y}): '{kind}' buttons need a label")
            if "\\" in label or "\n" in label:
                raise CompileError(
                    f"page '{pid}': label '{label}' contains a backslash or"
                    " newline (the helper's TYPE command cannot send those)")
            if kind == "nav" or btn.get("navTo"):
                nav_to = btn.get("navTo")
                if not nav_to:
                    raise CompileError(
                        f"page '{pid}': nav button '{label}' needs navTo")
                if nav_to not in ids and not any(
                        p.get("id") == nav_to for p in pages):
                    raise CompileError(
                        f"page '{pid}': '{label}' links to unknown page id"
                        f" '{nav_to}'")
            layout = btn.get("layout")
            if layout is not None and layout not in KNOWN_LAYOUTS:
                raise CompileError(
                    f"page '{pid}': '{label}' has unknown layout '{layout}'"
                    f" (use one of: {', '.join(KNOWN_LAYOUTS)})")
            fs = btn.get("fontSize")
            if fs is not None and not isinstance(fs, (int, float)):
                raise CompileError(
                    f"page '{pid}': '{label}' fontSize must be a number"
                    " (a multiplier: 3.0 means 300%)")
    # navTo may reference pages later in the file; re-check now that all ids
    # are known (the loop above already collected them incrementally, so a
    # forward reference could have been flagged; verify cleanly here).
    for page in pages:
        for btn in page.get("buttons", []):
            nav_to = btn.get("navTo")
            if nav_to and nav_to not in ids:
                raise CompileError(
                    f"page '{page['id']}': link target id '{nav_to}' is not"
                    " a page in this spec")


def is_silent(btn):
    """True when phase E must remove the button's speak action."""
    if btn.get("kind") == "rest":
        return False  # rest cells never get a speak action to begin with
    if btn.get("kind") == "nav" or btn.get("navTo"):
        return not btn.get("speakToo")
    return bool(btn.get("silent"))


# --------------------------------------------------------------------------
# compilation
# --------------------------------------------------------------------------

def compile_page(spec, page, built, prof):
    pages_by_id = {p["id"]: p for p in spec["pages"]}
    cols, rows = page["grid"]
    xs = prof.grid_axis("columns_x", cols, page["title"])
    ys = prof.grid_axis("rows_y", rows, page["title"])
    e = Emitter(prof.max_batch)

    def click_xy(x, y, settle):
        e.cmd(f"CLICK {x} {y}")
        if settle > 0:
            e.cmd(f"SLEEP {settle}")

    def click(point, settle=None):
        x, y = prof.xy(point)
        click_xy(x, y, prof.settle(point) if settle is None else settle)

    def click_cell(btn, settle):
        x, y = btn["pos"]
        click_xy(xs[x], ys[y], settle)

    def collapse_panel():
        if e.panel_open:
            click("panel_collapse")
            e.panel_open = False

    def open_panel():
        if not e.panel_open:
            click("button_tab_collapsed")
            e.panel_open = True

    def begin_button_unit(btn):
        """Normalize panel, select the button's cell, open the panel."""
        e.unit_begin()
        e.panel_open = True  # assume open; collapse explicitly to normalize
        collapse_panel()
        click_cell(btn, prof.timing("cell_select_ms"))
        open_panel()

    # ---- phase A: grid ---------------------------------------------------
    # The first click doubles as the session normalizer: if the panel is
    # collapsed it opens it; if the panel is open it lands harmlessly in
    # panel content. After it, panel state is KNOWN open.
    click("button_tab_collapsed", settle=prof.timing("panel_normalize_ms"))
    e.panel_open = True
    click("page_tab")
    click("page_grid_size")
    click("grid_match_toggle")     # law 3: Match Page Set OFF before ANY
    click("grid_size_picker")      # grid change
    click("grid_rows_arrow")
    click_xy(*prof.value_row(rows), settle=prof.timing("picker_option_ms"))
    click("grid_back")
    click("grid_columns_scroll")
    click("grid_columns_arrow")
    click_xy(*prof.value_row(cols), settle=prof.timing("picker_option_ms"))
    e.split(f"CHECKPOINT: screenshot and verify the grid is now {cols}"
            f" columns x {rows} rows (and that Match Page Set is OFF)."
            " Then run the next batch.")
    e.panel_open = True

    # ---- phase B: create + label + link ----------------------------------
    content = [b for b in page.get("buttons", []) if b.get("kind") != "rest"]
    for btn in content:
        begin_button_unit(btn)
        click("button_content_tab")
        click("button_label_field")
        e.cmd(f"TYPE {btn['label']}",
              f"SLEEP {prof.timing('label_type_settle_ms')}")
        if btn.get("navTo"):
            target_title = pages_by_id[btn["navTo"]]["title"]
            click("button_link_tab")
            if btn["navTo"] in built:
                click("link_existing")
                click("link_search_field")
                e.cmd(f"TYPE {target_title}",
                      f"SLEEP {prof.timing('link_search_settle_ms')}")
                e.unit_end()
                ccx, ccy = prof.xy("link_create_confirm")
                e.split(
                    "OPERATOR STOP: a page-search list is open. Verify the"
                    f" results and click the row for '{target_title}' (a"
                    " blank thumbnail is a just-created shell page; a content"
                    " thumbnail is a built or stock page), then click Create"
                    f" at {ccx},{ccy}. Then run the next batch.")
                e.panel_open = True
                continue
            click("link_new")
            e.cmd(f"TYPE {target_title}",
                  f"SLEEP {prof.timing('link_type_settle_ms')}")
            click("link_new_create")
            built.add(btn["navTo"])  # the editor just created the shell
        e.unit_end()

    # ---- phase C: rest cells ---------------------------------------------
    for btn in page.get("buttons", []):
        if btn.get("kind") != "rest":
            continue
        begin_button_unit(btn)
        click("button_style_tab")
        click("style_bg_color_arrow")
        click("style_color_black")
        e.unit_end()
    e.split("CHECKPOINT: screenshot and verify every button has the right"
            " label and every rest cell is solid black. Then run the style"
            " batches.")
    e.panel_open = True

    # ---- phase D: style passes (multi-select, grouped) -------------------
    groups = {}
    for btn in content:
        fs = btn.get("fontSize")
        key = (None if fs is None else size_key(fs), btn.get("layout"))
        if key == (None, None):
            continue
        groups.setdefault(key, []).append(btn)
    for (fs_key, layout), group in groups.items():
        # Resolve picker positions up front so a profile gap fails the
        # compile, not the middle of a build.
        size_pos = prof.size_option(fs_key) if fs_key else None
        layout_pos = prof.layout_option(layout) if layout else None
        e.unit_begin()
        e.panel_open = True
        collapse_panel()
        click("multiselect_toggle")
        for btn in group:
            click_cell(btn, prof.timing("multiselect_tap_ms"))
        e.cmd(f"SLEEP {prof.timing('selection_settle_ms')}")
        e.unit_end()
        e.split(f"CHECKPOINT: verify the multi-select badge shows exactly"
                f" {len(group)} selected (a stray earlier selection can"
                " silently join). Then run the next batch.")
        e.unit_begin()
        open_panel()
        e.cmd(f"SLEEP {prof.timing('panel_race_guard_ms')}")
        click("button_style_tab",
              settle=prof.timing("style_tab_multiselect_ms"))
        click("style_scroll_track")
        if size_pos:
            click("style_size_row")
            click("style_match_toggle")
            click("style_size_list_scroll")
            click_xy(*size_pos, settle=prof.timing("picker_option_ms"))
        if layout_pos:
            if size_pos:
                click("style_back")
            click("style_layout_row")
            click("style_match_toggle")
            click("style_layout_list_scroll")
            click_xy(*layout_pos, settle=prof.timing("picker_option_ms"))
        click("multiselect_toggle", settle=prof.timing("multiselect_off_ms"))
        e.panel_open = True
        e.unit_end()
    if groups:
        e.split("CHECKPOINT: screenshot and verify the styles (font sizes"
                " and layouts) landed on the right buttons. Then run the"
                " silence batches.")
        e.panel_open = True

    # ---- phase E: silence ------------------------------------------------
    for btn in content:
        if not is_silent(btn):
            continue
        begin_button_unit(btn)
        click("button_content_tab")
        click("content_speak_delete")
        click("delete_confirm")
        e.unit_end()

    return e


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def finalize_batches(e):
    """Drop empty batches (folding their notes forward) and de-duplicate
    consecutive identical batches. Returns (batches, notes, final_note)."""
    batches, notes = [], []
    pending = []
    for cmds, note in zip(e.batches, e.notes):
        if note and note != "(continued; no checkpoint needed)":
            pending.append(note)
        if not cmds:
            continue
        if batches and cmds == batches[-1]:
            continue  # guard: never emit the same batch twice in a row
        batches.append(cmds)
        notes.append(" ".join(pending))
        pending = []
    return batches, notes, " ".join(pending)


def write_output(out_dir, page, prof, batches, notes, final_note):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in sorted(out.glob("*.txt")):
        stale.unlink()  # recompiles must never leave stale batches behind
    lines = [
        f"# compile-page manifest -- page '{page['title']}'"
        f" (id: {page['id']}), profile '{prof.name}'",
        "# Run batches in order. Each 'before' line is an operator",
        "# checkpoint to satisfy BEFORE running that batch.",
    ]
    total = 0
    sleep_ms = 0
    for i, (cmds, note) in enumerate(zip(batches, notes)):
        name = f"{i:02d}.txt"
        (out / name).write_text("\n".join(cmds) + "\n", encoding="utf-8")
        if note:
            lines.append(f"before {name}: {note}")
        lines.append(f"{name}: {len(cmds)} commands")
        total += len(cmds)
        sleep_ms += sum(int(c.split()[1]) for c in cmds
                        if c.startswith("SLEEP "))
    if final_note:
        lines.append(f"after the last batch: {final_note}")
    lines.append("after the page: exit edit mode with Done, then verify the"
                 " page in the database (tools/qa-db.py) before moving on.")
    lines.append(f"total: {total} commands in {len(batches)} batches,"
                 f" ~{sleep_ms // 1000}s scripted sleep")
    (out / "manifest.txt").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8")
    return total, sleep_ms


def main():
    ap = argparse.ArgumentParser(
        description="Compile one spec page into helper command batches."
                    " All coordinates come from the calibration profile;"
                    " see docs/calibration.md.")
    ap.add_argument("spec", help="board spec JSON (spec/spec-schema.json)")
    ap.add_argument("--page", required=True,
                    help="title (or id) of the page to compile")
    ap.add_argument("--profile", required=True,
                    help="calibration profile JSON for this machine")
    ap.add_argument("--out", required=True,
                    help="output directory for batch files + manifest")
    ap.add_argument("--built", default="",
                    help="comma-separated ids/titles of pages already built"
                         " on the edit station (links to them become"
                         " link-to-existing)")
    args = ap.parse_args()

    try:
        try:
            with open(args.spec, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as exc:
            raise CompileError(f"cannot read spec {args.spec}: {exc}")
        validate_spec(spec)
        prof = Profile(args.profile)

        pages = spec["pages"]
        by_title = {p["title"]: p for p in pages}
        by_id = {p["id"]: p for p in pages}
        page = by_title.get(args.page) or by_id.get(args.page)
        if page is None:
            raise CompileError(
                f"page '{args.page}' not in spec (titles: "
                + ", ".join(sorted(by_title)) + ")")

        built = set()
        for token in filter(None, (t.strip()
                                   for t in args.built.split(","))):
            if token in by_id:
                built.add(token)
            elif token in by_title:
                built.add(by_title[token]["id"])
            else:
                raise CompileError(
                    f"--built entry '{token}' is not a page id or title in"
                    " this spec")

        e = compile_page(spec, page, built, prof)
        batches, notes, final_note = finalize_batches(e)
        over = [i for i, b in enumerate(batches) if len(b) > prof.max_batch]
        if over:  # invariant; the emitter should make this impossible
            raise CompileError(
                f"internal error: batch(es) {over} exceed"
                f" {prof.max_batch} commands")
        total, sleep_ms = write_output(args.out, page, prof, batches,
                                       notes, final_note)
    except CompileError as exc:
        sys.exit(f"error: {exc}")

    print(f"compiled page '{page['title']}' -> {args.out}:"
          f" {len(batches)} batches, {total} commands,"
          f" ~{sleep_ms // 1000}s scripted sleep")
    print("read manifest.txt for the operator checkpoints between batches")


if __name__ == "__main__":
    main()
