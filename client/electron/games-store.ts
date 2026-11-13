import { app } from "electron";
import fs from "node:fs";
import path from "node:path";
import type { GameItem } from "../shared/ipc";

export const DEFAULT_GAMES: GameItem[] = [
  {
    id: "r6s",
    name: "Rainbow Six Siege (رهرو)",
    category: "شوتر تاکتیکال",
    icon: "🛡️",
    executable: "c:\\program files(x86)\\games\\rainbow six siege\\rainbowsix_rahro_native.exe",
    arguments: "",
    workingDir: "c:\\program files(x86)\\games\\rainbow six siege",
    color: "border-sky-500/30 bg-sky-500/[0.06]",
    enabled: true,
  },
  {
    id: "cs16",
    name: "Counter-Strike 1.6",
    category: "شوتر کلاسیک",
    icon: "🎯",
    executable: "c:\\program files(x86)\\games\\counter-strike 1.6\\hl.exe",
    arguments: "-game cstrike",
    workingDir: "c:\\program files(x86)\\games\\counter-strike 1.6",
    color: "border-amber/30 bg-amber/[0.06]",
    enabled: true,
  },
];

function gamesPath(): string {
  try {
    return path.join(app.getPath("userData"), "games.json");
  } catch {
    return path.join(process.cwd(), "games.json");
  }
}

export class GamesStore {
  private cached: GameItem[] | null = null;

  loadGames(): GameItem[] {
    if (this.cached !== null) {
      return this.cached;
    }
    const file = gamesPath();
    try {
      if (fs.existsSync(file)) {
        const raw = fs.readFileSync(file, "utf8");
        const list = JSON.parse(raw);
        if (Array.isArray(list)) {
          this.cached = list;
          return list;
        }
      }
    } catch {
      // Fallback to default
    }
    this.cached = [...DEFAULT_GAMES];
    this.saveGames(this.cached);
    return this.cached;
  }

  saveGames(games: GameItem[]): GameItem[] {
    this.cached = games;
    const file = gamesPath();
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
      const tmp = `${file}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(games, null, 2), "utf8");
      fs.renameSync(tmp, file);
    } catch {
      // Ignore write errors
    }
    return games;
  }

  addGame(game: Omit<GameItem, "id">): GameItem {
    const list = this.loadGames();
    const id = "game_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 6);
    const item: GameItem = {
      ...game,
      id,
      enabled: game.enabled !== undefined ? game.enabled : true,
    };
    list.push(item);
    this.saveGames(list);
    return item;
  }

  updateGame(id: string, patch: Partial<GameItem>): GameItem | null {
    const list = this.loadGames();
    const index = list.findIndex((g) => g.id === id);
    if (index === -1) return null;
    list[index] = { ...list[index], ...patch, id };
    this.saveGames(list);
    return list[index];
  }

  deleteGame(id: string): boolean {
    const list = this.loadGames();
    const filtered = list.filter((g) => g.id !== id);
    if (filtered.length !== list.length) {
      this.saveGames(filtered);
      return true;
    }
    return false;
  }

  resetDefaults(): GameItem[] {
    return this.saveGames([...DEFAULT_GAMES]);
  }
}
