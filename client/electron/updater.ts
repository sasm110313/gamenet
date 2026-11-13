import { app } from "electron";
import fs from "node:fs";
import path from "node:path";
import https from "node:https";
import http from "node:http";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { Transform } from "node:stream";
import { pipeline } from "node:stream/promises";

export interface UpdateOptions {
  version: string;
  url: string;
  sha256?: string;
  installerUrl?: string;
  hubHost?: string;
  hubPort?: number;
  onProgress?: (progress: number, message: string) => void;
  onError?: (err: Error) => void;
  onComplete?: () => void;
}

let isUpdating = false;

export function isUpdateInProgress(): boolean {
  return isUpdating;
}

export async function performClientUpdate(options: UpdateOptions): Promise<boolean> {
  const currentVersion = app.getVersion();
  if (isUpdating || options.version === currentVersion) return false;
  isUpdating = true;
  let deadline: NodeJS.Timeout | undefined;
  let req: http.ClientRequest | undefined;
  let targetFilePath = "";
  try {
    const tempDir = path.join(app.getPath("temp"), "gamenet_update");
    fs.mkdirSync(tempDir, { recursive: true });
    const base = `https://${options.hubHost || "127.0.0.1"}:${options.hubPort || 19443}`;
    const url = new URL(options.url, base);
    const isInstaller = url.pathname.endsWith(".exe");
    targetFilePath = path.join(tempDir, isInstaller ? "GameNet-Setup.exe" : "update_package.bin");
    options.onProgress?.(0, `شروع دریافت نسخه ${options.version}...`);
    const httpModule = url.protocol === "https:" ? https : http;
    const res = await new Promise<http.IncomingMessage>((resolve, reject) => {
      req = httpModule.get(url, {
        rejectUnauthorized: false,
        headers: { "User-Agent": `GameNet-Client/${currentVersion}` },
      }, resolve);
      req.once("error", reject);
      req.setTimeout(15_000, () => req?.destroy(new Error("دریافت داده متوقف شد")));
      deadline = setTimeout(() => req?.destroy(new Error("مهلت دانلود پایان یافت")), 120_000);
    });
    if (res.statusCode !== 200) {
      res.destroy();
      throw new Error(`دریافت فایل بروزرسانی با خطا مواجه شد (کد ${res.statusCode})`);
    }
    const totalBytes = Number(res.headers["content-length"] || 0);
    let receivedBytes = 0;
    const hash = crypto.createHash("sha256");
    const hashingStream = new Transform({
      transform(chunk: Buffer, _encoding, done) {
        try {
          receivedBytes += chunk.length;
          hash.update(chunk);
          const percent = totalBytes > 0 ? Math.min(100, Math.round(receivedBytes / totalBytes * 100)) : 50;
          options.onProgress?.(percent, `در حال دریافت نسخه ${options.version} (${percent}٪)...`);
          done(null, chunk);
        } catch (error) {
          done(error as Error);
        }
      },
    });
    await pipeline(res, hashingStream, fs.createWriteStream(targetFilePath));
    if (options.sha256?.trim() && hash.digest("hex") !== options.sha256.trim().toLowerCase()) {
      throw new Error("کد اعتبارسنجی (هش) فایل دانلود شده با سرور تطابق ندارد.");
    }
    if (deadline) clearTimeout(deadline);
    req?.setTimeout(0);
    options.onProgress?.(100, "دانلود تکمیل شد. در حال اعمال بروزرسانی و راه‌اندازی مجدد...");
    options.onComplete?.();
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
    applyAndRestart(tempDir, targetFilePath, isInstaller);
    return true;
  } catch (error) {
    try { if (targetFilePath) fs.unlinkSync(targetFilePath); } catch {}
    options.onError?.(error instanceof Error ? error : new Error(String(error)));
    throw error;
  } finally {
    if (deadline) clearTimeout(deadline);
    req?.destroy();
    isUpdating = false;
  }
}

function applyAndRestart(tempDir: string, updateFilePath: string, isInstaller: boolean): void {
  const installDir = app.isPackaged ? path.dirname(process.resourcesPath) : process.cwd();
  const exePath = app.getPath("exe");
  const asarDest = path.join(installDir, "resources", "app.asar");
  const setupExePath = path.join(tempDir, "GameNet-Setup.exe");

  if (process.platform === "win32") {
    const batPath = path.join(tempDir, "apply_update.bat");
    const logPath = path.join(tempDir, "update.log");
    const batLines = [
      "@echo off",
      "title GameNet Auto-Updater",
      `echo [%date% %time%] Starting GameNet update... > "${logPath}"`,
      "ping -n 3 127.0.0.1 >nul",
      "taskkill /f /im GameNet.exe >nul 2>&1",
      "ping -n 2 127.0.0.1 >nul",
      "",
      `if exist "${updateFilePath}" if /i not "${updateFilePath}"=="${setupExePath}" (`,
      `    echo Copying updated app.asar... >> "${logPath}"`,
      "    for /L %%i in (1,1,6) do (",
      `        copy /y "${updateFilePath}" "${asarDest}" >> "${logPath}" 2>&1`,
      "        if not errorlevel 1 goto copy_ok",
      "        ping -n 2 127.0.0.1 >nul",
      "    )",
      `    echo Standard copy failed; elevation is required. >> "${logPath}"`,
      ")",
      ":copy_ok",
      "",
      `if exist "${setupExePath}" (`,
      `    echo Running installer >> "${logPath}"`,
      `    "${setupExePath}" /S >> "${logPath}" 2>&1`,
      `    if errorlevel 1 echo Silent install was refused; a manual installer run is required. >> "${logPath}"`,
      ")",
      "",
      "ping -n 10 127.0.0.1 >nul",
      `echo Starting "${exePath}" >> "${logPath}"`,
      `start "" "${exePath}"`,
      "exit",
      "",
    ];
    fs.writeFileSync(batPath, batLines.join("\r\n"), "utf8");

    const child = spawn("cmd.exe", ["/c", batPath], {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
      shell: false,
    });
    child.unref();
    app.exit(0);
  } else {
    // Linux/macOS fallback
    if (!isInstaller) {
      try {
        const dest = path.join(process.resourcesPath, "app.asar");
        fs.copyFileSync(updateFilePath, dest);
      } catch {}
    }
    app.relaunch();
    app.exit(0);
  }
}
