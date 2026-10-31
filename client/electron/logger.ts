import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

/** Minimal file log for Windows machines with no console. Secrets are never logged. */
let logFile = "";

export function initLogging(): void {
  try {
    const directory = path.join(app.getPath("userData"), "logs");
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    logFile = path.join(directory, "client.log");
    if (fs.existsSync(logFile) && fs.statSync(logFile).size > 1_000_000) {
      fs.renameSync(logFile, `${logFile}.1`);
    }
  } catch {
    logFile = "";
  }
}

export function log(level: "info" | "warn" | "error", message: string): void {
  const line = `${new Date().toISOString()} ${level.toUpperCase()} ${message}\n`;
  if (level === "error") console.error(line.trimEnd());
  else console.log(line.trimEnd());
  if (!logFile) return;
  try {
    fs.appendFileSync(logFile, line, { encoding: "utf8", mode: 0o600 });
  } catch {
    // A full disk must not take the client down.
  }
}
