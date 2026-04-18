# Grid Bot Session — 2026-04-15

## What we built
- `grid_bot.py` — Grid trading bot with paper + live mode, safety features, geometric spacing
- `backtest.py` — Backtester using high/low candle fills, parameter sweep
- `grid_bot_dashboard.html` — Light-theme dashboard with auto-refresh

## Current grid status (2026-04-18)
- Range: $67,000 — $81,000 (set on 2026-04-15)
- BTC price: ~$77,xxx — back in the middle of the range, bot running normally
- 4 completed cycles, $9.05 profit, portfolio value ~$770
- Price pulled back from $78,800 — no longer at risk of breaking upper bound

## Infrastructure change (2026-04-18)
- Moved off iCloud storage — iCloud + git repos don't mix
- Code now lives in GitHub repo: `Guannings/gridbot` (private)
- Other Mac (Cheepers-MacBook-Air): cloned to `~/gridbot-git/`, running in tmux
- This Mac: local copy at `~/gridbot`, connected to same GitHub remote
- State file (`grid_bot_state.json`) preserved from old iCloud location (`~/Desktop/MAC/gridbot/`)

## Backtest findings

### Original config (consistent across 30/60/90 day periods)
- **10 grids, ±5% range, geometric spacing**
- 30d: +4.6% | 60d: +16.1% | 90d: -4.3%
- Annualized: ~57% APR in choppy market
- Always beat buy & hold (even in 90d downtrend: -4.3% vs -22.8%)

### New range candidates (180-day backtest, 2026-04-18)
| Range | Return | vs B&H | Grid Profit | Cycles | Time in Range | Max DD |
|-------|--------|--------|-------------|--------|---------------|--------|
| $75K-$90K | **+0.83%** | +29.39% | $53.04 | 43 | 25.1% | 24.8% |
| $78K-$95K | -2.14% | +26.43% | $61.98 | 46 | 40.5% | 28.3% |
| $80K-$100K | -5.41% | +23.17% | $63.42 | 41 | 43.9% | 30.4% |

- All crushed buy & hold (BTC dropped 28% over 180d)
- $75K-$90K only positive total return; $78K-$95K had most cycles
- Core problem: static ranges only in-range 25-44% of time — BTC moved $60K-$116K

### Key insight
- Our +4.7%/month IS the "57% APR" exchange bots advertise — same thing, different label
- More grids (50+) = more cycles but fees eat all profit. 10 grids is the sweet spot.
- Tight range (±5%) needs weekly re-adjustment if price drifts
- Static grid's "do nothing when out of range" is actually a feature, not a bug (see regime detection results below)

### Realistic simulation
- Backtester uses high/low within each candle (not just close prices)
- Simulates fills at grid price (like real limit orders)
- Tested up to 200 grids — confirmed 10-20 is optimal

## Regime detection experiment (2026-04-18) — FAILED

Attempted to add auto-adjustment so the grid follows price instead of going idle. Tested 3 approaches, all backtested worse than static grid.

### Approach 1: Full rebalance (sell all + recenter grid)
- Used ATR (14-period) + Bollinger Band width (20-period) on 1h candles
- Classified market as RANGING / TRENDING_UP / TRENDING_DOWN
- When trending detected → sell all crypto, recenter grid ±5% around current price
- Tested with cooldowns: 30min, 6h, 12h, 24h, 48h

| Cooldown | 90d Return | Static Return |
|----------|-----------|---------------|
| 30min | -15.2% | **+1.3%** |
| 6h | -19.3% | **+1.3%** |
| 12h | -13.9% | **+1.3%** |
| 24h | -15.0% | **+1.3%** |
| 48h | -12.8% | **+1.3%** |

**Why it failed:** Each rebalance during the downtrend ($95K→$77K) locked in losses. Sold crypto low, re-bought, price dropped again. 24 rebalances in 90 days = death by a thousand cuts.

### Approach 2: Upward-only rebalance (never chase falling price)
- Same detection, but only rebalanced on TRENDING_UP (ignored TRENDING_DOWN)
- Still did full liquidation + recenter

| Period | Static | Regime (up-only) |
|--------|--------|------------------|
| 90d | **+1.1%** | -14.6% |
| 180d | **-2.2%** | -28.9% |
| 365d | **+3.1%** | -15.0% |

**Why it failed:** Shifted grid up during rallies → bought at high prices → crash wiped out gains.

### Approach 3: Trailing grid (shift one level at a time)
- Instead of full liquidation, just shift the grid up one level: drop bottom buy, add new top sell
- Much less aggressive than full rebalance

| Period | Static | Trailing |
|--------|--------|----------|
| 90d | **+1.1%** | -19.6% |
| 180d | **-2.2%** | -37.1% |
| 365d | **+3.1%** | -11.7% |

**Why it failed:** Same fundamental issue — shifting up buys at higher prices, crash punishes you harder. More shifts = more exposure at high prices.

### Conclusion
- **Static grid wins** in the current market (BTC dropped from $116K to $60K over 6 months)
- The grid going idle when out of range is protective — it avoids buying during crashes
- Regime detection would only help in a sustained uptrend with no major crash, which BTC hasn't done in the past year
- **Decision: keep static grid, manually adjust range when needed**

## Next up
- Continue paper trading with static grid
- Monitor and manually reset range when price drifts significantly
- Revisit regime detection if BTC enters a sustained uptrend

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
