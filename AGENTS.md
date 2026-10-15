# era-pageset-builder — orientation for the agent running this toolkit

This repo is an agent-run toolkit that builds and verifies AAC page sets in
TD Snap for Windows by driving TD Snap's own editor, the same way a human
editor would: real mouse and keyboard input, batch-scripted, then verified
structurally in the page set database (read-only).

It is unofficial and not affiliated with or endorsed by Tobii Dynavox. The
person you are helping must own a licensed copy of TD Snap. Nothing in this
repo contains Tobii Dynavox software, symbols, or content.

You are probably being run by a parent, caregiver, SLP, or teacher who wants
to build or restructure pages for an AAC user. Read this file fully, then
`docs/edit-station.md` for the setup, before touching anything.

## Laws (unbreakable — every one of these was learned in production)

1. **Writes go through the editor only.** Page sets are signed by the editor;
   this toolkit writes only through the editor and does not attempt to forge
   signatures. The SQLite database is opened READ-ONLY, for verification.
2. **Cloud-checkpoint before any editing session** (Page Set tab → save a copy
   to myTobiiDynavox, named `ck1`, `ck2`, ...). Checkpoint again every 4-10
   pages. Restoring a checkpoint is deterministic; the editor's undo is not a
   reliable recovery tool. Restore beats undo.
3. **Toggle "Match Page Set" OFF before ANY grid change.** With Match ON, a
   grid change resizes the ENTIRE page set, every page. This is the single
   worst failure this method has ever produced. Toggle OFF, verify, then change.
4. **Never delete a button carrying system actions or Active Content**
   (time, date, volume, calibration, status). Some carry configuration that
   cannot be rebuilt from the editor's action list. Copy-paste or move such
   buttons; never delete-and-recreate.
5. **Verify in the database, not by eye.** Font sizes and silent-button state
   are invisible or misleading in screenshots. `tools/qa-db.py` failure blocks
   the build; nothing ships to the AAC user unverified.
6. **Never accept a software-update dialog mid-build.** Screenshot first, then
   cancel it (blind clicks land on grid cells and create stray buttons). The
   device owner decides updates, on their schedule, not the automation.
7. **Sync is manual.** TD Snap page sets sync only when someone taps
   "Sync Page Set" on a device. Finish a build, verify it, then tell the human
   to sync the edit station first and each receiving device after.
8. **Practice on a locally imported copy first.** A cloud-synced page set
   propagates to every device on the account. Import a local copy (no cloud
   badge) for your first sessions and for experiments.
9. **Never press ESC and never blind-toggle panels** in the editor; both can
   wedge the edit drawer (recovery: restart TD Snap). Normalize panel state
   with the known-safe click from your calibration profile, and screenshot
   when unsure.

## Workflow (the proven loop)

1. **Set up the edit station** — `docs/edit-station.md`.
2. **Calibrate** — `docs/calibration.md` walks you through discovering the
   editor's UI coordinates on THIS machine into `profiles/<name>.json`.
   Recalibrate after any resolution, scaling, or TD Snap version change.
3. **Write the spec with the human** — `spec/spec-schema.json` defines the
   format; `spec/example-board.json` is a worked demo. Design guidance for
   eye-gaze users: big fonts, few choices per page, a rest cell.
4. **Checkpoint** (law 2).
5. **Compile and build** — `tools/compile-page.py` turns a spec page into
   command batches; drive them through the helper (`tools/qahelper/`,
   `tools/drive-local.ps1` or `tools/drive-ssh.sh`). Method, edge cases, and
   recovery: `docs/method.md`. Batches are capped at 38 commands: the helper
   silently drops longer ones.
6. **Verify** — copy the page set file, run `tools/qa-db.py` against the spec
   (`docs/qa.md`, `docs/internals.md`). Fix and re-verify until clean.
7. **Checkpoint again, then sync** (law 7).

## Map

- `docs/edit-station.md` — topology: which machine runs what, and why.
- `docs/calibration.md` — coordinate discovery method (per machine).
- `docs/method.md` — the editor-driving playbook and edge-case catalog.
- `docs/internals.md` — the read-only database facts verification needs.
- `docs/qa.md` — what qa-db checks and why DB-verify is the standard.
- `tools/` — compiler, verifier, fixture generator, helper source, drivers, gate.
- `spec/`, `profiles/` — spec format + example; calibration profiles.

## Repo hygiene (for contributors)

`tools/gate.sh` must pass before any commit: compiler golden match, qa-db
pass/fail fixture round-trip, scanner sweep. This repo never contains: Tobii
Dynavox software or assets, symbol images, real page sets, screenshots of
TD Snap, or any AAC user's personal content. Example content is invented.
