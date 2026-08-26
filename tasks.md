# Orbit Optimization Tasks

- [x] Run local walk-forward optimization on Gold 1H Donchian parameters (lengths 10-30, entry offset 0.1-0.4 ATR) and verify Sharpe > 0.60.
- [ ] Implement ATR trailing stop variations (2.0 to 3.5 ATR) for Gold 1H to reduce max drawdown below -7%.
- [ ] Backtest dynamic CET Opening Range time windows (15:30-15:45 vs 15:30-16:00) for MNQ 15m locally.
- [ ] Add volume filter (1.25x SMA) to MNQ 15m ORB entries and verify win rate improvement.
- [ ] Run full 3-bot local portfolio correlation check to confirm smooth overall equity curve.