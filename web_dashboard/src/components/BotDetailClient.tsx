"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Pause, Play } from "lucide-react";
import type { BotState } from "../lib/types";
import { EquityChart } from "./EquityChart";

export function BotDetailClient({ initial }: { initial: BotState }) {
  const [bot, setBot] = useState(initial);
  const [paper, setPaper] = useState(initial.status === "PAPER");
  const [running, setRunning] = useState(initial.status !== "IDLE");
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const res = await fetch(`/api/bots?id=${bot.bot_id}`, { cache: "no-store" });
        const data = await res.json();
        if (data.ok && data.bot) setBot(data.bot);
      } catch {
        /* ignore */
      }
    }, 5000);
    return () => clearInterval(id);
  }, [bot.bot_id]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-300">
        ← All bots
      </Link>
      <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold text-zinc-50">{bot.bot_name}</h1>
          <p className="mt-1 text-sm text-zinc-400">
            {bot.asset_class} · {bot.timeframe}
            {bot.acceptance_note ? ` · ${bot.acceptance_note}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setRunning(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-500/15 px-3 py-2 text-sm text-emerald-300 ring-1 ring-emerald-500/30"
          >
            <Play size={14} /> Start
          </button>
          <button
            type="button"
            onClick={() => setRunning(false)}
            className="inline-flex items-center gap-2 rounded-xl bg-zinc-800 px-3 py-2 text-sm text-zinc-200 ring-1 ring-zinc-700"
          >
            <Pause size={14} /> Pause
          </button>
          <button
            type="button"
            onClick={() => setPaper((v) => !v)}
            className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm ring-1 ${
              paper
                ? "bg-sky-500/15 text-sky-300 ring-sky-500/30"
                : "bg-zinc-800 text-zinc-300 ring-zinc-700"
            }`}
          >
            <Activity size={14} /> Paper Mode {paper ? "On" : "Off"}
          </button>
          <button
            type="button"
            onClick={() => setDrawerOpen((v) => !v)}
            className="rounded-xl bg-zinc-800 px-3 py-2 text-sm text-zinc-200 ring-1 ring-zinc-700"
          >
            Parameters
          </button>
        </div>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Sharpe" value={bot.sharpe_ratio.toFixed(2)} />
        <Metric label="Profit factor" value={(bot.profit_factor ?? 0).toFixed(2)} />
        <Metric label="Trades" value={String(bot.trade_count ?? 0)} />
        <Metric
          label="Status"
          value={`${running ? (paper ? "PAPER" : "ACTIVE") : "IDLE"}`}
        />
      </div>

      <div className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4">
        <div className="mb-2 text-sm font-medium text-zinc-200">Equity curve</div>
        <EquityChart data={bot.equity_curve} height={300} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4">
          <div className="mb-3 text-sm font-medium text-zinc-200">Recent trades</div>
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-zinc-500">
                <tr>
                  <th className="py-2">When</th>
                  <th>Side/Type</th>
                  <th>Symbol</th>
                  <th className="text-right">PnL</th>
                </tr>
              </thead>
              <tbody>
                {(bot.recent_trades || []).slice(0, 15).map((t, i) => (
                  <tr key={i} className="border-t border-zinc-800 text-zinc-300">
                    <td className="py-2 pr-2 text-xs text-zinc-500">
                      {(t.exit_time || t.entry_time || t.time || "").toString().slice(0, 19)}
                    </td>
                    <td>{t.side || t.type || t.reason || "—"}</td>
                    <td>{t.symbol || "—"}</td>
                    <td
                      className={`text-right ${
                        Number(t.pnl_usdt || 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {t.pnl_usdt == null ? "—" : Number(t.pnl_usdt).toFixed(2)}
                    </td>
                  </tr>
                ))}
                {!bot.recent_trades?.length && (
                  <tr>
                    <td colSpan={4} className="py-6 text-center text-zinc-500">
                      No trades yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs text-zinc-300">
          <div className="mb-3 font-sans text-sm font-medium text-zinc-200">Live logs</div>
          <div className="max-h-80 space-y-2 overflow-auto">
            {(bot.logs || []).slice(-30).map((line, i) => (
              <div key={i}>
                <span className="text-zinc-600">
                  {(line.time || "").toString().slice(11, 19)}{" "}
                </span>
                <span className="text-amber-400/80">{line.level || "INFO"}</span>{" "}
                {line.message}
              </div>
            ))}
            {!bot.logs?.length && <div className="text-zinc-600">No log lines</div>}
          </div>
        </div>
      </div>

      {drawerOpen && (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-zinc-800 bg-zinc-950 p-6 shadow-2xl">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium text-zinc-50">Parameters</h2>
            <button
              type="button"
              className="text-sm text-zinc-400"
              onClick={() => setDrawerOpen(false)}
            >
              Close
            </button>
          </div>
          <dl className="space-y-3 text-sm">
            <Row k="Bot ID" v={bot.bot_id} />
            <Row k="Timeframe" v={bot.timeframe} />
            <Row k="Asset" v={bot.asset_class} />
            <Row k="Updated" v={bot.updated_at} />
            <Row
              k="Position"
              v={
                bot.current_position
                  ? JSON.stringify(bot.current_position)
                  : "flat"
              }
            />
            <Row k="Source" v={bot.mock ? "mock fallback" : "live JSON"} />
          </dl>
          <p className="mt-6 text-xs text-zinc-500">
            Start / Pause / Paper Mode update the dashboard session only. Wire
            them to each bot controller when you connect live control APIs.
          </p>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 px-4 py-4">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-xl font-medium text-zinc-50">{value}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-zinc-900 py-2">
      <dt className="text-zinc-500">{k}</dt>
      <dd className="break-all text-right text-zinc-200">{v}</dd>
    </div>
  );
}
