#!/usr/bin/env python3
"""make-fixture.py -- build a SYNTHETIC page set database from a spec.

Creates a small SQLite file with the same table/column shapes that
tools/qa-db.py reads (Page, PageLayout, ElementReference, ElementPlacement,
Button, CommandSequence). Every row is invented from the spec: page
UniqueIds are deterministic UUIDs derived from the page id, timestamps are a
made-up monotonic counter, symbol ids are placeholders. No real exported
page set file is ever shipped or required -- this fixture exists so the QA
tool can be exercised end to end in CI.

Usage:
    python3 tools/make-fixture.py <spec.json> <out.sqlite> [--defects N] [--seed S]

Modes:
    default        faithful fixture; qa-db.py must PASS against it.
    --defects N    seed N deliberate mismatches (wrong label, wrong position,
                   broken link, speak-on-silent, labeled rest cell, wrong
                   font, wrong layout, wrong grid) and print exactly what was
                   seeded; qa-db.py must FAIL and report each one.

Python 3 standard library only.
"""

import argparse
import json
import os
import random
import sqlite3
import sys
import uuid

SCHEMA = """
CREATE TABLE Page (
    Id INTEGER PRIMARY KEY,
    Title TEXT,
    UniqueId TEXT,
    GridDimension TEXT,
    Timestamp INTEGER
);
CREATE TABLE PageLayout (
    Id INTEGER PRIMARY KEY,
    PageId INTEGER,
    PageLayoutSetting TEXT
);
CREATE TABLE ElementReference (
    Id INTEGER PRIMARY KEY,
    BackgroundColor INTEGER
);
CREATE TABLE ElementPlacement (
    Id INTEGER PRIMARY KEY,
    ElementReferenceId INTEGER,
    PageLayoutId INTEGER,
    GridPosition TEXT,
    GridSpan TEXT
);
CREATE TABLE Button (
    Id INTEGER PRIMARY KEY,
    ElementReferenceId INTEGER,
    Label TEXT,
    Message TEXT,
    FontSize REAL,
    SmartSymLayout INTEGER,
    LibrarySymbolId INTEGER,
    PageSetImageId INTEGER
);
CREATE TABLE CommandSequence (
    Id INTEGER PRIMARY KEY,
    ButtonId INTEGER,
    SerializedCommands TEXT
);
"""

LAYOUT_VALUES = {
    "label-top": 0,
    "stacked": 1,
    "label-left": 2,
    "symbol-left": 3,
    "text-only": 4,
    "symbol-only": 5,
}

FAKE_TICKS_BASE = 638000000000000000  # invented .NET-ticks-like counter


def page_uid(page_id):
    """Deterministic invented UniqueId for a spec page id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "fixture-page:" + page_id))


def build_plan(spec):
    """Turn the spec into a flat list of button build records."""
    uids = {p["id"]: page_uid(p["id"]) for p in spec["pages"]}
    plan = []  # one dict per button
    for p in spec["pages"]:
        for btn in p.get("buttons", []):
            kind = btn.get("kind", "speak")
            commands = []
            if kind == "nav" or btn.get("navTo"):
                target = btn.get("navTo")
                commands.append({
                    "$type": "2",
                    "LinkedPageId": uids.get(target, str(uuid.uuid5(
                        uuid.NAMESPACE_URL, "fixture-missing:" + str(target)))),
                })
                if btn.get("speakToo"):
                    commands.append({"$type": "3", "Message": btn["label"]})
            elif kind == "speak" and not btn.get("silent"):
                commands.append({"$type": "3", "Message": btn.get("message", btn["label"])})
            plan.append({
                "page_id": p["id"],
                "label": "" if kind == "rest" else btn["label"],
                "message": None if kind == "rest" else btn.get("message", btn.get("label")),
                "pos": list(btn["pos"]),
                "font": btn.get("fontSize", 2.0),
                "layout": LAYOUT_VALUES.get(btn.get("layout"), 1),
                "symbol": None if kind == "rest" else 1,  # placeholder symbol id
                "kind": kind,
                "spec": btn,
                "commands": commands,
            })
    grids = {p["id"]: list(p["grid"]) for p in spec["pages"]}
    return uids, grids, plan


# ---------------------------------------------------------------------------
# Defect seeding: each defect type produces exactly one qa-db finding.
# ---------------------------------------------------------------------------

def defect_candidates(grids, plan):
    """List of (target_key, description, apply_fn) deliberate mismatches.

    target_key identifies what the defect touches. The seeder applies at most
    one defect per target so seeded defects can never mask each other (e.g. a
    wrong label on a button would hide a broken link on the same button,
    because qa-db stops checking a cell whose label is already wrong).
    """
    cands = []
    for n, rec in enumerate(plan):
        key = f"button:{n}"
        b, pid = rec["spec"], rec["page_id"]
        x, y = rec["pos"]
        if rec["kind"] == "rest":
            def mk_rest(r=rec):
                r["label"] = "oops"
            cands.append((key, f"labeled rest cell: page '{pid}' cell ({x},{y}) "
                          f"given label 'oops'", mk_rest))
            continue
        def mk_label(r=rec):
            r["label"] = r["label"] + " WRONG"
        cands.append((key, f"wrong label: page '{pid}' ({x},{y}) "
                      f"'{rec['label']}' -> '{rec['label']} WRONG'", mk_label))

        gx, gy = grids[pid]
        def mk_pos(r=rec, gx=gx, gy=gy):
            r["pos"] = [gx + 1, gy + 1]  # park it off-grid: spec cell now empty
        cands.append((key, f"wrong position: page '{pid}' '{rec['label']}' moved "
                      f"from ({x},{y}) to ({gx + 1},{gy + 1})", mk_pos))

        if b.get("fontSize") is not None:
            def mk_font(r=rec):
                r["font"] = (r["font"] or 1.0) + 1.0
            cands.append((key, f"wrong font size: page '{pid}' '{rec['label']}' "
                          f"{rec['font']} -> {rec['font'] + 1.0}", mk_font))

        if b.get("layout") in LAYOUT_VALUES:
            other = (LAYOUT_VALUES[b["layout"]] + 1) % 6
            def mk_layout(r=rec, other=other):
                r["layout"] = other
            cands.append((key, f"wrong layout: page '{pid}' '{rec['label']}' "
                          f"SmartSymLayout {rec['layout']} -> {other}", mk_layout))

        if rec["kind"] == "nav" or b.get("navTo"):
            def mk_link(r=rec):
                for c in r["commands"]:
                    if "LinkedPageId" in c:
                        c["LinkedPageId"] = str(uuid.uuid5(
                            uuid.NAMESPACE_URL, "fixture-broken-link"))
            cands.append((key, f"broken link: page '{pid}' '{rec['label']}' now "
                          f"links to a nonexistent page", mk_link))
            if not b.get("speakToo"):
                def mk_speak(r=rec):
                    r["commands"].append({"$type": "3", "Message": r["label"]})
                cands.append((key, f"speak-on-silent: page '{pid}' "
                              f"'{rec['label']}' given a speak command", mk_speak))
    for pid, (gx, gy) in grids.items():
        def mk_grid(pid=pid, gx=gx, gy=gy):
            grids[pid] = [gx + 1, gy]
        cands.append((f"grid:{pid}", f"wrong grid: page '{pid}' {gx}x{gy} -> "
                      f"{gx + 1}x{gy}", mk_grid))
    return cands


def pick_defects(cands, n, seed):
    """Choose n defects, at most one per target_key, reproducibly."""
    rng = random.Random(seed)
    rng.shuffle(cands)
    chosen, used = [], set()
    for key, desc, fn in cands:
        if key in used:
            continue
        used.add(key)
        chosen.append((desc, fn))
        if len(chosen) == n:
            return chosen
    sys.exit(f"error: only {len(chosen)} independent defect targets available")


def write_db(path, spec, uids, grids, plan):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    page_rows = {}   # page id -> Page.Id
    layout_rows = {}  # page id -> PageLayout.Id
    for i, p in enumerate(spec["pages"]):
        gx, gy = grids[p["id"]]
        cur = db.execute(
            "INSERT INTO Page (Title, UniqueId, GridDimension, Timestamp) "
            "VALUES (?,?,?,?)",
            (p["title"], uids[p["id"]], f"{gx},{gy}", FAKE_TICKS_BASE + i),
        )
        page_rows[p["id"]] = cur.lastrowid
        cur = db.execute(
            "INSERT INTO PageLayout (PageId, PageLayoutSetting) VALUES (?,?)",
            (page_rows[p["id"]], f"{gx},{gy},False,0"),
        )
        layout_rows[p["id"]] = cur.lastrowid
    for rec in plan:
        cur = db.execute(
            "INSERT INTO ElementReference (BackgroundColor) VALUES (?)",
            (-16777216 if rec["kind"] == "rest" else -1,),
        )
        er_id = cur.lastrowid
        db.execute(
            "INSERT INTO ElementPlacement (ElementReferenceId, PageLayoutId, "
            "GridPosition, GridSpan) VALUES (?,?,?,?)",
            (er_id, layout_rows[rec["page_id"]],
             f"{rec['pos'][0]},{rec['pos'][1]}", "1,1"),
        )
        cur = db.execute(
            "INSERT INTO Button (ElementReferenceId, Label, Message, FontSize, "
            "SmartSymLayout, LibrarySymbolId, PageSetImageId) "
            "VALUES (?,?,?,?,?,?,?)",
            (er_id, rec["label"], rec["message"], rec["font"], rec["layout"],
             rec["symbol"], None),
        )
        if rec["commands"]:
            db.execute(
                "INSERT INTO CommandSequence (ButtonId, SerializedCommands) "
                "VALUES (?,?)",
                (cur.lastrowid, json.dumps({"Commands": rec["commands"]})),
            )
    db.commit()
    db.close()


def main():
    ap = argparse.ArgumentParser(
        description="Generate a synthetic page set SQLite fixture from a spec."
    )
    ap.add_argument("spec", help="spec JSON file")
    ap.add_argument("out", help="output SQLite file (overwritten)")
    ap.add_argument("--defects", type=int, default=0, metavar="N",
                    help="seed N deliberate mismatches (default 0 = faithful)")
    ap.add_argument("--seed", type=int, default=0,
                    help="random seed for defect selection (default 0)")
    args = ap.parse_args()

    try:
        spec = json.load(open(args.spec))
    except (OSError, ValueError) as e:
        sys.exit(f"error: cannot read spec: {e}")
    if not spec.get("pages"):
        sys.exit("error: spec has no pages")

    uids, grids, plan = build_plan(spec)

    if args.defects:
        cands = defect_candidates(grids, plan)
        for desc, apply_fn in pick_defects(cands, args.defects, args.seed):
            apply_fn()
            print("SEEDED:", desc)

    if os.path.exists(args.out):
        os.remove(args.out)
    write_db(args.out, spec, uids, grids, plan)
    n_pages = len(spec["pages"])
    print(f"wrote {args.out}: {n_pages} page(s), {len(plan)} button(s), "
          f"{args.defects} seeded defect(s)")


if __name__ == "__main__":
    main()
