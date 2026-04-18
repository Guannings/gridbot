# **Grid Trading Bot — Paper & Live Trading on OKX**

Author: [PARVAUX]

Date: 18 April 2026

Tech Stack: Python, ccxt, OKX API

# **IMPORTANT LEGAL DISCLAIMER AND RISK DISCLOSURE**

**1. GENERAL DISCLAIMER**

The content, signals, data, and software provided herein (collectively, the "System") are for informational, educational, and research purposes only. The Creator and associated contributors (the "Authors") are not registered financial advisors, broker-dealers, or investment professionals. Nothing in this System constitutes personalized investment advice, a recommendation to buy, sell, or hold any security or cryptocurrency, or a solicitation of any offer to buy or sell any financial instruments.

**2. NO FIDUCIARY DUTY**

You acknowledge that no fiduciary relationship exists between you and the Authors. All investment decisions are made solely by you at your own discretion and risk. You agree to consult with a qualified, licensed financial advisor or tax professional before making any financial decisions based on the outputs of this System.

**3. RISK OF LOSS (CRYPTOCURRENCY)**

Trading in cryptocurrency markets, particularly **Bitcoin (BTC)**, involves a high degree of risk and may not be suitable for all investors.

* **Volatility Risk:** Bitcoin is extremely volatile and can experience 50%+ drawdowns within weeks. You may sustain a total loss of your initial invested capital.

* **Grid Trading Risk:** Grid trading strategies profit from sideways/ranging markets. During strong directional trends, grid bots will accumulate losing positions (buying into a crash or selling into a rally). Historical backtests do not guarantee future performance.

* **Regulatory Risk:** Cryptocurrency regulations vary by jurisdiction and may change without notice, potentially affecting your ability to trade, hold, or withdraw BTC.

* **Custodial Risk:** Digital assets may be lost due to exchange failures, hacking incidents, or loss of private keys.

* **Leverage Risk:** If leverage is used, losses are amplified proportionally. A leveraged grid bot can be liquidated during extreme market moves.

**4. HYPOTHETICAL PERFORMANCE DISCLOSURE**

The results presented in this project, including backtests and historical simulations, are hypothetical. Hypothetical or simulated performance results have certain inherent limitations. Unlike an actual performance record, simulated results do not represent actual trading. Also, since the trades have not actually been executed, the results may have under- or over-compensated for the impact, if any, of certain market factors, such as lack of liquidity. No representation is being made that any account will or is likely to achieve profits or losses similar to those shown. Past performance is not necessarily indicative of future results.

**5. ALGORITHMIC AND TECHNICAL RISKS**

The System relies on real-time price data from OKX via the ccxt library and third-party APIs.

* The bot relies on external API data which may be delayed, inaccurate, or unavailable. The Authors do not guarantee the accuracy, timeliness, or completeness of the data.

* The code is provided "AS IS" without warranty of any kind. There may be errors, bugs, or glitches in the logic that could result in incorrect orders or financial loss.

* Network outages, exchange downtime, or API rate limits may cause the bot to miss trades or behave unexpectedly.

**6. LIMITATION OF LIABILITY**

**IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SYSTEM, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.**

=============================================================================

## **1. What is Grid Trading?**

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

## **2. Backtest Results**

Backtested on BTC/USDT using **realistic high/low candle fills** (not just close prices).

**Best config: 10 grids, ±5% range, geometric spacing**

| Period | Grid Return | Buy & Hold | Grid vs B&H |
|--------|------------|------------|-------------|
| 30d (choppy) | +4.6% | +0.8% | **+3.8%** |
| 60d (mixed) | +16.1% | +7.6% | **+8.5%** |
| 90d (downtrend) | -4.3% | -22.8% | **+18.5%** |

Annualized: **~57% APR** in choppy markets. Grid consistently outperforms buy & hold.

## **3. Prerequisites**

**a. Python 3.10+**

**b. ccxt library**
```bash
pip install ccxt
```

**c. OKX Account** (for live trading only — paper trading needs no account)

## **4. Quick Start**

```bash
# Clone the repo
git clone https://github.com/Guannings/gridbot.git
cd gridbot

# Install dependencies
pip install -r requirements.txt

# Run the bot (paper trading by default)
python grid_bot.py
```

The interactive setup will walk you through: pair selection, grid range, number of grids, spacing mode, investment amount, and safety settings. After setup, you can **run a backtest with your exact config** before starting — pick any period (30, 90, 180, 365 days) to see how your settings would have performed historically.

## **5. Backtesting**

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

## **6. Live Trading Setup**

**API keys are read from environment variables only — never stored on disk.**

```bash
export OKX_API_KEY="your-key"
export OKX_API_SECRET="your-secret"
export OKX_PASSPHRASE="your-passphrase"
python grid_bot.py
```

The bot will detect the API keys and ask for **double confirmation** before enabling live mode.

## **7. Running 24/7**

```bash
# Using tmux (recommended)
tmux new -s gridbot
python grid_bot.py
# Ctrl+B, D to detach
# tmux attach -t gridbot to come back
```

## **8. Dashboard**

Open `grid_bot_dashboard.html` in a browser and load `grid_bot_state.json` to see live metrics. Supports auto-refresh on Chrome/Edge.

## **9. Features**

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

## **10. Regime Detection — Why We Don't Have It**

We tested 3 approaches to auto-adjust the grid when price trends out of range. All were backtested across 90, 180, and 365-day periods on BTC/USDT. All performed worse than a static grid.

**Approaches tested:**

| Approach | Mechanism | Result |
|----------|-----------|--------|
| Full rebalance | Sell all crypto, recenter grid around current price | -15% vs +1% static (90d) |
| Upward-only rebalance | Same as above but only shift upward | -15% vs +3% static (365d) |
| Trailing grid | Shift one level at a time (drop bottom, add top) | -20% vs +1% static (90d) |

**Detection used:** ATR (14-period) + Bollinger Band width (20-period) on 1h candles to classify RANGING vs TRENDING.

**Why they all failed:** BTC dropped from ~$116K to ~$60K over the past 6 months. Any dynamic adjustment that moved the grid upward during rallies bought crypto at high prices. When the crash came, those positions got destroyed. The static grid's "do nothing when out of range" behavior accidentally protected capital by avoiding buys at the top.

**Takeaway:** Grid bots are fundamentally a ranging strategy. The grid going idle when price leaves the range is a feature, not a bug. Manual range adjustment when price stabilizes at a new level is safer than algorithmic auto-adjustment.

> Detailed backtest data in `SESSION.md`.

## **11. Project Structure**

```
gridbot/
├── grid_bot.py              # Main bot (paper + live)
├── backtest.py              # Backtester with parameter sweep
├── grid_bot_dashboard.html  # Browser dashboard
├── requirements.txt         # Python dependencies
├── config.json              # Saved settings (auto-created, gitignored)
└── grid_bot_state.json      # Live state for dashboard (auto-created, gitignored)
```
