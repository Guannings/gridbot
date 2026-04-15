# Grid Bot Session — 2026-04-15

## What we built
- `grid_bot.py` — Grid trading bot with paper + live mode, safety features, geometric spacing
- `backtest.py` — Backtester using high/low candle fills, parameter sweep
- `grid_bot_dashboard.html` — Light-theme dashboard with auto-refresh

## Backtest findings

### Best config (consistent across 30/60/90 day periods)
- **10 grids, ±5% range, geometric spacing**
- 30d: +4.6% | 60d: +16.1% | 90d: -4.3%
- Annualized: ~57% APR in choppy market
- Always beat buy & hold (even in 90d downtrend: -4.3% vs -22.8%)

### Key insight
- Our +4.7%/month IS the "57% APR" exchange bots advertise — same thing, different label
- More grids (50+) = more cycles but fees eat all profit. 10 grids is the sweet spot.
- Tight range (±5%) needs weekly re-adjustment if price drifts

### Realistic simulation
- Backtester uses high/low within each candle (not just close prices)
- Simulates fills at grid price (like real limit orders)
- Tested up to 200 grids — confirmed 10-20 is optimal

## Leverage decision
- 1.5x is the plan (eventually)
- Good month: +$52 | Bad quarter: -$98
- Liquidation needs 66.7% crash (basically impossible on BTC)
- Start with 1x spot first

## Budget
- Phase 1: $753 (PayPal / DataAnnotation money — don't care about losing it)
- Phase 2: Add ~$930 (30,000 TWD) if Phase 1 works after 1+ month
- Total potential: ~$1,680 USDT

## Current defaults in grid_bot.py
- Investment: $753
- Grids: 10
- Spacing: geometric
- Range: ±5% (auto-suggested during setup)
- Fee rate: 0.1%
- Max drawdown: 10%
- Mode: paper trading (live requires OKX API keys in env vars)

## Plan
1. Paper trade for 2 weeks minimum
2. Look for 5-10 completed cycles, no crashes, P&L matches backtest
3. Go live with $753 at 1x spot
4. After 1 month live, consider adding TWD money
5. After comfortable, consider 1.5x futures leverage

## To run
```bash
# Paper trading
cd ~/gridbot
tmux new -s gridbot
python grid_bot.py
# Ctrl+B, D to detach — tmux attach -t gridbot to come back

# Dashboard
open grid_bot_dashboard.html
# Load grid_bot_state.json

# Backtest anytime
python backtest.py --sweep --days 30
python backtest.py --grids 10 --range-pct 5 --geometric

# Go live later
export OKX_API_KEY="..."
export OKX_API_SECRET="..."
export OKX_PASSPHRASE="..."
python grid_bot.py  # will ask to enable live mode
```
