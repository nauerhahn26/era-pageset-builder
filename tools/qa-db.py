#!/usr/bin/env python3
"""qa-db.py -- read-only structural QA for a built TD Snap page set.

Verifies that the pages described in a spec JSON actually exist in the page
set database with the right structure. This is the trust anchor of the build
pipeline: several properties (font scale, a button's silent/speaking state,
which page a link really lands on) are invisible or unreliable in screenshots,
but they are all plain rows in the page set's SQLite database.

Usage:
    python3 tools/qa-db.py <spec.json> <pageset.sqlite> [--page <title>]

    <spec.json>        page spec (see docs/qa.md for the supported shape)
    <pageset.sqlite>   a COPY of the page set database file
    --page <title>     verify only this page (repeatable); default: all pages

IMPORTANT -- always run against a COPY of the page set file, never the live
one. TD Snap keeps its database open with write-ahead logging; reading the
file while the app owns it can see a torn/stale view. Copy the file (with its
sidecar -wal/-shm files if present, or after the app has been closed) and
point this tool at the copy. The database is additionally opened in
read-only mode (SQLite mode=ro URI) so this tool can never modify anything.

Checks per page:
  * grid dimensions (PageLayout.PageLayoutSetting "cols,rows,...")
  * every spec button exists at its grid position with the exact label
  * font size, where the spec specifies one (Button.FontSize is a
    multiplier: 3.0 means 300% in the editor UI)
  * symbol layout, where the spec specifies one (Button.SmartSymLayout)
  * page links resolve to the correct TARGET page (the serialized command
    references the target page's UniqueId -- we resolve it back to a title)
  * silent buttons carry no speak command; speak-and-navigate buttons do
  * rest cells are present and empty (no label, no speak command)

Exit status: 0 = all checks passed, 1 = one or more findings (or bad input).
This is deliberate: wire this into the build so any finding BLOCKS the build.
Python 3 standard library only.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from urllib.request import pathname2url

# Button.SmartSymLayout empirical value map (per-button, so layouts can mix
# freely on one page). Spec files use the names on the left.
LAYOUT_VALUES = {
    "label-top": 0,     # text on top, symbol below
    "stacked": 1,       # symbol on top, text below (common page-set default)
    "label-left": 2,    # text left, symbol right
    "symbol-left": 3,   # symbol left, text right
    "text-only": 4,     # no symbol shown
    "symbol-only": 5,   # no text shown
}
INHERIT_VALUES = (None, 6)  # NULL / 6 = inherit the page-set default

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def open_readonly(path):
    """Open a SQLite database strictly read-only (mode=ro URI)."""
    if not os.path.exists(path):
        sys.exit(f"error: database file not found: {path}")
    uri = "file:" + pathname2url(os.path.abspath(path)) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def parse_commands(blob):
    """Extract (linked_page_uids, has_speak) from a serialized command blob.

    The command sequence is JSON: entries with $type "2" are page links
    (carrying a LinkedPageId = the target page's UniqueId) and entries with
    $type "3" are speak/insert-message actions. We walk the parsed JSON when
    possible and fall back to pattern matching so minor format drift between
    app versions does not break QA.
    """
    blob = blob or ""
    links, has_speak = [], False

    def walk(node):
        nonlocal has_speak
        if isinstance(node, dict):
            if str(node.get("$type", "")) == "3":
                has_speak = True
            lp = node.get("LinkedPageId")
            if lp:
                links.append(str(lp))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    try:
        walk(json.loads(blob))
    except ValueError:
        links.extend(UUID_RE.findall(blob))
        if re.search(r'"\$type"\s*:\s*"?3"?', blob):
            has_speak = True
    return links, has_speak


def load_page_buttons(db, page_db_id):
    """Map (x, y) grid position -> device button facts for one page."""
    rows = db.execute(
        """SELECT b.Id, b.Label, b.Message, b.FontSize, b.SmartSymLayout,
                  ep.GridPosition
           FROM Button b
           JOIN ElementReference er ON er.Id = b.ElementReferenceId
           JOIN ElementPlacement ep ON ep.ElementReferenceId = er.Id
           JOIN PageLayout pl ON pl.Id = ep.PageLayoutId
           WHERE pl.PageId = ?""",
        (page_db_id,),
    )
    dev = {}
    for bid, label, message, font, layout, grid_pos in rows:
        if not grid_pos:
            continue
        try:
            x, y = (int(v) for v in grid_pos.split(",")[:2])
        except ValueError:
            continue
        dev[(x, y)] = {
            "id": bid,
            "label": label or "",
            "message": message,
            "font": font,
            "layout": layout,
        }
    return dev


def button_commands(db, button_id):
    row = db.execute(
        "SELECT SerializedCommands FROM CommandSequence WHERE ButtonId = ?",
        (button_id,),
    ).fetchone()
    return parse_commands(row[0] if row else "")


def verify_page(db, page, target_titles, findings):
    """Run all checks for one spec page; append finding strings on mismatch."""
    title = page["title"]

    def fail(msg):
        findings.append(f"[{title}] {msg}")

    row = db.execute(
        "SELECT Id FROM Page WHERE Title = ? ORDER BY Timestamp DESC LIMIT 1",
        (title,),
    ).fetchone()
    if not row:
        fail("page not found in database")
        return
    page_db_id = row[0]

    # --- grid dimensions --------------------------------------------------
    cols, rows_n = page["grid"]
    layouts = [
        r[0]
        for r in db.execute(
            "SELECT PageLayoutSetting FROM PageLayout WHERE PageId = ?",
            (page_db_id,),
        )
        if r[0]
    ]
    if not layouts:
        fail("no PageLayout row (cannot verify grid)")
    else:
        def grid_of(setting):
            parts = setting.split(",")
            return (parts[0], parts[1]) if len(parts) >= 2 else (None, None)

        if not any(grid_of(g) == (str(cols), str(rows_n)) for g in layouts):
            fail(f"grid is {layouts!r}, spec wants {cols}x{rows_n}")

    dev = load_page_buttons(db, page_db_id)

    # --- per-button checks ------------------------------------------------
    for btn in page.get("buttons", []):
        x, y = btn["pos"]
        kind = btn.get("kind", "speak")
        d = dev.get((x, y))

        if kind == "rest":
            # Rest cell: a deliberately blank, non-speaking target.
            if not d:
                fail(f"rest cell missing at ({x},{y})")
                continue
            if d["label"]:
                fail(f"rest cell ({x},{y}) has label '{d['label']}' (must be empty)")
            _, speaks = button_commands(db, d["id"])
            if speaks:
                fail(f"rest cell ({x},{y}) has a speak command (must be silent)")
            continue

        if not d:
            fail(f"'{btn['label']}' missing at ({x},{y})")
            continue

        # label (exact, whitespace-trimmed)
        if d["label"].strip() != btn["label"].strip():
            fail(f"({x},{y}) label '{d['label']}' != spec '{btn['label']}'")
            continue  # wrong button in the cell; deeper checks are noise

        # font size, where specified
        want_font = btn.get("fontSize")
        if want_font is not None:
            if d["font"] is None or abs(d["font"] - want_font) > 0.01:
                fail(f"'{btn['label']}' FontSize={d['font']} != spec {want_font}")

        # symbol layout, where specified
        want_layout = btn.get("layout")
        if want_layout is not None:
            if want_layout not in LAYOUT_VALUES:
                fail(f"'{btn['label']}' spec layout '{want_layout}' unknown "
                     f"(use one of {sorted(LAYOUT_VALUES)})")
            elif d["layout"] != LAYOUT_VALUES[want_layout]:
                fail(f"'{btn['label']}' SmartSymLayout={d['layout']} != "
                     f"spec '{want_layout}' ({LAYOUT_VALUES[want_layout]})")

        # links and speak/silent state
        if kind == "nav" or btn.get("navTo"):
            link_uids, speaks = button_commands(db, d["id"])
            want_title = target_titles.get(btn.get("navTo"), btn.get("navTo"))
            hit_titles = []
            for uid in link_uids:
                for t in db.execute(
                    "SELECT Title FROM Page WHERE UniqueId = ?", (uid,)
                ):
                    hit_titles.append(t[0])
            if want_title not in hit_titles:
                fail(f"'{btn['label']}' links to {hit_titles!r}, "
                     f"spec wants '{want_title}'")
            if btn.get("speakToo") and not speaks:
                fail(f"'{btn['label']}' should speak before navigating "
                     f"but has NO speak command")
            if not btn.get("speakToo") and speaks:
                fail(f"'{btn['label']}' should be SILENT but has a speak command")
        elif btn.get("silent"):
            _, speaks = button_commands(db, d["id"])
            if speaks:
                fail(f"'{btn['label']}' marked silent but has a speak command")


def main():
    ap = argparse.ArgumentParser(
        description="Read-only structural QA: verify a built page set "
                    "database against its spec. Run against a COPY of the "
                    "page set file, never the live one."
    )
    ap.add_argument("spec", help="spec JSON file")
    ap.add_argument("database", help="COPY of the page set SQLite file")
    ap.add_argument(
        "--page", action="append", metavar="TITLE",
        help="verify only this page title (repeatable)",
    )
    args = ap.parse_args()

    try:
        spec = json.load(open(args.spec))
    except (OSError, ValueError) as e:
        sys.exit(f"error: cannot read spec: {e}")

    pages = spec.get("pages", [])
    if not pages:
        sys.exit("error: spec has no pages")

    # navTo values reference page ids; resolve them to titles once.
    target_titles = {p.get("id"): p["title"] for p in pages if p.get("id")}

    if args.page:
        wanted = set(args.page)
        pages = [p for p in pages if p["title"] in wanted]
        missing = wanted - {p["title"] for p in pages}
        if missing:
            sys.exit(f"error: page(s) not in spec: {', '.join(sorted(missing))}")

    db = open_readonly(args.database)
    findings = []
    checked = 0
    for page in pages:
        before = len(findings)
        verify_page(db, page, target_titles, findings)
        checked += 1
        status = "PASS" if len(findings) == before else "FAIL"
        print(f"{status}  {page['title']}")
    db.close()

    for f in findings:
        print("FINDING:", f)
    print(f"checked {checked} page(s), {len(findings)} finding(s)")
    if findings:
        print("RESULT: FAIL -- do not ship this build")
        sys.exit(1)
    print("RESULT: PASS")


if __name__ == "__main__":
    main()
