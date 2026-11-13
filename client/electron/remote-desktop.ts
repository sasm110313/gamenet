import { desktopCapturer, screen } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import readline from "node:readline";
import { log } from "./logger";

export interface RemoteFramePayload {
  kind: "screenshot" | "stream";
  width: number;
  height: number;
  format: "jpeg";
  data: string;
  captured_at: string;
  request_id?: string;
}

export interface RemoteControlMessage {
  action?: string;
  request_id?: string;
  width?: number;
  quality?: number;
  fps?: number;
  event?: Record<string, unknown>;
}

const WIN32_HELPER_PS = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @"
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Windows.Forms;
using System.Runtime.InteropServices;

public class GnRemoteHelper {
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct CURSORINFO {
        public int cbSize;
        public int flags;
        public IntPtr hCursor;
        public POINT ptScreenPos;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct ICONINFO {
        public bool fIcon;
        public int xHotspot;
        public int yHotspot;
        public IntPtr hbmMask;
        public IntPtr hbmColor;
    }

    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, int dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
    [DllImport("user32.dll")] public static extern bool GetCursorInfo(ref CURSORINFO pci);
    [DllImport("user32.dll")] public static extern IntPtr CopyIcon(IntPtr hIcon);
    [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr hIcon);
    [DllImport("user32.dll")] public static extern bool GetIconInfo(IntPtr hIcon, out ICONINFO piconinfo);
    [DllImport("user32.dll")] public static extern bool DrawIconEx(IntPtr hdc, int xLeft, int yTop, IntPtr hIcon, int cxWidth, int cyWidth, int istepIfAniCur, IntPtr hbrFlickerFreeDraw, int diFlags);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr hObject);

    private static ImageCodecInfo jpegCodec = null;
    private static ImageCodecInfo GetJpegCodec() {
        if (jpegCodec != null) return jpegCodec;
        foreach (ImageCodecInfo c in ImageCodecInfo.GetImageEncoders()) {
            if (c.MimeType == "image/jpeg") { jpegCodec = c; break; }
        }
        return jpegCodec;
    }

    private static bool IsExtended(byte vk) {
        return vk == 0x21 || vk == 0x22 || vk == 0x23 || vk == 0x24 ||
               vk == 0x25 || vk == 0x26 || vk == 0x27 || vk == 0x28 ||
               vk == 0x2D || vk == 0x2E || vk == 0x5B || vk == 0x5C ||
               vk == 0x5D || vk == 0x6F || vk == 0x90 || vk == 0xA3 || vk == 0xA5;
    }

    private static void DrawCursor(Graphics g, int offsetX, int offsetY) {
        try {
            CURSORINFO ci = new CURSORINFO();
            ci.cbSize = Marshal.SizeOf(typeof(CURSORINFO));
            if (!GetCursorInfo(ref ci) || (ci.flags & 1) == 0 || ci.hCursor == IntPtr.Zero) return;

            IntPtr hIcon = CopyIcon(ci.hCursor);
            bool copied = hIcon != IntPtr.Zero;
            if (!copied) hIcon = ci.hCursor;
            try {
                int x = ci.ptScreenPos.X - offsetX;
                int y = ci.ptScreenPos.Y - offsetY;
                ICONINFO ii;
                if (GetIconInfo(hIcon, out ii)) {
                    try {
                        x -= ii.xHotspot;
                        y -= ii.yHotspot;
                    } finally {
                        if (ii.hbmMask != IntPtr.Zero) DeleteObject(ii.hbmMask);
                        if (ii.hbmColor != IntPtr.Zero) DeleteObject(ii.hbmColor);
                    }
                }
                IntPtr hdc = g.GetHdc();
                try {
                    DrawIconEx(hdc, x, y, hIcon, 0, 0, 0, IntPtr.Zero, 3);
                } finally {
                    g.ReleaseHdc(hdc);
                }
            } finally {
                if (copied) DestroyIcon(hIcon);
            }
        } catch {
        }
    }

    public static void MoveAbs(double nx, double ny) {
        int sw = Math.Max(1, GetSystemMetrics(0));
        int sh = Math.Max(1, GetSystemMetrics(1));
        double cx = Math.Max(0.0, Math.Min(1.0, nx));
        double cy = Math.Max(0.0, Math.Min(1.0, ny));
        int px = (int)Math.Round(cx * (sw - 1));
        int py = (int)Math.Round(cy * (sh - 1));
        SetCursorPos(px, py);
        mouse_event(0x8001u, (int)Math.Round(cx * 65535.0), (int)Math.Round(cy * 65535.0), 0, UIntPtr.Zero);
    }

    public static void MouseButton(int btn, bool down, double nx, double ny) {
        MoveAbs(nx, ny);
        uint flag = 0;
        if (btn == 0) flag = down ? 0x0002u : 0x0004u;
        else if (btn == 1) flag = down ? 0x0020u : 0x0040u;
        else if (btn == 2) flag = down ? 0x0008u : 0x0010u;
        if (flag != 0) mouse_event(flag, 0, 0, 0, UIntPtr.Zero);
    }

    public static void Wheel(int delta, double nx, double ny) {
        MoveAbs(nx, ny);
        mouse_event(0x0800u, 0, 0, delta, UIntPtr.Zero);
    }

    private static readonly UIntPtr RDP_TAG = new UIntPtr(0x474E5244u);

    public static void Key(byte vk, bool down) {
        byte scan = (byte)(MapVirtualKey((uint)vk, 0) & 0xFF);
        uint flags = (IsExtended(vk) ? 0x0001u : 0u) | (down ? 0u : 0x0002u);
        keybd_event(vk, scan, flags, RDP_TAG);
    }

    public static string CaptureJpeg(int maxWidth, long quality) {
        Rectangle bounds = Screen.PrimaryScreen.Bounds;
        int sw = Math.Max(1, bounds.Width);
        int sh = Math.Max(1, bounds.Height);
        int tw = Math.Min(sw, Math.Max(320, maxWidth));
        int th = Math.Max(180, (int)Math.Round((double)sh * tw / sw));

        using (Bitmap raw = new Bitmap(sw, sh, PixelFormat.Format24bppRgb)) {
            using (Graphics g = Graphics.FromImage(raw)) {
                g.CopyFromScreen(bounds.X, bounds.Y, 0, 0, bounds.Size, CopyPixelOperation.SourceCopy);
                DrawCursor(g, bounds.X, bounds.Y);
            }
            Bitmap target = raw;
            bool disposeTarget = false;
            if (tw != sw || th != sh) {
                target = new Bitmap(tw, th, PixelFormat.Format24bppRgb);
                disposeTarget = true;
                using (Graphics sg = Graphics.FromImage(target)) {
                    sg.InterpolationMode = InterpolationMode.Bilinear;
                    sg.DrawImage(raw, 0, 0, tw, th);
                }
            }
            try {
                using (MemoryStream ms = new MemoryStream()) {
                    ImageCodecInfo codec = GetJpegCodec();
                    if (codec != null) {
                        using (EncoderParameters ep = new EncoderParameters(1))
                        using (EncoderParameter ep0 = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, Math.Max(25L, Math.Min(95L, quality)))) {
                            ep.Param[0] = ep0;
                            target.Save(ms, codec, ep);
                        }
                    } else {
                        target.Save(ms, ImageFormat.Jpeg);
                    }
                    return tw.ToString() + "|" + th.ToString() + "|" + Convert.ToBase64String(ms.ToArray());
                }
            } finally {
                if (disposeTarget) target.Dispose();
            }
        }
    }
}
"@
$ErrorActionPreference = 'Continue'
try { [void][GnRemoteHelper]::SetProcessDPIAware() } catch {}
$elev = "0"
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    if ($pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $elev = "1" }
} catch {}
[Console]::Out.WriteLine("READY|" + $elev)
[Console]::Out.Flush()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if ($line -eq "") { continue }
    $parts = $line.Split('|')
    $op = $parts[0]
    $seq = ""
    try {
        if ($op -eq "CAP") {
            $seq = $parts[1]
            $mw = [int]$parts[2]
            $q = [long]$parts[3]
            $res = [GnRemoteHelper]::CaptureJpeg($mw, $q)
            [Console]::Out.WriteLine("FRAME|" + $seq + "|" + $res)
            [Console]::Out.Flush()
        } elseif ($op -eq "MV") {
            [GnRemoteHelper]::MoveAbs([double]::Parse($parts[1], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "MD") {
            [GnRemoteHelper]::MouseButton([int]$parts[1], $true, [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[3], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "MU") {
            [GnRemoteHelper]::MouseButton([int]$parts[1], $false, [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[3], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "WH") {
            [GnRemoteHelper]::Wheel([int]$parts[1], [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[3], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "KD") {
            [GnRemoteHelper]::Key([byte][int]$parts[1], $true)
        } elseif ($op -eq "KU") {
            [GnRemoteHelper]::Key([byte][int]$parts[1], $false)
        } elseif ($op -eq "SC") {
            $codes = $parts[1].Split(',')
            foreach ($c in $codes) { if ($c -ne "") { [GnRemoteHelper]::Key([byte][int]$c, $true) } }
            for ($i = $codes.Length - 1; $i -ge 0; $i--) { if ($codes[$i] -ne "") { [GnRemoteHelper]::Key([byte][int]$codes[$i], $false) } }
        }
    } catch {
        if ($op -eq "CAP") {
            [Console]::Out.WriteLine("ERR|" + $seq + "|" + ([string]$_.Exception.Message).Replace([char]13, ' ').Replace([char]10, ' '))
            [Console]::Out.Flush()
        }
    }
}
`;

export class RemoteDesktopService {
  private readonly sendFrame: (frame: RemoteFramePayload) => void;
  private worker: ChildProcessWithoutNullStreams | null = null;
  private workerReady = false;
  private workerStarting: Promise<boolean> | null = null;
  private workerRetryAfter = 0;
  private pendingCaptures = new Map<number, (res: { width: number; height: number; data: string } | null) => void>();
  private nextCaptureSeq = 1;
  private warnedUnsupportedInput = false;

  private streamTimer: NodeJS.Timeout | null = null;
  private streamIdleTimer: NodeJS.Timeout | null = null;
  private streamInFlight = false;
  private streamFps = 5;
  private streamWidth = 1024;
  private streamQuality = 64;
  private inputQueue: Promise<void> = Promise.resolve();

  constructor(sendFrame: (frame: RemoteFramePayload) => void) {
    this.sendFrame = sendFrame;
  }

  handleControl(msg: RemoteControlMessage): void {
    const action = String(msg.action || "");
    if (action === "screenshot") {
      void this.captureAndSend({
        kind: "screenshot",
        width: clampInt(msg.width, 480, 1920, 1280),
        quality: clampInt(msg.quality, 40, 95, 84),
        requestId: typeof msg.request_id === "string" ? msg.request_id : undefined,
      });
      return;
    }

    if (action === "stream_start") {
      this.streamFps = clampInt(msg.fps, 1, 8, 5);
      this.streamWidth = clampInt(msg.width, 480, 1440, 1024);
      this.streamQuality = clampInt(msg.quality, 35, 90, 64);
      void this.ensureWin32Worker();
      this.startStream();
      return;
    }

    if (action === "stream_keepalive") {
      this.bumpIdleTimeout();
      return;
    }

    if (action === "stream_stop") {
      this.stopStream();
      return;
    }

    if (action === "input" && msg.event && typeof msg.event === "object") {
      this.bumpIdleTimeout();
      const ev = msg.event;
      this.inputQueue = this.inputQueue.then(() => this.injectInput(ev)).catch(() => {});
    }
  }

  dispose(): void {
    this.stopStream();
    if (this.worker) {
      try {
        this.worker.kill();
      } catch {}
      this.worker = null;
      this.workerReady = false;
    }
    this.clearPendingCaptures();
  }

  private clearPendingCaptures(): void {
    for (const done of this.pendingCaptures.values()) {
      done(null);
    }
    this.pendingCaptures.clear();
  }

  private startStream(): void {
    this.stopStream();
    this.bumpIdleTimeout();
    void this.tickStream();
    const intervalMs = Math.max(120, Math.round(1000 / Math.max(1, this.streamFps)));
    this.streamTimer = setInterval(() => {
      void this.tickStream();
    }, intervalMs);
  }

  stopStream(): void {
    if (this.streamTimer) {
      clearInterval(this.streamTimer);
      this.streamTimer = null;
    }
    if (this.streamIdleTimer) {
      clearTimeout(this.streamIdleTimer);
      this.streamIdleTimer = null;
    }
    this.streamInFlight = false;
  }

  private bumpIdleTimeout(): void {
    if (!this.streamTimer) return;
    if (this.streamIdleTimer) clearTimeout(this.streamIdleTimer);
    this.streamIdleTimer = setTimeout(() => {
      this.stopStream();
    }, 15_000);
  }

  private async tickStream(): Promise<void> {
    if (this.streamInFlight) return;
    this.streamInFlight = true;
    try {
      await this.captureAndSend({
        kind: "stream",
        width: this.streamWidth,
        quality: this.streamQuality,
      });
    } finally {
      this.streamInFlight = false;
    }
  }

  private async captureAndSend(opts: {
    kind: "screenshot" | "stream";
    width: number;
    quality: number;
    requestId?: string;
  }): Promise<void> {
    try {
      const captured = await this.captureScreen(opts.kind, opts.width, opts.quality);
      if (!captured) return;
      this.sendFrame({
        kind: opts.kind,
        width: captured.width,
        height: captured.height,
        format: "jpeg",
        data: captured.data,
        captured_at: new Date().toISOString(),
        request_id: opts.requestId,
      });
    } catch (err) {
      log("warn", `remote capture error: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  private async captureScreen(
    kind: "screenshot" | "stream",
    maxWidth: number,
    quality: number,
  ): Promise<{ width: number; height: number; data: string } | null> {
    if (process.platform === "win32") {
      // On Windows, always prefer the persistent DPI-aware C# GDI worker (fast, includes cursor,
      // and avoids Electron desktopCapturer.getSources() per-frame CPU overhead and mouse lag).
      const workerFrame = await this.captureViaWin32Worker(maxWidth, quality);
      if (workerFrame) return workerFrame;
      // Avoid hammering desktopCapturer.getSources on every stream tick when the worker is active.
      if (kind === "stream" && this.workerReady) return null;
    }

    try {
      const display = screen.getPrimaryDisplay();
      const physW = Math.max(1, Math.round(display.size.width * (display.scaleFactor || 1)));
      const physH = Math.max(1, Math.round(display.size.height * (display.scaleFactor || 1)));
      const targetW = Math.min(physW, Math.max(320, maxWidth));
      const targetH = Math.max(180, Math.round((physH * targetW) / physW));

      const sources = await desktopCapturer.getSources({
        types: ["screen"],
        thumbnailSize: { width: targetW, height: targetH },
      });
      const primary = sources[0];
      if (primary && !primary.thumbnail.isEmpty()) {
        const jpg = primary.thumbnail.toJPEG(quality);
        const sz = primary.thumbnail.getSize();
        if (jpg.length > 2200) {
          return {
            width: sz.width,
            height: sz.height,
            data: jpg.toString("base64"),
          };
        }
      }
    } catch (err) {
      log("warn", `desktopCapturer failed: ${String(err)}`);
    }

    return null;
  }

  private async ensureWin32Worker(): Promise<boolean> {
    if (process.platform !== "win32") return false;
    if (this.worker && this.workerReady && !this.worker.killed) return true;
    if (this.workerStarting) return this.workerStarting;
    if (Date.now() < this.workerRetryAfter) return false;

    this.workerStarting = new Promise<boolean>((resolve) => {
      try {
        const encoded = Buffer.from(WIN32_HELPER_PS, "utf16le").toString("base64");
        const proc = spawn(
          "powershell.exe",
          [
            "-NoProfile",
            "-NonInteractive",
            "-InputFormat",
            "None",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
          ],
          { windowsHide: true },
        );
        this.worker = proc;
        this.workerReady = false;

        let settled = false;
        let startupTimer: NodeJS.Timeout | null = null;
        const rl = readline.createInterface({ input: proc.stdout });
        const rle = readline.createInterface({ input: proc.stderr });
        const finishStart = (ok: boolean) => {
          if (startupTimer) {
            clearTimeout(startupTimer);
            startupTimer = null;
          }
          if (!ok) {
            this.workerRetryAfter = Date.now() + 15_000;
          } else {
            this.workerRetryAfter = 0;
          }
          if (!settled) {
            settled = true;
            resolve(ok);
          }
        };

        rl.on("line", (line) => {
          if (line === "READY" || line.startsWith("READY|")) {
            this.workerReady = true;
            const elevated = line.endsWith("|1");
            log(
              "info",
              elevated
                ? "win32 remote worker ready (elevated=true)"
                : "win32 remote worker ready (elevated=false; UIPI blocks input to elevated windows)",
            );
            finishStart(true);
            return;
          }
          if (line.startsWith("FRAME|")) {
            const parts = line.split("|");
            const seq = parseInt(parts[1] || "0", 10);
            const w = parseInt(parts[2] || "0", 10);
            const h = parseInt(parts[3] || "0", 10);
            const data = parts[4] || "";
            const cb = this.pendingCaptures.get(seq);
            if (cb) {
              this.pendingCaptures.delete(seq);
              cb(data ? { width: w, height: h, data } : null);
            }
            return;
          }
          if (line.startsWith("ERR|")) {
            const firstSep = line.indexOf("|", 4);
            const seq = firstSep > 4 ? parseInt(line.slice(4, firstSep), 10) : 0;
            const errText = firstSep > 4 ? line.slice(firstSep + 1) : line.slice(4);
            log("warn", `win32 worker error: ${errText}`);
            const cb = this.pendingCaptures.get(seq);
            if (cb) {
              this.pendingCaptures.delete(seq);
              cb(null);
            }
          }
        });
        rle.on("line", (line) => {
          const trimmed = line.trim();
          if (trimmed) log("warn", `win32 helper stderr: ${trimmed}`);
        });

        proc.on("exit", (code) => {
          if (code && !this.workerReady) {
            log("warn", `win32 helper exited before READY (code ${code})`);
          }
          this.workerReady = false;
          if (this.worker === proc) this.worker = null;
          rl.close();
          rle.close();
          this.clearPendingCaptures();
          finishStart(false);
        });

        startupTimer = setTimeout(() => {
          if (!settled) {
            log("warn", "win32 helper startup timed out after 15s");
            if (this.worker === proc) {
              this.worker = null;
              this.workerReady = false;
            }
            try {
              proc.kill();
            } catch {}
            finishStart(false);
          }
        }, 15_000);
      } catch (err) {
        this.workerRetryAfter = Date.now() + 15_000;
        log("warn", `failed spawning win32 helper: ${String(err)}`);
        resolve(false);
      }
    }).finally(() => {
      this.workerStarting = null;
    });

    return this.workerStarting;
  }

  private async captureViaWin32Worker(
    maxWidth: number,
    quality: number,
  ): Promise<{ width: number; height: number; data: string } | null> {
    const ok = await this.ensureWin32Worker();
    if (!ok || !this.worker) return null;
    const seq = this.nextCaptureSeq++;
    return await new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pendingCaptures.delete(seq);
        resolve(null);
      }, 6_000);

      const done = (res: { width: number; height: number; data: string } | null) => {
        clearTimeout(timer);
        resolve(res);
      };

      this.pendingCaptures.set(seq, done);
      try {
        this.worker?.stdin.write(`CAP|${seq}|${maxWidth}|${quality}\n`);
      } catch {
        this.pendingCaptures.delete(seq);
        clearTimeout(timer);
        resolve(null);
      }
    });
  }

  private async injectInput(ev: Record<string, unknown>): Promise<void> {
    if (process.platform !== "win32") {
      if (!this.warnedUnsupportedInput) {
        this.warnedUnsupportedInput = true;
        log("info", `remote input injection skipped on non-win32 platform (${process.platform})`);
      }
      return;
    }
    const ok = await this.ensureWin32Worker();
    if (!ok || !this.worker) return;

    const kind = String(ev.kind || "");
    const nx = clampFloat(ev.x, 0, 1, 0.5).toFixed(5);
    const ny = clampFloat(ev.y, 0, 1, 0.5).toFixed(5);
    let line = "";

    if (kind === "mv") {
      line = `MV|${nx}|${ny}`;
    } else if (kind === "md") {
      const btn = clampInt(ev.button, 0, 2, 0);
      line = `MD|${btn}|${nx}|${ny}`;
    } else if (kind === "mu") {
      const btn = clampInt(ev.button, 0, 2, 0);
      line = `MU|${btn}|${nx}|${ny}`;
    } else if (kind === "wh") {
      const delta = clampInt(ev.delta, -600, 600, -120);
      line = `WH|${delta}|${nx}|${ny}`;
    } else if (kind === "kd" || kind === "ku") {
      const vk = resolveWindowsVk(ev);
      if (vk > 0) line = `${kind === "kd" ? "KD" : "KU"}|${vk}`;
    } else if (kind === "combo" && Array.isArray(ev.vks)) {
      const vks = (ev.vks as unknown[])
        .map((n) => clampInt(n, 0, 255, 0))
        .filter((n) => n > 0 && n < 255);
      if (vks.length > 0) line = `SC|${vks.join(",")}`;
    }

    if (line) {
      try {
        this.worker.stdin.write(`${line}\n`);
      } catch {}
    }
  }
}

function clampInt(val: unknown, min: number, max: number, fallback: number): number {
  const n = typeof val === "number" ? val : Number(val);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.round(n)));
}

function clampFloat(val: unknown, min: number, max: number, fallback: number): number {
  const n = typeof val === "number" ? val : Number(val);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

const CODE_TO_VK: Record<string, number> = {
  Backspace: 0x08,
  Tab: 0x09,
  Enter: 0x0d,
  NumpadEnter: 0x0d,
  ShiftLeft: 0x10,
  ShiftRight: 0x10,
  ControlLeft: 0x11,
  ControlRight: 0xa3,
  AltLeft: 0x12,
  AltRight: 0xa5,
  Pause: 0x13,
  CapsLock: 0x14,
  Escape: 0x1b,
  Space: 0x20,
  PageUp: 0x21,
  PageDown: 0x22,
  End: 0x23,
  Home: 0x24,
  ArrowLeft: 0x25,
  ArrowUp: 0x26,
  ArrowRight: 0x27,
  ArrowDown: 0x28,
  PrintScreen: 0x2c,
  Insert: 0x2d,
  Delete: 0x2e,
  MetaLeft: 0x5b,
  MetaRight: 0x5c,
  ContextMenu: 0x5d,
  NumLock: 0x90,
  ScrollLock: 0x91,
  Semicolon: 0xba,
  Equal: 0xbb,
  Comma: 0xbc,
  Minus: 0xbd,
  Period: 0xbe,
  Slash: 0xbf,
  Backquote: 0xc0,
  BracketLeft: 0xdb,
  Backslash: 0xdc,
  BracketRight: 0xdd,
  Quote: 0xde,
  NumpadMultiply: 0x6a,
  NumpadAdd: 0x6b,
  NumpadSubtract: 0x6d,
  NumpadDecimal: 0x6e,
  NumpadDivide: 0x6f,
};

function resolveWindowsVk(ev: Record<string, unknown>): number {
  const code = typeof ev.code === "string" ? ev.code : "";
  if (code) {
    if (CODE_TO_VK[code]) return CODE_TO_VK[code];
    if (code.startsWith("Key") && code.length === 4) {
      return code.charCodeAt(3); // A-Z 0x41..0x5A
    }
    if (code.startsWith("Digit") && code.length === 6) {
      return code.charCodeAt(5); // 0-9 0x30..0x39
    }
    if (code.startsWith("Numpad") && code.length === 7) {
      const d = code.charCodeAt(6) - 48;
      if (d >= 0 && d <= 9) return 0x60 + d;
    }
    if (code.startsWith("F") && code.length <= 3) {
      const f = parseInt(code.slice(1), 10);
      if (f >= 1 && f <= 12) return 0x6f + f;
    }
  }
  const keyCode = typeof ev.keyCode === "number" ? ev.keyCode : 0;
  if (keyCode > 0 && keyCode < 255) return keyCode;
  return 0;
}
