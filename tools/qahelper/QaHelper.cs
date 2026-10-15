// QaHelper.cs — file-drop UI automation helper for Windows.
//
// A single-file C# program (no project, no NuGet) that watches a command file,
// injects real mouse/keyboard input via SendInput, then captures a full-screen
// screenshot and bumps a sequence counter so a driver script knows the batch
// is done.
//
// Build (any Windows box with .NET Framework 4.x, which is preinstalled):
//   %WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:winexe QaHelper.cs
//
// Protocol (all files live in C:\Users\Public\Documents\qa\):
//   qa_cmd.txt   — dropped by a driver; one command per line (see below).
//                  QaHelper reads it, DELETES it, executes the commands in
//                  order, then writes qa_shot.png and increments qa_seq.txt.
//   qa_shot.png  — full-screen PNG captured after the batch finishes.
//   qa_seq.txt   — integer, incremented once per completed batch (created if
//                  missing). Drivers wait on this to know the batch is done.
//   qa_err.txt   — append-only log of unknown commands and runtime errors.
//
// Command language (coordinates are ORIGINAL physical screen pixels):
//   MOVE x y        move cursor to (x, y)
//   CLICK x y       move + left click
//   DBL x y         move + left double-click
//   RCLICK x y      move + right click
//   KEY name        named key or combo: Enter, Tab, Esc, Backspace, Delete,
//                   Home, End, Up/Down/Left/Right, F1..F12, and combos like
//                   Ctrl+A, Ctrl+Shift+S, Alt+F4
//   TYPE text       literal text typed via SendInput unicode events.
//                   NOTE: backslashes and some special characters have proven
//                   unreliable in some target apps — prefer avoiding them
//                   (use KEY for Tab/Enter, and avoid paths in typed text).
//   SCROLL n        mouse wheel at the CURRENT cursor position; positive = up,
//                   negative = down; n is in wheel notches (120 units each)
//   SLEEP ms        pause for the given number of milliseconds
//
// Unknown commands are logged to qa_err.txt and skipped; the batch continues.
//
// Reliability notes:
//   * Input is real hardware-level injection (SendInput), not PostMessage, so
//     it works against apps that ignore synthetic window messages.
//   * A ~40 ms settle delay follows every input command so slow message pumps
//     can keep up.
//   * Even so, batches longer than ~38 commands have been observed to be
//     dropped SILENTLY by slow editors' message pumps. Drivers MUST chunk
//     batches to 38 commands or fewer (both bundled drivers enforce this).
//   * Screen capture uses Graphics.CopyFromScreen, which only works in an
//     INTERACTIVE desktop session. Run QaHelper as the logged-on user, never
//     as a service (black screenshots) and not in a minimized/disconnected
//     remote-desktop session. See tools/qahelper/build.md.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

internal static class QaHelper
{
    // ------------------------------------------------------------------ paths

    private const string QaDir   = @"C:\Users\Public\Documents\qa";
    private const string CmdPath = QaDir + @"\qa_cmd.txt";
    private const string ShotPath = QaDir + @"\qa_shot.png";
    private const string ShotTmpPath = QaDir + @"\qa_shot.tmp";
    private const string SeqPath = QaDir + @"\qa_seq.txt";
    private const string ErrPath = QaDir + @"\qa_err.txt";

    private const int PollMs = 250;    // command-file poll interval
    private const int SettleMs = 40;   // settle delay after each input command

    // -------------------------------------------------------------- P/Invoke

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int nIndex);

    [DllImport("user32.dll")]
    private static extern uint MapVirtualKey(uint uCode, uint uMapType);

    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    private const int SM_XVIRTUALSCREEN = 76;
    private const int SM_YVIRTUALSCREEN = 77;
    private const int SM_CXVIRTUALSCREEN = 78;
    private const int SM_CYVIRTUALSCREEN = 79;

    private const uint INPUT_MOUSE = 0;
    private const uint INPUT_KEYBOARD = 1;

    private const uint MOUSEEVENTF_MOVE        = 0x0001;
    private const uint MOUSEEVENTF_LEFTDOWN    = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP      = 0x0004;
    private const uint MOUSEEVENTF_RIGHTDOWN   = 0x0008;
    private const uint MOUSEEVENTF_RIGHTUP     = 0x0010;
    private const uint MOUSEEVENTF_WHEEL       = 0x0800;
    private const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;
    private const uint MOUSEEVENTF_ABSOLUTE    = 0x8000;

    private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
    private const uint KEYEVENTF_KEYUP       = 0x0002;
    private const uint KEYEVENTF_UNICODE     = 0x0004;

    private const int WHEEL_DELTA = 120;

    // INPUT and its union. On x64 the native INPUT is 40 bytes (4-byte type,
    // 4 bytes padding, 32-byte MOUSEINPUT); Marshal.SizeOf reproduces that
    // because dwExtraInfo is IntPtr and the union uses explicit layout.
    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT
    {
        public uint type;
        public InputUnion U;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct InputUnion
    {
        [FieldOffset(0)] public MOUSEINPUT mi;
        [FieldOffset(0)] public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    // ------------------------------------------------------------ key tables

    private static readonly Dictionary<string, ushort> NamedKeys =
        new Dictionary<string, ushort>(StringComparer.OrdinalIgnoreCase)
    {
        { "enter", 0x0D }, { "return", 0x0D },
        { "tab", 0x09 },
        { "esc", 0x1B }, { "escape", 0x1B },
        { "backspace", 0x08 }, { "back", 0x08 },
        { "delete", 0x2E }, { "del", 0x2E },
        { "insert", 0x2D }, { "ins", 0x2D },
        { "home", 0x24 }, { "end", 0x23 },
        { "pageup", 0x21 }, { "pgup", 0x21 },
        { "pagedown", 0x22 }, { "pgdn", 0x22 },
        { "up", 0x26 }, { "down", 0x28 }, { "left", 0x25 }, { "right", 0x27 },
        { "space", 0x20 },
        { "f1", 0x70 }, { "f2", 0x71 }, { "f3", 0x72 }, { "f4", 0x73 },
        { "f5", 0x74 }, { "f6", 0x75 }, { "f7", 0x76 }, { "f8", 0x77 },
        { "f9", 0x78 }, { "f10", 0x79 }, { "f11", 0x7A }, { "f12", 0x7B },
        { "win", 0x5B },
        { "apps", 0x5D }, { "menu", 0x5D },
    };

    private static readonly Dictionary<string, ushort> Modifiers =
        new Dictionary<string, ushort>(StringComparer.OrdinalIgnoreCase)
    {
        { "ctrl", 0x11 }, { "control", 0x11 },
        { "shift", 0x10 },
        { "alt", 0x12 },
        { "win", 0x5B },
    };

    // Keys the hardware reports as "extended"; some apps care about the flag.
    private static readonly HashSet<ushort> ExtendedKeys = new HashSet<ushort>
    {
        0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, // Del Ins Home End PgUp PgDn
        0x26, 0x28, 0x25, 0x27,             // arrows
    };

    // ------------------------------------------------------------------ main

    [STAThread]
    private static void Main()
    {
        // Single instance only — a second copy would race on the files.
        bool createdNew;
        using (new Mutex(true, "QaHelperSingleInstance", out createdNew))
        {
            if (!createdNew) return;

            // See physical pixels: without this, a scaled desktop would make
            // both CopyFromScreen and our coordinates operate on virtualized
            // (DPI-scaled) pixels instead of the ORIGINAL screen pixels the
            // command language promises.
            try { SetProcessDPIAware(); } catch { }

            Directory.CreateDirectory(QaDir);

            while (true)
            {
                Thread.Sleep(PollMs);
                try
                {
                    RunOneBatchIfPresent();
                }
                catch (Exception ex)
                {
                    LogError("batch failed: " + ex.Message);
                }
            }
        }
    }

    private static void RunOneBatchIfPresent()
    {
        if (!File.Exists(CmdPath)) return;

        // Open exclusively so a half-written file (driver still copying) is
        // skipped this cycle and picked up on the next poll.
        string[] lines;
        try
        {
            using (var fs = new FileStream(CmdPath, FileMode.Open,
                                           FileAccess.Read, FileShare.None))
            using (var sr = new StreamReader(fs))
            {
                var all = new List<string>();
                string line;
                while ((line = sr.ReadLine()) != null) all.Add(line);
                lines = all.ToArray();
            }
            File.Delete(CmdPath);
        }
        catch (IOException)
        {
            return; // writer still holds the file; retry on next poll
        }

        foreach (string raw in lines)
        {
            string line = raw.TrimEnd('\r').Trim();
            if (line.Length == 0) continue;
            Execute(line);
        }

        CaptureScreen();
        IncrementSeq();
    }

    // ------------------------------------------------------------- dispatch

    private static void Execute(string line)
    {
        int sp = line.IndexOf(' ');
        string cmd = (sp < 0 ? line : line.Substring(0, sp)).ToUpperInvariant();
        string rest = sp < 0 ? "" : line.Substring(sp + 1);

        try
        {
            switch (cmd)
            {
                case "MOVE":   { int x, y; ParseXY(rest, out x, out y); MouseMove(x, y); Settle(); break; }
                case "CLICK":  { int x, y; ParseXY(rest, out x, out y); MouseMove(x, y); MouseButton(true);  Settle(); break; }
                case "DBL":    { int x, y; ParseXY(rest, out x, out y); MouseMove(x, y); MouseButton(true); Thread.Sleep(60); MouseButton(true); Settle(); break; }
                case "RCLICK": { int x, y; ParseXY(rest, out x, out y); MouseMove(x, y); MouseButton(false); Settle(); break; }
                case "KEY":    SendKeyCombo(rest.Trim()); Settle(); break;
                case "TYPE":   SendText(rest); Settle(); break;
                case "SCROLL": Scroll(int.Parse(rest.Trim())); Settle(); break;
                case "SLEEP":  Thread.Sleep(Math.Max(0, int.Parse(rest.Trim()))); break;
                default:
                    LogError("unknown command: " + line);
                    break;
            }
        }
        catch (Exception ex)
        {
            LogError("command '" + line + "' failed: " + ex.Message);
        }
    }

    private static void ParseXY(string args, out int x, out int y)
    {
        string[] parts = args.Split(new[] { ' ', '\t' },
                                    StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 2) throw new ArgumentException("expected: x y");
        x = int.Parse(parts[0]);
        y = int.Parse(parts[1]);
    }

    private static void Settle() { Thread.Sleep(SettleMs); }

    // ---------------------------------------------------------------- mouse

    // Absolute move: normalize physical pixels to the 0..65535 space of the
    // whole VIRTUAL screen (all monitors), per the SendInput contract.
    private static void MouseMove(int x, int y)
    {
        int vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
        int vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
        int vw = GetSystemMetrics(SM_CXVIRTUALSCREEN);
        int vh = GetSystemMetrics(SM_CYVIRTUALSCREEN);
        if (vw <= 1 || vh <= 1) throw new InvalidOperationException("no screen metrics");

        int nx = (int)Math.Round((x - vx) * 65535.0 / (vw - 1));
        int ny = (int)Math.Round((y - vy) * 65535.0 / (vh - 1));

        var inp = new INPUT { type = INPUT_MOUSE };
        inp.U.mi.dx = nx;
        inp.U.mi.dy = ny;
        inp.U.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                         | MOUSEEVENTF_VIRTUALDESK;
        Send(new[] { inp });
    }

    private static void MouseButton(bool left)
    {
        var down = new INPUT { type = INPUT_MOUSE };
        down.U.mi.dwFlags = left ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_RIGHTDOWN;
        var up = new INPUT { type = INPUT_MOUSE };
        up.U.mi.dwFlags = left ? MOUSEEVENTF_LEFTUP : MOUSEEVENTF_RIGHTUP;
        Send(new[] { down, up });
    }

    private static void Scroll(int notches)
    {
        var inp = new INPUT { type = INPUT_MOUSE };
        inp.U.mi.mouseData = unchecked((uint)(notches * WHEEL_DELTA));
        inp.U.mi.dwFlags = MOUSEEVENTF_WHEEL; // at current cursor position
        Send(new[] { inp });
    }

    // ------------------------------------------------------------- keyboard

    private static void SendKeyCombo(string name)
    {
        if (name.Length == 0) throw new ArgumentException("KEY needs a name");

        // "Ctrl+Shift+S" → modifiers [Ctrl, Shift], key S
        string[] parts = name.Split('+');
        var mods = new List<ushort>();
        for (int i = 0; i < parts.Length - 1; i++)
        {
            ushort mvk;
            if (!Modifiers.TryGetValue(parts[i].Trim(), out mvk))
                throw new ArgumentException("unknown modifier: " + parts[i]);
            mods.Add(mvk);
        }
        ushort vk = ResolveKey(parts[parts.Length - 1].Trim());

        var seq = new List<INPUT>();
        foreach (ushort m in mods) seq.Add(KeyEvent(m, false));
        seq.Add(KeyEvent(vk, false));
        seq.Add(KeyEvent(vk, true));
        for (int i = mods.Count - 1; i >= 0; i--) seq.Add(KeyEvent(mods[i], true));
        Send(seq.ToArray());
    }

    private static ushort ResolveKey(string name)
    {
        ushort vk;
        if (NamedKeys.TryGetValue(name, out vk)) return vk;
        if (name.Length == 1)
        {
            char c = char.ToUpperInvariant(name[0]);
            if (c >= 'A' && c <= 'Z') return (ushort)c;   // VK_A..VK_Z = 'A'..'Z'
            if (c >= '0' && c <= '9') return (ushort)c;   // VK_0..VK_9 = '0'..'9'
        }
        throw new ArgumentException("unknown key: " + name);
    }

    private static INPUT KeyEvent(ushort vk, bool up)
    {
        var inp = new INPUT { type = INPUT_KEYBOARD };
        inp.U.ki.wVk = vk;
        inp.U.ki.wScan = (ushort)MapVirtualKey(vk, 0); // MAPVK_VK_TO_VSC
        inp.U.ki.dwFlags = (up ? KEYEVENTF_KEYUP : 0u)
                         | (ExtendedKeys.Contains(vk) ? KEYEVENTF_EXTENDEDKEY : 0u);
        return inp;
    }

    // TYPE — literal text as KEYEVENTF_UNICODE down/up pairs. Surrogate pairs
    // are sent as two events each, which SendInput handles. Backslashes and
    // some special characters are unreliable in some target apps; batches
    // should avoid them where possible.
    private static void SendText(string text)
    {
        if (text.Length == 0) return;
        var seq = new List<INPUT>(text.Length * 2);
        foreach (char c in text)
        {
            var down = new INPUT { type = INPUT_KEYBOARD };
            down.U.ki.wScan = c;
            down.U.ki.dwFlags = KEYEVENTF_UNICODE;
            var up = new INPUT { type = INPUT_KEYBOARD };
            up.U.ki.wScan = c;
            up.U.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            seq.Add(down);
            seq.Add(up);
        }
        Send(seq.ToArray());
    }

    private static void Send(INPUT[] inputs)
    {
        uint sent = SendInput((uint)inputs.Length, inputs,
                              Marshal.SizeOf(typeof(INPUT)));
        if (sent != inputs.Length)
            throw new InvalidOperationException(
                "SendInput injected " + sent + "/" + inputs.Length +
                " events (Win32 error " + Marshal.GetLastWin32Error() + ")");
    }

    // ----------------------------------------------------- capture and seq

    // Full VIRTUAL screen capture. CopyFromScreen requires an interactive
    // desktop session; from a service or a disconnected session it produces
    // a black image or throws.
    private static void CaptureScreen()
    {
        try
        {
            int vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
            int vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
            int vw = GetSystemMetrics(SM_CXVIRTUALSCREEN);
            int vh = GetSystemMetrics(SM_CYVIRTUALSCREEN);

            using (var bmp = new Bitmap(vw, vh, PixelFormat.Format32bppArgb))
            {
                using (var g = Graphics.FromImage(bmp))
                {
                    g.CopyFromScreen(vx, vy, 0, 0, new Size(vw, vh));
                }
                bmp.Save(ShotTmpPath, ImageFormat.Png);
            }
            if (File.Exists(ShotPath)) File.Delete(ShotPath);
            File.Move(ShotTmpPath, ShotPath);
        }
        catch (Exception ex)
        {
            LogError("screenshot failed: " + ex.Message);
        }
    }

    private static void IncrementSeq()
    {
        int seq = 0;
        try
        {
            if (File.Exists(SeqPath))
                int.TryParse(File.ReadAllText(SeqPath).Trim(), out seq);
        }
        catch (IOException) { }
        File.WriteAllText(SeqPath, (seq + 1).ToString());
    }

    // ------------------------------------------------------------- err log

    private static void LogError(string message)
    {
        try
        {
            File.AppendAllText(ErrPath,
                DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + message
                + Environment.NewLine, Encoding.UTF8);
        }
        catch (IOException) { }
    }
}
