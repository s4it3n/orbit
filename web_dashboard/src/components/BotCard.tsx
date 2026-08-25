"use client";

import Link from "next/link";
import { Activity, Bitcoin, Landmark, LineChart } from "lucide-react";
import type { BotState } from "../lib/types";
import { EquityChart } from "./EquityChart";

const ICONS = {
  orbit: Bitcoin,
  gold: Landmark,
  mnq: LineChart,
} as const;

function statusClass(status: string) {
  if (status === "ACTIVE") return "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30";
  if (status === "PAPER") return "bg-sky-500/15 text-sky-300 ring-sky-500/30";
  return "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30";
}

function fmtPct(n: number) {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

export function BotCard({ bot }: { bot: BotState }) {
  const Icon = ICONS[bot.bot_id as keyof typeof ICONS] || Activity;
  return (
    <Link
      href={`/bot/${bot.bot_id}`}
      className="group block rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5 transition hover:border-zinc-600 hover:bg-zinc-900"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-zinc-800 p-2.5 text-zinc-200">
            <Icon size={18} />
          </div>
          <div>
            <div className="font-medium text-zinc-50">{bot.bot_name}</div>
            <div className="text-xs text-zinc-500">
              {bot.asset_class} · {bot.timeframe}
              {bot.mock ? " · mock" : ""}
            </div>
          </div>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide ring-1 ${statusClass(bot.status)}`}
        >
          {bot.status}
        </span>
      </div>
      <div className="mb-3 grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">Return</div>
          <div className={bot.total_return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}>
            {fmtPct(bot.total_return_pct)}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">Win rate</div>
          <div className="text-zinc-100">{bot.win_rate_pct.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">Max DD</div>
          <div className="text-rose-300">{bot.max_drawdown_pct.toFixed(1)}%</div>
        </div>
      </div>
      <div className="h-16 overflow-hidden rounded-lg bg-zinc-950/60">
        <EquityChart data={bot.equity_curve.slice(-40)} height={64} compact />
      </div>
    </Link>
  );
}
