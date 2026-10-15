# calibration.md — discovering the editor's coordinates on THIS machine

The compiler contains no coordinates. Every click position comes from a
profile in `profiles/`, and profiles are per-machine: they change with
screen resolution, display scaling, TD Snap version, and which optional
toolbar buttons are enabled. `profiles/example-2736x1824.json` is a complete
worked example from our edit station; your job is to produce the same set of
keys for the machine in front of you.

Recalibrate whenever resolution, display scaling, or the TD Snap version
changes, and spot-check the normalizer click at the start of every session.

## The two coordinate spaces (get this right first)

The helper captures screenshots at the display's ORIGINAL resolution, but
you may be viewing them scaled down. All profile coordinates are ORIGINAL
space. Determine your scale factor once: original width ÷ displayed width
(e.g. 2736 ÷ 2000 = 1.37), and multiply every coordinate you measure off a
displayed screenshot by it. Record both resolutions and the factor in the
profile's `meta` block. Getting this wrong makes every click land short of
its target toward the top-left; if your very first verified click misses in
that pattern, recheck the factor before anything else.

## Method: locate, then verify with a discriminator

For each profile key, in TD Snap's editor on a THROWAWAY locally imported
page set (never a synced one):

1. **Screenshot** the relevant editor state.
2. **Locate** the control visually and compute original-space coordinates.
3. **Verify with a discriminating click**: click it once, screenshot again,
   and check for the control's UNAMBIGUOUS effect (a drawer opened, a badge
   appeared, a field focused with cursor). A click that "seems fine" is not
   verified; a click whose effect you can name and see is. If the effect is
   wrong or absent, you probably hit a neighbor: fix the coordinate, do not
   retry blindly.
4. **Record** the key with a one-line note of its discriminator, so the next
   calibration can re-verify quickly.

Slow feedback reads as failure: some editor drawers take a beat to rise.
Wait, screenshot, then judge. Never conclude from one fast screenshot that
a click did nothing.

## What to calibrate (the profile keys)

Work through `profiles/example-2736x1824.json` key by key; it documents each
one. The load-bearing groups:

- **Mode controls**: enter edit mode, Done. Verify edit mode by its banner
  and tab row (see method.md on fake edit mode), not by assuming.
- **Panel state**: the tab row positions in BOTH panel-open and
  panel-collapsed states, and the normalizer click that lands harmlessly in
  either state. This pair is the #1 failure source; calibrate it carefully.
- **Grid cells**: the column x-centers and row y-centers for each grid size
  your specs use, measured with the panel collapsed.
- **Button panel controls**: Content / Style / Link to Page entries, label
  field, size and layout rows, the Match toggle inside pickers, the list
  scrollbar TRACK (wheel scrolling moves these lists uselessly slowly;
  clicking the track pages properly).
- **Dialogs**: the update-dialog Cancel position (screenshot-first, then
  click; see method.md), search-dialog field and clear-X.
- **Multi-select**: the multi-select icon and where its count badge appears
  (the badge is how you verify selections).

## Profile hygiene

Name profiles by resolution and context (`example-2736x1824.json`,
`myedit-1920x1080.json`). Keep your machine's profile out of version control
if it embeds anything personal; geometry itself is generic. Never copy a
profile between machines without re-running the discriminator pass.
