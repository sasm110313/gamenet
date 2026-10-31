import { app, safeStorage } from "electron";
import fs from "node:fs";
import path from "node:path";
import type { PairingTarget } from "./pinned-agent";

/**
 * On-disk client state. Only the device token is secret. On Windows it is
 * sealed with DPAPI via Electron safeStorage; if DPAPI is unavailable the app
 * refuses to persist a token rather than writing it in plaintext.
 *
 * The file also holds the pinned certificate fingerprint and the edge address,
 * so a restart reconnects without a human at the machine.
 */

export interface StoredState {
  version: 1;
  pairing: PairingTarget;
  deviceId: string;
  deviceName: string;
  hubName: string;
  tokenSealed: string;
  savedAt: string;
}

const STATE_VERSION = 1;

function statePath(): string {
  return path.join(app.getPath("userData"), "client-state.json");
}

function ensureDirectory(): void {
  fs.mkdirSync(path.dirname(statePath()), { recursive: true, mode: 0o700 });
}

function isPairingTarget(value: unknown): value is PairingTarget {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.host === "string" &&
    candidate.host.length > 0 &&
    candidate.host.length <= 255 &&
    Number.isInteger(candidate.port) &&
    (candidate.port as number) > 0 &&
    (candidate.port as number) < 65_536 &&
    typeof candidate.fingerprint === "string" &&
    /^[0-9A-F]{64}$/.test(candidate.fingerprint)
  );
}

export class StateStore {
  load(): StoredState | null {
    try {
      const raw = fs.readFileSync(statePath(), "utf8");
      const parsed = JSON.parse(raw) as Partial<StoredState>;
      if (
        parsed.version !== STATE_VERSION ||
        !isPairingTarget(parsed.pairing) ||
        typeof parsed.deviceId !== "string" ||
        !parsed.deviceId ||
        typeof parsed.tokenSealed !== "string" ||
        !parsed.tokenSealed
      ) {
        return null;
      }
      return {
        version: STATE_VERSION,
        pairing: parsed.pairing,
        deviceId: parsed.deviceId,
        deviceName: typeof parsed.deviceName === "string" ? parsed.deviceName : "",
        hubName: typeof parsed.hubName === "string" ? parsed.hubName : "",
        tokenSealed: parsed.tokenSealed,
        savedAt: typeof parsed.savedAt === "string" ? parsed.savedAt : "",
      };
    } catch {
      return null;
    }
  }

  save(state: Omit<StoredState, "version" | "savedAt">): StoredState {
    ensureDirectory();
    const full: StoredState = {
      version: STATE_VERSION,
      ...state,
      savedAt: new Date().toISOString(),
    };
    const temporary = `${statePath()}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(full, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
    fs.chmodSync(temporary, 0o600);
    fs.renameSync(temporary, statePath());
    return full;
  }

  clear(): void {
    try {
      fs.rmSync(statePath(), { force: true });
    } catch {
      // Losing the file is not worth crashing the kiosk over.
    }
  }

  sealToken(token: string): string {
    if (safeStorage.isEncryptionAvailable()) {
      return `enc:${safeStorage.encryptString(token).toString("base64")}`;
    }
    if (process.platform === "win32") {
      throw new Error(
        "رمزنگاری ویندوز (DPAPI) در دسترس نیست؛ ذخیره کلید دستگاه در متن ساده مجاز نیست",
      );
    }
    // Linux CI/dev only. Production Windows goes through DPAPI above.
    return `plain:${Buffer.from(token, "utf8").toString("base64")}`;
  }

  openToken(stored: StoredState): string | null {
    try {
      if (stored.tokenSealed.startsWith("enc:")) {
        const sealed = Buffer.from(stored.tokenSealed.slice(4), "base64");
        return safeStorage.decryptString(sealed);
      }
      if (stored.tokenSealed.startsWith("plain:") && process.platform !== "win32") {
        return Buffer.from(stored.tokenSealed.slice(6), "base64").toString("utf8");
      }
      return null;
    } catch {
      return null;
    }
  }
}
