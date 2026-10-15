# QaHelper — build and install

QaHelper is a single-file C# helper that turns a Windows PC into a scriptable
UI-automation target: drop a command file, get real mouse/keyboard input plus a
screenshot back. See the header comment in `QaHelper.cs` for the full command
language and file protocol.

## Build

No IDE, no SDK download. Every Windows 10/11 install ships the .NET Framework
4.x C# compiler at a fixed path pattern:

```
%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
```

From a `cmd` prompt in the folder containing `QaHelper.cs`:

```
%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:winexe QaHelper.cs
```

That produces `QaHelper.exe` next to the source file. `/target:winexe` means
no console window — the helper runs invisibly in the background.

Notes:

- The default compiler response file (`csc.rsp`, same folder as `csc.exe`)
  already references `System.dll`, `System.Drawing.dll`, and
  `System.Windows.Forms.dll`, so no `/r:` flags are needed. If a locked-down
  machine has a stripped `csc.rsp`, add them explicitly:
  `/r:System.dll /r:System.Drawing.dll`.
- On a 32-bit-only install use `Framework` instead of `Framework64` in the
  path.

## Files and locations

All protocol files live in a world-writable folder so any local account (or a
remote driver copying files in) can reach them:

| File | Purpose |
| --- | --- |
| `C:\Users\Public\Documents\qa\qa_cmd.txt` | command batch, dropped by a driver; deleted after it is read |
| `C:\Users\Public\Documents\qa\qa_shot.png` | full-screen PNG written after each batch |
| `C:\Users\Public\Documents\qa\qa_seq.txt` | integer counter, +1 per completed batch |
| `C:\Users\Public\Documents\qa\qa_err.txt` | unknown commands and runtime errors |

`QaHelper.exe` itself can live anywhere; a sensible spot is
`C:\Users\Public\Documents\qa\QaHelper.exe`.

## Run it — INTERACTIVE session required

This is the one hard rule: **QaHelper must run inside the interactive,
logged-on user session.**

- As a Windows **service** (or via `schtasks` without `/it`), screen capture
  runs against a non-interactive desktop and `qa_shot.png` comes out **black**.
- The same happens in a **minimized or disconnected remote-desktop session** —
  there is no live desktop to capture. Keep the console session active, or
  keep the RDP window open and unminimized while batches run.

### Option A — just double-click it

After logging on, double-click `QaHelper.exe`. It has no window; confirm it is
running in Task Manager. This is the simplest and most reliable way.

### Option B — start automatically at logon

Create a logon task that runs it in the interactive session (`/it`):

```
schtasks /create /tn qahelper /tr C:\Users\Public\Documents\qa\QaHelper.exe /sc onlogon /ru <user> /it
```

Replace `<user>` with the account that logs on to the machine. The `/it` flag
is what makes the task interactive; without it you get the black-screenshot
failure mode above.

To remove the task later:

```
schtasks /delete /tn qahelper /f
```

## Stop it

```
taskkill /IM QaHelper.exe
```

(Add `/F` if it does not exit promptly.) QaHelper also refuses to start a
second copy of itself, so restarting is always: taskkill, then launch again.

## Driver reminder

Batches longer than **38 commands** have been observed to be dropped silently
by slow editors' message pumps. The bundled drivers (`tools/drive-local.ps1`,
`tools/drive-ssh.sh`) refuse longer batches; if you write your own driver,
chunk to 38 or fewer.
