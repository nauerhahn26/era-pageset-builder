# edit-station.md — topology: which machine runs what, and why

The pattern that works: do all building on an **edit station**, a Windows PC
you control that is not the AAC user's device, and let TD Snap's own cloud
sync deliver the finished, verified result. The AAC user's device is never
automated and never at risk mid-build.

Check your TD Snap license terms for how many installs you are allowed; the
standard individual license permits installation on multiple devices for
the same AAC user. You need your own licensed TD Snap on the edit station,
signed into the same account as the AAC user's device.

## Setup

1. **Windows PC** with TD Snap for Windows installed and signed in.
2. **The helper** (`tools/qahelper/`): ~150 lines of C# you compile yourself
   with the csc already on every Windows machine (`build.md`). It reads
   command files and executes real input, then screenshots. It must run in
   the interactive desktop session; service-style sessions capture black
   screens.
3. **The agent** (the coding agent CLI) either:
   - **Locally on the edit station** (simplest): drives the helper through
     `tools/drive-local.ps1`; or
   - **Remotely** from another machine over SSH: `tools/drive-ssh.sh`
     (set your own host; requires an SSH server on the edit station).
4. **Quiet machine**: notifications off, no scheduled tasks, nothing else
   running. Anything that steals foreground focus mid-batch receives your
   clicks (method.md, edge case 10).

## Practice safety ladder

1. First sessions: a **locally imported copy** of a page set (no cloud
   badge). Local page sets never sync anywhere; you can do no harm beyond
   the copy. Calibrate and learn here.
2. Real builds: the cloud-synced page set, but only after a **cloud
   checkpoint** (save a copy to myTobiiDynavox), and with the checkpoint
   cadence from method.md. A cloud-synced page set edits propagate to every
   device on the account once synced, which is exactly what you want at the
   end and exactly what you don't mid-build; sync deliberately.

## Delivery

When the build is DB-verified clean (`qa.md`):

1. Checkpoint once more.
2. On the edit station: tap Sync Page Set (pushes).
3. On the AAC user's device, at a good moment for the user: tap Sync Page
   Set (pulls). Sync happens ONLY on this manual tap; nothing propagates on
   launch or on a timer.
4. Confirm on-device that the new pages are present and the home page and
   message bar are as the user expects. If the user relies on a modeling or
   tracking mode, re-check it after any app restart; such modes can be
   runtime-only state.

## What this toolkit deliberately does not do

- It does not automate the AAC user's own device.
- It does not write page content to the database (editor-only writes;
  page sets are signed by the editor and the toolkit does not attempt to
  forge signatures).
- It does not accept TD Snap update dialogs (the owner updates on their own
  schedule, after checking their device still works as expected).
- It has no drag command, so it cannot rearrange learned button positions;
  position-preserving rearrangement is intentionally left to human hands.
