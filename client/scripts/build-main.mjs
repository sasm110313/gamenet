import { build } from "esbuild";

// Main and preload are bundled to CommonJS for Electron 22 (Node 16). `ws` is
// bundled too, so the installed app is only asar + assets with no node_modules
// resolution surprises on Windows 7.
await build({
  entryPoints: ["electron/main.ts", "electron/preload.ts"],
  outdir: "dist-electron",
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node16",
  external: ["electron"],
  sourcemap: false,
  minify: false,
  logLevel: "info",
});
