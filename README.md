# era-pageset-builder

An agent-run toolkit that builds AAC page sets in **TD Snap for Windows** by
driving TD Snap's own editor, then verifies every button structurally in the
page set database. Built by a family that used it to rebuild a 60+ page
eye-gaze communication board, and published so other families, SLPs, and
teachers can do the same with an AI agent doing the repetitive work.

**Unofficial.** This project is not affiliated with, endorsed by, or supported
by Tobii Dynavox. TD Snap is a product of Tobii Dynavox; you need your own
licensed copy. This repo contains no Tobii Dynavox software, no symbol
libraries, and no page set content — only our own tools and hard-won method
notes.

## What it does

- You (with your coding agent) write a **board spec**: pages,
  buttons, labels, links, layouts, silent navigation buttons, rest cells.
- The **compiler** turns each page into batches of real mouse/keyboard
  commands. A tiny open-source **helper** (C#, ~one file, you build it
  yourself) executes them in TD Snap's editor exactly as a human would:
  click cell, type label, set the grid, link pages, apply styles.
- TD Snap itself does everything meaningful: it fills in the message, picks
  the symbol from your licensed library, creates the pages, signs the result.
  The toolkit never edits page content in the database.
- The **verifier** then opens a *copy* of the page set database read-only and
  checks every label, position, link, font, layout, and silence against your
  spec. If anything mismatches, the build fails. Screenshots lie; the
  database doesn't.

## Why this exists

Building a well-designed board for an eye-gaze user means hundreds of
repetitive editor operations per page, times dozens of pages, with zero
tolerance for a wrong link or a button that speaks when it should be silent.
That is exactly the work an agent is good at and a tired parent is not. Our
full build ran ~65 pages with a final structural sweep of zero defects.

## Quick start

1. Read `docs/edit-station.md` — you'll set up a Windows PC with your own
   TD Snap install as the "edit station" (practice on a locally imported
   copy of a page set first, never directly on a synced one).
2. Point your agent at this repo. `AGENTS.md` orients it: laws, workflow,
   calibration, build, QA.
3. The agent calibrates coordinates for your machine (`docs/calibration.md`),
   helps you write the spec, builds, verifies, and tells you when to tap
   Sync.

## Safety posture

- Writes happen only through TD Snap's editor. Page sets are signed by the
  editor; this toolkit writes only through the editor and does not attempt to
  forge signatures.
- The database is only ever opened read-only, on a copy, for verification.
- Cloud-checkpoint before editing, checkpoint often, restore instead of undo.
- The toolkit never accepts update dialogs and never deletes buttons carrying
  system actions.

## License

MPL-2.0 for everything in this repo. TD Snap, its symbol libraries, and all
Tobii Dynavox trademarks and content remain the property of their respective
owners; nothing here grants you any rights to them.
