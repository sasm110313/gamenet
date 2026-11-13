import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import readline from "node:readline";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { log } from "./logger";

export type KioskGuardMode = "DISABLED" | "LOCK" | "GAME";

export interface Win32AppWindow {
  hwnd: string;
  pid: number;
  isForeground: boolean;
  isMinimized: boolean;
  processName: string;
  title: string;
}

const KIOSK_GUARD_PS = `
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Runtime.InteropServices;
using Microsoft.Win32;

public class GnKioskGuard {
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumeratorComObject {
    }

    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator {
        [PreserveSig]
        int EnumAudioEndpoints(int dataFlow, int dwStateMask, out IntPtr ppDevices);
        [PreserveSig]
        int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppEndpoint);
    }

    [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice {
        [PreserveSig]
        int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
    }

    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioEndpointVolume {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr pNotify);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr pNotify);
        [PreserveSig] int GetChannelCount(out uint pnChannelCount);
        [PreserveSig] int SetMasterVolumeLevel(float fLevelDB, ref Guid pguidEventContext);
        [PreserveSig] int SetMasterVolumeLevelScalar(float fLevel, ref Guid pguidEventContext);
        [PreserveSig] int GetMasterVolumeLevel(out float pfLevelDB);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float pfLevel);
        [PreserveSig] int SetChannelVolumeLevel(uint nChannel, float fLevelDB, ref Guid pguidEventContext);
        [PreserveSig] int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, ref Guid pguidEventContext);
        [PreserveSig] int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
        [PreserveSig] int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, ref Guid pguidEventContext);
        [PreserveSig] int GetMute(out bool pbMute);
    }

    private const int WH_KEYBOARD_LL = 13;
    private const int WM_QUIT = 0x0012;
    private const int WM_KEYDOWN = 0x0100;
    private const int WM_KEYUP = 0x0101;
    private const int WM_SYSKEYDOWN = 0x0104;
    private const int WM_SYSKEYUP = 0x0105;

    private const uint LLKHF_ALTDOWN = 0x20;
    private static readonly UIntPtr RDP_TAG = new UIntPtr(0x474E5244u);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int x;
        public int y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MSG {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public POINT pt;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KBDLLHOOKSTRUCT {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll")]
    private static extern int GetMessage(out MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref MSG lpMsg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessage(ref MSG lpMsg);

    [DllImport("user32.dll")]
    private static extern bool PostThreadMessage(uint idThread, uint Msg, UIntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr FindWindowEx(IntPtr parentHandle, IntPtr childAfter, string className, string windowTitle);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    [DllImport("user32.dll")]
    private static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SystemParametersInfo(uint uiAction, uint uiParam, IntPtr pvParam, uint fWinIni);

    [DllImport("user32.dll", EntryPoint = "SystemParametersInfo", SetLastError = true)]
    private static extern bool SystemParametersInfoGet(uint uiAction, uint uiParam, out int pvParam, uint fWinIni);

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern IntPtr GetModuleHandle(string lpModuleName);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    // 0 = DISABLED, 1 = LOCK (kiosk locked), 2 = GAME (kiosk active during user session)
    private static volatile int _mode = 0;
    private static volatile bool _quitting = false;
    private static volatile bool _ctrlPressed = false;
    private static volatile bool _shiftPressed = false;
    private static volatile bool _altPressed = false;
    private static IntPtr _hookId = IntPtr.Zero;
    private static uint _mainThreadId = 0;
    private static readonly LowLevelKeyboardProc _proc = HookCallback;

    private static bool IsKeyDown(int vk) {
        return (GetAsyncKeyState(vk) & 0x8000) != 0;
    }

    private static IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam) {
        if (nCode >= 0 && _mode != 0) {
            int msg = wParam.ToInt32();
            bool isKeyEvent = (msg == WM_KEYDOWN || msg == WM_KEYUP || msg == WM_SYSKEYDOWN || msg == WM_SYSKEYUP);
            if (isKeyEvent) {
                KBDLLHOOKSTRUCT info = (KBDLLHOOKSTRUCT)Marshal.PtrToStructure(lParam, typeof(KBDLLHOOKSTRUCT));
                if (info.dwExtraInfo.ToUInt64() == RDP_TAG.ToUInt64()) {
                    return CallNextHookEx(_hookId, nCode, wParam, lParam);
                }

                uint vk = info.vkCode;
                bool isDown = (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN);
                bool isUp = (msg == WM_KEYUP || msg == WM_SYSKEYUP);

                if (vk == 0x11 || vk == 0xA2 || vk == 0xA3) {
                    _ctrlPressed = isDown;
                }
                if (vk == 0x10 || vk == 0xA0 || vk == 0xA1) {
                    _shiftPressed = isDown;
                }
                if (vk == 0x12 || vk == 0xA4 || vk == 0xA5) {
                    _altPressed = isDown;
                }

                bool altDown = (info.flags & LLKHF_ALTDOWN) != 0 || IsKeyDown(0x12) || IsKeyDown(0xA4) || IsKeyDown(0xA5) || _altPressed;
                bool ctrlDown = IsKeyDown(0x11) || IsKeyDown(0xA2) || IsKeyDown(0xA3) || _ctrlPressed;
                bool shiftDown = IsKeyDown(0x10) || IsKeyDown(0xA0) || IsKeyDown(0xA1) || _shiftPressed;

                // Block Left Win (0x5B), Right Win (0x5C), Context Menu / Apps key (0x5D)
                if (vk == 0x5B || vk == 0x5C || vk == 0x5D) {
                    return (IntPtr)1;
                }

                // Alt+F5 (vk == 0x74 && altDown): Fast logout / lock screen keeping games alive
                if (vk == 0x74 && altDown) {
                    if (isDown) {
                        Console.Out.WriteLine("EVENT|ALTF5");
                        Console.Out.Flush();
                    }
                    return (IntPtr)1;
                }

                // Alt+Tab (vk == 0x09 && altDown)
                if (vk == 0x09 && altDown) {
                    if (_mode == 1) {
                        return (IntPtr)1;
                    } else if (_mode == 2) {
                        if (isDown) {
                            SwitchToNextWindow();
                            Console.Out.WriteLine("EVENT|ALTTAB");
                            Console.Out.Flush();
                        }
                        return (IntPtr)1;
                    }
                }

                // Block Ctrl+Shift+Esc (Task Manager), Ctrl+Esc (Start Menu), Alt+Esc (Window Switch)
                if (vk == 0x1B && (ctrlDown || altDown || shiftDown)) {
                    return (IntPtr)1;
                }

                // Block Alt+Space (System Window Menu)
                if (vk == 0x20 && altDown) {
                    return (IntPtr)1;
                }

                // Block Alt+F4 system-wide while screen is locked (in GAME mode Electron blocks closing GameNet itself)
                if (vk == 0x73 && altDown && _mode == 1) {
                    return (IntPtr)1;
                }
            }
        }
        return CallNextHookEx(_hookId, nCode, wParam, lParam);
    }

    private static bool IsApplicationWindow(IntPtr hWnd) {
        try {
            if (!IsWindowVisible(hWnd)) return false;
            int len = GetWindowTextLength(hWnd);
            if (len <= 0) return false;
            if (GetWindow(hWnd, 4 /* GW_OWNER */) != IntPtr.Zero) return false;
            int exStyle = GetWindowLong(hWnd, -20 /* GWL_EXSTYLE */);
            if ((exStyle & 0x00000080 /* WS_EX_TOOLWINDOW */) != 0) return false;
            StringBuilder sb = new StringBuilder(256);
            GetWindowText(hWnd, sb, sb.Capacity);
            string title = sb.ToString().Trim();
            if (string.IsNullOrEmpty(title)) return false;
            if (title == "Program Manager" || title == "Windows Task Manager" || title == "Windows Security") return false;
            return true;
        } catch {
            return false;
        }
    }

    public static void ListWindows() {
        try {
            System.Collections.Generic.List<string> list = new System.Collections.Generic.List<string>();
            IntPtr fg = GetForegroundWindow();
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                try {
                    if (IsApplicationWindow(hWnd)) {
                        StringBuilder sb = new StringBuilder(256);
                        GetWindowText(hWnd, sb, sb.Capacity);
                        string title = sb.ToString().Trim();
                        uint pid = 0;
                        GetWindowThreadProcessId(hWnd, out pid);
                        string pName = "";
                        try {
                            Process p = Process.GetProcessById((int)pid);
                            pName = p.ProcessName;
                        } catch {}
                        bool isFg = (hWnd == fg);
                        bool isMin = IsIconic(hWnd);
                        string row = hWnd.ToInt64().ToString() + "\t" + pid.ToString() + "\t" + (isFg ? "1" : "0") + "\t" + (isMin ? "1" : "0") + "\t" + pName.Replace("\t", " ") + "\t" + title.Replace("\t", " ");
                        list.Add(row);
                    }
                } catch {}
                return true;
            }, IntPtr.Zero);

            Console.Out.WriteLine("WINDOWS_START");
            foreach (string row in list) {
                Console.Out.WriteLine("WINDOW|" + row);
            }
            Console.Out.WriteLine("WINDOWS_END");
            Console.Out.Flush();
        } catch {}
    }

    public static void FocusWindow(IntPtr hWnd) {
        try {
            if (IsIconic(hWnd)) {
                ShowWindowAsync(hWnd, 9 /* SW_RESTORE */);
            } else {
                ShowWindowAsync(hWnd, 5 /* SW_SHOW */);
            }
            SetForegroundWindow(hWnd);
        } catch {}
    }

    public static void MinimizeWindow(IntPtr hWnd) {
        try {
            ShowWindowAsync(hWnd, 6 /* SW_MINIMIZE */);
        } catch {}
    }

    public static void CloseWindow(IntPtr hWnd, int pid) {
        try {
            PostMessage(hWnd, 0x0010 /* WM_CLOSE */, IntPtr.Zero, IntPtr.Zero);
        } catch {}
    }

    public static void KillAllApps(int currentPid) {
        try {
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                try {
                    if (IsApplicationWindow(hWnd)) {
                        uint pid = 0;
                        GetWindowThreadProcessId(hWnd, out pid);
                        if (pid != 0 && pid != (uint)currentPid) {
                            try {
                                Process p = Process.GetProcessById((int)pid);
                                string pName = p.ProcessName.ToLowerInvariant();
                                if (pName != "explorer" && pName != "gamenet" && pName != "electron" &&
                                    !pName.StartsWith("csrss") && !pName.StartsWith("dwm") &&
                                    !pName.StartsWith("lsass") && !pName.StartsWith("services") &&
                                    !pName.StartsWith("smss") && !pName.StartsWith("svchost") &&
                                    !pName.StartsWith("winlogon") && !pName.StartsWith("taskhost")) {
                                    p.Kill();
                                }
                            } catch {}
                        }
                    }
                } catch {}
                return true;
            }, IntPtr.Zero);
        } catch {}
    }

    public static void SwitchToNextWindow() {
        try {
            System.Collections.Generic.List<IntPtr> wins = new System.Collections.Generic.List<IntPtr>();
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                if (IsApplicationWindow(hWnd)) {
                    wins.Add(hWnd);
                }
                return true;
            }, IntPtr.Zero);

            if (wins.Count == 0) return;
            if (wins.Count == 1) {
                FocusWindow(wins[0]);
                return;
            }
            IntPtr fg = GetForegroundWindow();
            int idx = wins.IndexOf(fg);
            int nextIdx = (idx + 1) % wins.Count;
            IntPtr nextHwnd = wins[nextIdx];
            FocusWindow(nextHwnd);
        } catch {}
    }

    private static IAudioEndpointVolume GetEndpointVolume(int role) {
        IMMDeviceEnumerator enumerator = null;
        IMMDevice dev = null;
        try {
            enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
            int hr = enumerator.GetDefaultAudioEndpoint(0, role, out dev);
            if (hr != 0 || dev == null) {
                return null;
            }
            Guid iid = typeof(IAudioEndpointVolume).GUID;
            object activated = null;
            int hrAct = dev.Activate(ref iid, 23, IntPtr.Zero, out activated);
            if (hrAct != 0 || activated == null) {
                return null;
            }
            return activated as IAudioEndpointVolume;
        } catch {
            return null;
        } finally {
            if (dev != null) { try { Marshal.ReleaseComObject(dev); } catch {} }
            if (enumerator != null) { try { Marshal.ReleaseComObject(enumerator); } catch {} }
        }
    }

    public static int GetMasterVolume(int fallback) {
        for (int role = 0; role <= 1; role++) {
            IAudioEndpointVolume epv = GetEndpointVolume(role);
            if (epv != null) {
                try {
                    bool muted = false;
                    float scalar = 0.0f;
                    int hrMute = epv.GetMute(out muted);
                    int hrVol = epv.GetMasterVolumeLevelScalar(out scalar);
                    if (hrVol == 0) {
                        if (hrMute == 0 && muted) return 0;
                        int pct = (int)Math.Round(scalar * 100.0f);
                        if (pct < 0) pct = 0;
                        if (pct > 100) pct = 100;
                        return pct;
                    }
                } catch {}
                finally {
                    try { Marshal.ReleaseComObject(epv); } catch {}
                }
            }
        }
        return fallback;
    }

    public static int SetMasterVolume(int level) {
        int clamped = level;
        if (clamped < 0) clamped = 0;
        if (clamped > 100) clamped = 100;
        bool anySet = false;
        for (int role = 0; role <= 1; role++) {
            IAudioEndpointVolume epv = GetEndpointVolume(role);
            if (epv != null) {
                try {
                    Guid ctx = Guid.Empty;
                    if (clamped == 0) {
                        epv.SetMasterVolumeLevelScalar(0.0f, ref ctx);
                        epv.SetMute(true, ref ctx);
                    } else {
                        epv.SetMute(false, ref ctx);
                        epv.SetMasterVolumeLevelScalar((float)clamped / 100.0f, ref ctx);
                    }
                    anySet = true;
                } catch {}
                finally {
                    try { Marshal.ReleaseComObject(epv); } catch {}
                }
            }
        }
        return anySet ? clamped : GetMasterVolume(clamped);
    }

    public static int GetMouseSpeed(int fallback) {
        try {
            int spd = 0;
            if (SystemParametersInfoGet(0x0070, 0, out spd, 0)) {
                if (spd >= 1 && spd <= 20) return spd;
            }
        } catch {}
        return fallback;
    }

    public static int SetMouseSpeed(int speed) {
        int clamped = speed;
        if (clamped < 1) clamped = 1;
        if (clamped > 20) clamped = 20;
        try {
            SystemParametersInfo(0x0071, 0, new IntPtr(clamped), 0x01 | 0x02);
        } catch {}
        try {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Control Panel\Mouse")) {
                if (key != null) {
                    key.SetValue("MouseSensitivity", clamped.ToString(), RegistryValueKind.String);
                }
            }
        } catch {}
        return GetMouseSpeed(clamped);
    }

    private static void EmitSystemSettings(int volFallback, int mouseFallback) {
        int vol = GetMasterVolume(volFallback);
        int mouse = GetMouseSpeed(mouseFallback);
        Console.Out.WriteLine("SYS_SETTINGS|" + vol.ToString() + "|" + mouse.ToString());
        Console.Out.Flush();
    }

    private static void SetTaskbarVisible(bool visible) {
        try {
            int cmd = visible ? 5 : 0; // SW_SHOW = 5, SW_HIDE = 0
            IntPtr primaryTray = FindWindow("Shell_TrayWnd", null);
            if (primaryTray != IntPtr.Zero) {
                ShowWindowAsync(primaryTray, cmd);
            }
            IntPtr secondaryTray = FindWindow("Shell_SecondaryTrayWnd", null);
            if (secondaryTray != IntPtr.Zero) {
                ShowWindowAsync(secondaryTray, cmd);
            }
            IntPtr startBtn = FindWindowEx(IntPtr.Zero, IntPtr.Zero, "Button", "Start");
            if (startBtn != IntPtr.Zero) {
                ShowWindowAsync(startBtn, cmd);
            }
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                try {
                    StringBuilder sb = new StringBuilder(64);
                    if (GetClassName(hWnd, sb, sb.Capacity) > 0) {
                        string cls = sb.ToString();
                        bool isShellBar = (cls == "Shell_TrayWnd" || cls == "Shell_SecondaryTrayWnd");
                        bool isWin7Start = (cls == "Button" && primaryTray != IntPtr.Zero && GetWindow(hWnd, 4 /* GW_OWNER */) == primaryTray);
                        if (isShellBar || isWin7Start) {
                            bool currentlyVisible = IsWindowVisible(hWnd);
                            if (visible && !currentlyVisible) {
                                ShowWindowAsync(hWnd, cmd);
                            } else if (!visible && currentlyVisible) {
                                ShowWindowAsync(hWnd, cmd);
                            }
                        }
                    }
                } catch {}
                return true;
            }, IntPtr.Zero);
        } catch {}
    }

    private static void SetDisableTaskMgr(bool disabled) {
        try {
            const string sysKey = @"Software\Microsoft\Windows\CurrentVersion\Policies\System";
            const string expKey = @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer";
            if (disabled) {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(sysKey)) {
                    if (key != null) {
                        key.SetValue("DisableTaskMgr", 1, RegistryValueKind.DWord);
                        key.SetValue("DisableLockWorkstation", 1, RegistryValueKind.DWord);
                        key.SetValue("DisableChangePassword", 1, RegistryValueKind.DWord);
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(expKey)) {
                    if (key != null) {
                        key.SetValue("NoLogoff", 1, RegistryValueKind.DWord);
                    }
                }
            } else {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(sysKey, true)) {
                    if (key != null) {
                        try { key.DeleteValue("DisableTaskMgr", false); } catch {}
                        try { key.DeleteValue("DisableLockWorkstation", false); } catch {}
                        try { key.DeleteValue("DisableChangePassword", false); } catch {}
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(expKey, true)) {
                    if (key != null) {
                        try { key.DeleteValue("NoLogoff", false); } catch {}
                    }
                }
            }
        } catch {}
    }

    private static void ApplyMode(int nextMode) {
        int prev = _mode;
        _mode = nextMode;
        bool active = nextMode != 0;
        if (active) {
            SetTaskbarVisible(false);
            if (prev == 0) {
                SetDisableTaskMgr(true);
            }
        } else {
            if (prev != 0) {
                SetTaskbarVisible(true);
                SetDisableTaskMgr(false);
            }
        }
    }

    private static IntPtr InstallHook() {
        IntPtr hMod = IntPtr.Zero;
        try {
            using (Process curProcess = Process.GetCurrentProcess())
            using (ProcessModule curModule = curProcess.MainModule) {
                if (curModule != null) {
                    hMod = GetModuleHandle(curModule.ModuleName);
                }
            }
        } catch {}
        if (hMod == IntPtr.Zero) {
            try { hMod = GetModuleHandle(null); } catch {}
        }
        return SetWindowsHookEx(WH_KEYBOARD_LL, _proc, hMod, 0);
    }

    private static void OnSessionEnding(object sender, SessionEndingEventArgs e) {
        ApplyMode(0);
    }

    public static void Run(int initialMode) {
        _mainThreadId = GetCurrentThreadId();
        ApplyMode(initialMode);
        _hookId = InstallHook();
        if (_hookId == IntPtr.Zero) {
            int err = Marshal.GetLastWin32Error();
            Console.Out.WriteLine("ERR|hook_failed_" + err.ToString());
            Console.Out.Flush();
        } else {
            Console.Out.WriteLine("READY");
            Console.Out.Flush();
        }

        try {
            SystemEvents.SessionEnding += OnSessionEnding;
        } catch {}

        System.Threading.Timer watchdog = new System.Threading.Timer(delegate(object state) {
            if (!_quitting && _mode != 0) {
                SetTaskbarVisible(false);
                try {
                    Process[] mgrs = Process.GetProcessesByName("taskmgr");
                    foreach (Process p in mgrs) {
                        try { p.Kill(); } catch {}
                    }
                } catch {}
            }
        }, null, 1000, 1000);

        Thread reader = new Thread(new ThreadStart(delegate {
            try {
                while (true) {
                    string line = Console.In.ReadLine();
                    if (line == null) {
                        break;
                    }
                    string rawLine = line.Trim();
                    string cmd = rawLine.ToUpperInvariant();
                    if (cmd == "LOCK") {
                        ApplyMode(1);
                    } else if (cmd == "GAME") {
                        ApplyMode(2);
                    } else if (cmd == "DISABLE") {
                        ApplyMode(0);
                    } else if (cmd == "LIST_WINDOWS") {
                        ListWindows();
                    } else if (cmd.StartsWith("FOCUS ")) {
                        try {
                            IntPtr h = (IntPtr)long.Parse(rawLine.Substring(6).Trim());
                            FocusWindow(h);
                        } catch {}
                    } else if (cmd.StartsWith("MINIMIZE ")) {
                        try {
                            IntPtr h = (IntPtr)long.Parse(rawLine.Substring(9).Trim());
                            MinimizeWindow(h);
                        } catch {}
                    } else if (cmd.StartsWith("CLOSE ")) {
                        try {
                            string[] parts = rawLine.Substring(6).Trim().Split(' ');
                            IntPtr h = (IntPtr)long.Parse(parts[0]);
                            int pid = parts.Length > 1 ? int.Parse(parts[1]) : 0;
                            CloseWindow(h, pid);
                        } catch {}
                    } else if (cmd.StartsWith("KILL_ALL_APPS")) {
                        try {
                            string[] parts = rawLine.Split(' ');
                            int myPid = parts.Length > 1 ? int.Parse(parts[1]) : 0;
                            KillAllApps(myPid);
                        } catch {}
                    } else if (cmd == "SWITCH_NEXT") {
                        SwitchToNextWindow();
                    } else if (cmd == "GET_SYS_SETTINGS") {
                        EmitSystemSettings(75, 10);
                    } else if (cmd.StartsWith("SET_VOLUME ")) {
                        try {
                            int val = int.Parse(rawLine.Substring(11).Trim());
                            int actual = SetMasterVolume(val);
                            EmitSystemSettings(actual, GetMouseSpeed(10));
                        } catch {}
                    } else if (cmd.StartsWith("SET_MOUSE_SPEED ")) {
                        try {
                            int val = int.Parse(rawLine.Substring(16).Trim());
                            int actual = SetMouseSpeed(val);
                            EmitSystemSettings(GetMasterVolume(75), actual);
                        } catch {}
                    } else if (cmd == "QUIT") {
                        break;
                    }
                }
            } catch {}
            _quitting = true;
            ApplyMode(0);
            if (_mainThreadId != 0) {
                PostThreadMessage(_mainThreadId, WM_QUIT, UIntPtr.Zero, IntPtr.Zero);
            }
        }));
        reader.IsBackground = true;
        try { reader.SetApartmentState(ApartmentState.STA); } catch {}
        reader.Start();

        try {
            MSG msg;
            while (GetMessage(out msg, IntPtr.Zero, 0, 0) > 0) {
                TranslateMessage(ref msg);
                DispatchMessage(ref msg);
            }
        } finally {
            _quitting = true;
            try { watchdog.Dispose(); } catch {}
            try { SystemEvents.SessionEnding -= OnSessionEnding; } catch {}
            if (_hookId != IntPtr.Zero) {
                UnhookWindowsHookEx(_hookId);
                _hookId = IntPtr.Zero;
            }
            ApplyMode(0);
        }
    }
}
"@
[GnKioskGuard]::Run(__INITIAL_MODE__)
`;

function modeToInt(mode: KioskGuardMode): number {
  if (mode === "LOCK") return 1;
  if (mode === "GAME") return 2;
  return 0;
}

export class Win32KioskGuard {
  private worker: ChildProcessWithoutNullStreams | null = null;
  private workerReady = false;
  private mode: KioskGuardMode = "DISABLED";
  private desiredMode: KioskGuardMode = "DISABLED";
  private disposed = false;
  private retryTimer: NodeJS.Timeout | null = null;
  onAltF5?: () => void;
  onAltTab?: () => void;
  onWorkerUp?: () => void;
  onWorkerDown?: () => void;
  private pendingWindowsResolve: ((windows: Win32AppWindow[]) => void) | null = null;
  private pendingWindowsPromise: Promise<Win32AppWindow[]> | null = null;
  private collectingWindows: Win32AppWindow[] | null = null;
  private pendingSysResolves: Array<(s: { volume: number; mouseSpeed: number }) => void> = [];
  private pendingRawCommands: string[] = [];
  private cachedVolume = 75;
  private cachedMouseSpeed = 10;

  ensureStarted(): void {
    if (process.platform !== "win32" || this.disposed) return;
    if (!this.worker) {
      this.startWorker(this.desiredMode);
    }
  }

  setMode(next: KioskGuardMode): void {
    this.desiredMode = next;
    if (process.platform !== "win32" || this.disposed) {
      this.mode = next;
      return;
    }

    if (next === "DISABLED" && !this.worker) {
      this.mode = "DISABLED";
      return;
    }

    if (!this.worker) {
      this.mode = next;
      this.startWorker(next);
      return;
    }

    if (this.mode !== next) {
      this.mode = next;
      this.sendCommand(next);
    }
  }

  private startWorker(initialMode: KioskGuardMode): void {
    if (this.worker || this.disposed || process.platform !== "win32") return;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }

    try {
      const rawScript = KIOSK_GUARD_PS.replace("__INITIAL_MODE__", String(modeToInt(initialMode)));
      const script = rawScript
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0 && !line.startsWith("//"))
        .join("\n");
      const workerDir = fs.mkdtempSync(path.join(os.tmpdir(), "gamenet-guard-"));
      const scriptPath = path.join(workerDir, "guard.ps1");
      fs.writeFileSync(scriptPath, `\uFEFF${script}`, { mode: 0o600 });
      const proc = spawn(
        "powershell.exe",
        ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", scriptPath],
        { windowsHide: true },
      );
      this.worker = proc;

      const rl = readline.createInterface({ input: proc.stdout });
      const rle = readline.createInterface({ input: proc.stderr });
      let handled = false;
      const readyTimer = setTimeout(() => failWorker(new Error("Kiosk guard READY timeout")), 20_000);
      const failWorker = (error?: Error) => {
        if (handled) return;
        handled = true;
        clearTimeout(readyTimer);
        if (this.worker === proc) {
          this.worker = null;
          this.workerReady = false;
        }
        try { proc.kill(); } catch {}
        rl.close();
        rle.close();
        if (error) log("warn", `kiosk guard failed: ${error.message}`);
        this.onWorkerDown?.();
        if (!this.disposed && this.desiredMode !== "DISABLED") {
          this.retryTimer = setTimeout(() => {
            this.retryTimer = null;
            this.startWorker(this.desiredMode);
          }, 2_000);
        }
      };
      proc.once("error", failWorker);
      proc.stdin.on("error", failWorker);
      proc.once("close", () => {
        failWorker();
        try { fs.unlinkSync(scriptPath); fs.rmdirSync(workerDir); } catch {}
      });

      rl.on("line", (line) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        if (trimmed === "READY") {
          clearTimeout(readyTimer);
          this.workerReady = true;
          log("info", `win32 kiosk guard active (mode=${this.desiredMode})`);
          this.onWorkerUp?.();
          if (this.desiredMode !== initialMode) {
            this.sendCommand(this.desiredMode);
          }
          const queued = this.pendingRawCommands.splice(0, this.pendingRawCommands.length);
          for (const qCmd of queued) {
            this.writeLine(qCmd);
          }
        } else if (trimmed.startsWith("SYS_SETTINGS|")) {
          const parts = trimmed.split("|");
          if (parts.length >= 3) {
            const vol = Number(parts[1]);
            const spd = Number(parts[2]);
            if (Number.isFinite(vol)) this.cachedVolume = Math.min(100, Math.max(0, Math.round(vol)));
            if (Number.isFinite(spd)) this.cachedMouseSpeed = Math.min(20, Math.max(1, Math.round(spd)));
          }
          const resolvers = this.pendingSysResolves.splice(0, this.pendingSysResolves.length);
          for (const resFn of resolvers) {
            resFn({ volume: this.cachedVolume, mouseSpeed: this.cachedMouseSpeed });
          }
        } else if (trimmed === "EVENT|ALTF5") {
          log("info", "win32 kiosk guard detected Alt+F5 event");
          this.onAltF5?.();
        } else if (trimmed === "EVENT|ALTTAB") {
          this.onAltTab?.();
        } else if (trimmed === "WINDOWS_START") {
          this.collectingWindows = [];
        } else if (trimmed.startsWith("WINDOW|")) {
          const content = trimmed.slice(7);
          if (this.collectingWindows && content) {
            const parts = content.split("\t");
            if (parts.length >= 6) {
              this.collectingWindows.push({
                hwnd: parts[0],
                pid: Number(parts[1]) || 0,
                isForeground: parts[2] === "1",
                isMinimized: parts[3] === "1",
                processName: parts[4] || "",
                title: parts[5] || "",
              });
            }
          }
        } else if (trimmed.startsWith("WINDOWS|")) {
          const content = trimmed.slice(8);
          if (this.collectingWindows && content) {
            const rows = content.split("\n");
            for (const r of rows) {
              const parts = r.split("\t");
              if (parts.length >= 6) {
                this.collectingWindows.push({
                  hwnd: parts[0],
                  pid: Number(parts[1]) || 0,
                  isForeground: parts[2] === "1",
                  isMinimized: parts[3] === "1",
                  processName: parts[4] || "",
                  title: parts[5] || "",
                });
              }
            }
          }
        } else if (trimmed === "WINDOWS_END") {
          if (this.pendingWindowsResolve) {
            this.pendingWindowsResolve(this.collectingWindows || []);
            this.pendingWindowsResolve = null;
            this.pendingWindowsPromise = null;
            this.collectingWindows = null;
          }
        } else if (trimmed.startsWith("ERR|")) {
          log("warn", `win32 kiosk guard warning: ${trimmed.slice(4)}`);
          if (trimmed.includes("hook_failed")) this.onWorkerDown?.();
        }
      });

      rle.on("line", (line) => {
        const trimmed = line.trim();
        if (trimmed) log("warn", `win32 kiosk guard stderr: ${trimmed}`);
      });

    } catch (err) {
      log("warn", `failed starting win32 kiosk guard: ${err instanceof Error ? err.message : String(err)}`);
      this.onWorkerDown?.();
      if (!this.disposed && this.desiredMode !== "DISABLED") {
        this.retryTimer = setTimeout(() => this.startWorker(this.desiredMode), 2_000);
      }
    }
  }

  private writeLine(commandStr: string): void {
    try {
      if (this.worker && this.worker.stdin.writable) {
        this.worker.stdin.write(`${commandStr}\n`);
      }
    } catch {}
  }

  private sendCommand(cmd: KioskGuardMode | "QUIT"): void {
    const target = cmd === "DISABLED" ? "DISABLE" : cmd;
    this.sendRawCommand(target);
  }

  sendRawCommand(commandStr: string): void {
    if (process.platform !== "win32" || this.disposed) return;
    if (!this.worker) {
      this.pendingRawCommands.push(commandStr);
      this.startWorker(this.desiredMode);
      return;
    }
    if (!this.workerReady && commandStr !== "QUIT") {
      this.pendingRawCommands.push(commandStr);
      return;
    }
    this.writeLine(commandStr);
  }

  async getSystemSettings(): Promise<{ volume: number; mouseSpeed: number }> {
    if (process.platform !== "win32" || this.disposed) {
      return { volume: this.cachedVolume, mouseSpeed: this.cachedMouseSpeed };
    }
    return new Promise((resolve) => {
      this.pendingSysResolves.push(resolve);
      this.sendRawCommand("GET_SYS_SETTINGS");
      setTimeout(() => {
        const idx = this.pendingSysResolves.indexOf(resolve);
        if (idx >= 0) {
          this.pendingSysResolves.splice(idx, 1);
          resolve({ volume: this.cachedVolume, mouseSpeed: this.cachedMouseSpeed });
        }
      }, 5000);
    });
  }

  setVolume(level: number): number {
    const clamped = Math.min(100, Math.max(0, Math.round(level)));
    this.cachedVolume = clamped;
    this.sendRawCommand(`SET_VOLUME ${clamped}`);
    return clamped;
  }

  setMouseSpeed(speed: number): number {
    const clamped = Math.min(20, Math.max(1, Math.round(speed)));
    this.cachedMouseSpeed = clamped;
    this.sendRawCommand(`SET_MOUSE_SPEED ${clamped}`);
    return clamped;
  }

  async listWindows(): Promise<Win32AppWindow[]> {
    if (process.platform !== "win32" || !this.worker) return [];
    if (this.pendingWindowsPromise) {
      return this.pendingWindowsPromise;
    }
    this.pendingWindowsPromise = new Promise<Win32AppWindow[]>((resolve) => {
      const finish = (wins: Win32AppWindow[]) => {
        this.pendingWindowsPromise = null;
        resolve(wins);
      };
      this.pendingWindowsResolve = finish;
      this.collectingWindows = [];
      this.sendRawCommand("LIST_WINDOWS");
      setTimeout(() => {
        if (this.pendingWindowsResolve === finish) {
          this.pendingWindowsResolve = null;
          this.pendingWindowsPromise = null;
          resolve(this.collectingWindows || []);
          this.collectingWindows = null;
        }
      }, 3000);
    });
    return this.pendingWindowsPromise;
  }

  focusWindow(hwnd: string): void {
    this.sendRawCommand(`FOCUS ${hwnd}`);
  }

  minimizeWindow(hwnd: string): void {
    this.sendRawCommand(`MINIMIZE ${hwnd}`);
  }

  closeWindow(hwnd: string, pid?: number): void {
    this.sendRawCommand(`CLOSE ${hwnd} ${pid || 0}`);
  }

  killAllApps(currentPid?: number): void {
    const pid = currentPid || process.pid;
    this.sendRawCommand(`KILL_ALL_APPS ${pid}`);
  }

  switchToNextWindow(): void {
    this.sendRawCommand("SWITCH_NEXT");
  }

  dispose(): void {
    this.disposed = true;
    this.workerReady = false;
    this.desiredMode = "DISABLED";
    this.mode = "DISABLED";
    this.pendingRawCommands = [];
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.worker) {
      this.writeLine("QUIT");
      const target = this.worker;
      this.worker = null;
      try {
        target.stdin.end();
      } catch {}
      setTimeout(() => {
        try {
          if (!target.killed) target.kill();
        } catch {}
      }, 600);
    }
  }
}
