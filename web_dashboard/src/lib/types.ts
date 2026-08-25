export type BotStatus = "ACTIVE" | "PAPER" | "IDLE";

export type EquityPoint = {
  timestamp: string;
  equity: number;
};

export type TradeRow = {
  time?: string;
  entry_time?: string;
  exit_time?: string;
  type?: string;
  detail?: string;
  symbol?: string;
  side?: string;
  entry_price?: number;
  exit_price?: number;
  quantity?: number;
  pnl_usdt?: number;
  reason?: string;
};

export type BotState = {
  bot_id: string;
  bot_name: string;
  asset_class: string;
  timeframe: string;
  status: BotStatus;
  updated_at: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor?: number;
  trade_count?: number;
  current_position: Record<string, unknown> | null;
  equity_usdt?: number | null;
  equity_curve: EquityPoint[];
  recent_trades: TradeRow[];
  logs?: Array<{ time?: string; level?: string; message?: string }>;
  regime?: Record<string, unknown>;
  accepted?: boolean;
  acceptance_note?: string;
  mock?: boolean;
};

export type PortfolioSummary = {
  combined_equity: number;
  monthly_pnl_pct: number;
  global_max_dd_pct: number;
  system_health: "healthy" | "degraded" | "offline";
  bots: BotState[];
};
