import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientDir = path.resolve(__dirname, "..");
const stagingDir = path.join(clientDir, ".asar_staging");
const outputDir = path.join(clientDir, "..", "backend", "static", "updates");
const asarBin = path.join(clientDir, "node_modules", ".bin", "asar");

fs.rmSync(stagingDir, { recursive: true, force: true });
fs.mkdirSync(stagingDir, { recursive: true });
fs.mkdirSync(outputDir, { recursive: true });

fs.copyFileSync(path.join(clientDir, "package.json"), path.join(stagingDir, "package.json"));
fs.cpSync(path.join(clientDir, "dist"), path.join(stagingDir, "dist"), { recursive: true });
fs.cpSync(path.join(clientDir, "dist-electron"), path.join(stagingDir, "dist-electron"), { recursive: true });

if (fs.existsSync(path.join(clientDir, "node_modules", "ws"))) {
  const nm = path.join(stagingDir, "node_modules");
  fs.mkdirSync(nm, { recursive: true });
  fs.cpSync(path.join(clientDir, "node_modules", "ws"), path.join(nm, "ws"), { recursive: true });
}

const targetAsar = path.join(outputDir, "app.asar");
execSync(`"${asarBin}" pack "${stagingDir}" "${targetAsar}"`, { stdio: "inherit" });

fs.rmSync(stagingDir, { recursive: true, force: true });
console.log(`[Asar Pack] Successfully created: ${targetAsar}`);
