# **Grid Trading Bot — Paper & Live Trading on OKX**

Author: [PEHC]

Date: April 2026

Tech Stack: Python, ccxt, OKX API

## **1. Risk Disclaimer**

This bot is for **educational and research purposes**. Trading cryptocurrency involves significant risk of loss. Grid trading can and will lose money during strong trending markets. **Never invest more than you can afford to lose.** The author is not a financial advisor. All trading decisions are made at your own risk.

## **2. What is Grid Trading?**

Grid trading profits from **price oscillation within a defined range**. Instead of predicting direction, it systematically buys low and sells high across a grid of price levels.

```
$77,000 ─── SELL
$76,000 ─── SELL
$75,000 ─── SELL
$74,000 ─── ← current price
$73,000 ─── BUY
$72,000 ─── BUY
$71,000 ─── BUY
$70,000 ─── BUY
```

**How it works:**
1. Define a price range and number of grid levels
2. Buy orders placed below current price, sell orders above
3. Price drops to a buy level → bot buys, places sell one level up
4. Price rises to a sell level → bot sells, places buy one level down
5. Each buy→sell cycle = profit (grid spread minus fees)

## **3. Backtest Results**

Backtested on BTC/USDT using **realistic high/low candle fills** (not just close prices).

**Best config: 10 grids, ±5% range, geometric spacing**

| Period | Grid Return | Buy & Hold | Grid vs B&H |
|--------|------------|------------|-------------|
| 30d (choppy) | +4.6% | +0.8% | **+3.8%** |
| 60d (mixed) | +16.1% | +7.6% | **+8.5%** |
| 90d (downtrend) | -4.3% | -22.8% | **+18.5%** |

Annualized: **~57% APR** in choppy markets. Grid consistently outperforms buy & hold.

## **4. Prerequisites**

**a. Python 3.10+**

**b. ccxt library**
```bash
pip install ccxt
```

**c. OKX Account** (for live trading only — paper trading needs no account)

## **5. Quick Start**

```bash
# Clone the repo
git clone https://github.com/Guannings/gridbot.git
cd gridbot

# Install dependencies
pip install -r requirements.txt

# Run the bot (paper trading by default)
python grid_bot.py
```

The interactive setup will walk you through: pair selection, grid range, number of grids, spacing mode, investment amount, and safety settings.

## **6. Backtesting**

```bash
# Single backtest with defaults
python backtest.py --days 30

# Custom backtest
python backtest.py --grids 10 --range-pct 5 --geometric --days 60

# Parameter sweep — finds optimal settings automatically
python backtest.py --sweep --days 30

# Test on ETH
python backtest.py --symbol ETH/USDT --sweep --days 30
```

## **7. Live Trading Setup**

**API keys are read from environment variables only — never stored on disk.**

```bash
export OKX_API_KEY="your-key"
export OKX_API_SECRET="your-secret"
export OKX_PASSPHRASE="your-passphrase"
python grid_bot.py
```

The bot will detect the API keys and ask for **double confirmation** before enabling live mode.

## **8. Running 24/7**

```bash
# Using tmux (recommended)
tmux new -s gridbot
python grid_bot.py
# Ctrl+B, D to detach
# tmux attach -t gridbot to come back
```

## **9. Dashboard**

Open `grid_bot_dashboard.html` in a browser and load `grid_bot_state.json` to see live metrics. Supports auto-refresh on Chrome/Edge.

## **10. Features**

| Feature | Description |
|---------|-------------|
| Paper trading | Default mode — simulates with real OKX prices |
| Live trading | Real limit orders on OKX (opt-in, double confirmation) |
| Geometric spacing | Percentage-based grid levels — better for crypto |
| Backtester | High/low candle simulation, parameter sweep |
| Max drawdown stop | Auto-stops if portfolio drops X% from peak |
| Stop-loss | Hard price floor — sells everything and exits |
| Take-profit | Hard price ceiling — sells everything and exits |
| Config persistence | Saves to config.json, API keys stay in env vars |
| Graceful shutdown | Ctrl+C cancels all live orders before exiting |

## **11. Project Structure**

```
gridbot/
├── grid_bot.py              # Main bot (paper + live)
├── backtest.py              # Backtester with parameter sweep
├── grid_bot_dashboard.html  # Browser dashboard
├── requirements.txt         # Python dependencies
├── config.json              # Saved settings (auto-created, gitignored)
├── grid_bot_state.json      # Live state for dashboard (auto-created, gitignored)
└── SESSION.md               # Development session notes
```
