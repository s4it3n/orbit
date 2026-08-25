import { existsSync, readFileSync } from "fs";
import path from "path";
import { MOCK_BOTS } from "./mocks";
import type { BotState, PortfolioSummary } from "./types";

const FILES: Record<string, string> = {
  orbit: "orbit_state.json",
  gold: "gold_state.json",
  mnq: "mnq_state.json",
};

function repoRoot(): string {
  // web_dashboard/ -> repo root
  return path.resolve(process.cwd(), "..");
}

function readBot(id: string): BotState {
  const fallback = MOCK_BOTS.find((b) => b.bot_id === id) ?? MOCK_BOTS[0];
  const file = FILES[id];
  if (!file) return { ...fallback, mock: true };
  const full = path.join(repoRoot(), file);
  if (!existsSync(full)) return { ...fallback, mock: true };
  try {
    const raw = JSON.parse(readFileSync(full, "utf8")) as BotState;
    return {
      ...fallback,
      ...raw,
      bot_id: id,
      mock: false,
      equity_curve: raw.equity_curve?.length ? raw.equity_curve : fallback.equity_curve,
      recent_trades: raw.recent_trades ?? [],
      logs: raw.logs ?? fallback.logs,
    };
  } catch {
    return { ...fallback, mock: true };
  }
}

export function loadAllBots(): PortfolioSummary {
  const bots = ["orbit", "gold", "mnq"].map(readBot);
  const combined = bots.reduce((sum, b) => sum + Number(b.equity_usdt || 0), 0);
  const globalDd = Math.min(...bots.map((b) => Number(b.max_drawdown_pct || 0)));
  const monthly = bots.reduce((sum, b) => sum + Number(b.total_return_pct || 0), 0) / bots.length;
  const liveCount = bots.filter((b) => !b.mock).length;
  const health =
    liveCount === 3 ? "healthy" : liveCount > 0 ? "degraded" : "offline";
  return {
    combined_equity: combined,
    monthly_pnl_pct: Number(monthly.toFixed(2)),
    global_max_dd_pct: globalDd,
    system_health: health,
    bots,
  };
}

export function loadBot(id: string): BotState | null {
  if (!FILES[id]) return null;
  return readBot(id);
}
