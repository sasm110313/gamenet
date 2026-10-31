import { rm } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

// Dev convenience only: forget the paired device so the pairing screen returns.
const name = process.platform === "win32" ? "GameNet" : "gamenet-client";
const base =
  process.platform === "win32"
    ? join(process.env.APPDATA || homedir(), name)
    : process.platform === "darwin"
      ? join(homedir(), "Library", "Application Support", name)
      : join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), name);
const target = join(base, "client-state.json");
await rm(target, { force: true });
console.log(`removed ${target}`);
