"use client";

import { useEffect, useState } from "react";
import { Radio } from "lucide-react";
import type { BotState, PortfolioSummary } from "../lib/types";
import { BotCard } from "./BotCard";

async function fetchPortfolio(): Promise<PortfolioSummary> {
  const res = await fetch("/api/bots", { cache: "no-store" });
  return (await res.json()) as PortfolioSummary;
}

function healthTone(h: string) {
  if (h === "healthy") return "text-emerald-400";
  if (h === "degraded") return "text-amber-300";
  return "text-rose-400";
}

export function DashboardHome({ initial }: { initial: PortfolioSummary }) {
  const [data, setData] = useState(initial);

  useEffect(() => {
    const id = setInterval(async () => {
      try {
        setData(await fetchPortfolio());
      } catch {
        /* keep last good snapshot */
      }
    }, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="mb-1 text-xs uppercase tracking-[0.2em] text-zinc-500">
            Multi-bot desk
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">
            Trading Command
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Orbit · Gold · Nasdaq ORB — live JSON polling every 5s
          </p>
        </div>
        <div className={`flex items-center gap-2 text-sm ${healthTone(data.system_health)}`}>
          <Radio size={16} />
          System {data.system_health}
        </div>
      </header>

      <section className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Combined equity"
          value={`$${Number(data.combined_equity || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        />
        <Stat
          label="Avg return (bots)"
          value={`${data.monthly_pnl_pct >= 0 ? "+" : ""}${data.monthly_pnl_pct.toFixed(1)}%`}
        />
        <Stat label="Global max DD" value={`${data.global_max_dd_pct.toFixed(1)}%`} />
        <Stat
          label="Active bots"
          value={`${data.bots.filter((b) => b.status !== "IDLE").length}/3`}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        {data.bots.map((bot: BotState) => (
          <BotCard key={bot.bot_id} bot={bot} />
        ))}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 px-4 py-4">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-xl font-medium text-zinc-50">{value}</div>
    </div>
  );
}
