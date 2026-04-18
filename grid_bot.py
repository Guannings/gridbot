"""
Grid Trading Bot — Paper & Live Trading
========================================
A spot grid trading bot for OKX with paper trading (default) and live trading modes.
Uses real-time prices from OKX via ccxt. Paper mode simulates orders; live mode places
real limit orders on OKX.

How it works:
1. You define a price range (upper/lower) and number of grids
2. The bot divides the range into grid levels (linear or geometric spacing)
3. At each grid level BELOW current price -> BUY order
4. At each grid level ABOVE current price -> SELL order
5. When price crosses a grid level:
   - If crossing downward (hit a buy) -> fills the buy, places a sell one level up
   - If crossing upward (hit a sell) -> fills the sell, places a buy one level down
6. Each completed buy->sell cycle = profit (the grid spread minus fees)

Safety features (for live trading):
- Max drawdown auto-stop
- Hard stop-loss price
- Take-profit price
- Graceful shutdown cancels all open orders

Config:
- Interactive setup on first run, saved to config.json
- API keys read from environment variables (never stored on disk)
- Set live=True explicitly to trade real money

Usage:
    python grid_bot.py

Author: Built with Claude for learning purposes
"""

import ccxt
import time
import json
import os
import signal
import sys
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

CONFIG_FILE = "config.json"

@dataclass
class GridConfig:
    """All the knobs you can turn."""

    # Which pair to trade
    symbol: str = "BTC/USDT"

    # Grid boundaries
    upper_price: float = 75000.0
    lower_price: float = 65000.0
    num_grids: int = 10

    # Grid spacing mode
    geometric: bool = True

    # How much USDT to allocate
    total_investment: float = 753.0

    # Exchange fee (OKX spot is 0.1% maker/taker for basic tier)
    fee_rate: float = 0.001

    # How often to check price (seconds)
    poll_interval: int = 5

    # ── Live trading ──
    live: bool = False
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""

    # ── Safety features ──
    max_drawdown_pct: float = 10.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0

    # Output files
    log_file: str = "grid_bot_log.json"
    state_file: str = "grid_bot_state.json"


def save_config(config: GridConfig):
    """Save config to config.json (excluding API keys)."""
    d = asdict(config)
    d.pop("api_key", None)
    d.pop("api_secret", None)
    d.pop("passphrase", None)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)
    print(f"  Config saved to {CONFIG_FILE}")


def load_config() -> Optional[GridConfig]:
    """Load config from config.json if it exists."""
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r") as f:
            d = json.load(f)
        d["api_key"] = os.environ.get("OKX_API_KEY", "")
        d["api_secret"] = os.environ.get("OKX_API_SECRET", "")
        d["passphrase"] = os.environ.get("OKX_PASSPHRASE", "")
        return GridConfig(**d)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"  Warning: could not load {CONFIG_FILE}: {e}")
        return None


# ─────────────────────────────────────────────
# Grid math
# ─────────────────────────────────────────────

def build_grid_levels(lower: float, upper: float, num_grids: int, geometric: bool) -> list[float]:
    if geometric:
        ratio = (upper / lower) ** (1.0 / num_grids)
        return [round(lower * (ratio ** i), 2) for i in range(num_grids + 1)]
    else:
        step = (upper - lower) / num_grids
        return [round(lower + i * step, 2) for i in range(num_grids + 1)]


# ─────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────

@dataclass
class GridLevel:
    price: float
    has_buy_order: bool = False
    has_sell_order: bool = False
    holding_crypto: bool = False
    live_order_id: str = ""


@dataclass
class Trade:
    timestamp: str
    side: str
    price: float
    actual_price: float
    amount: float
    cost: float
    fee: float
    grid_level: int


# ─────────────────────────────────────────────
# The Bot
# ─────────────────────────────────────────────

class GridBot:
    def __init__(self, config: GridConfig):
        self.config = config
        self.is_live = config.live and bool(config.api_key)

        exchange_params = {"enableRateLimit": True}
        if self.is_live:
            exchange_params.update({
                "apiKey": config.api_key,
                "secret": config.api_secret,
                "password": config.passphrase,
            })
        self.exchange = ccxt.okx(exchange_params)

        grid_prices = build_grid_levels(
            config.lower_price, config.upper_price, config.num_grids, config.geometric
        )

        if config.geometric:
            self.grid_step = (config.upper_price - config.lower_price) / config.num_grids
            self.grid_ratio = (config.upper_price / config.lower_price) ** (1.0 / config.num_grids)
        else:
            self.grid_step = (config.upper_price - config.lower_price) / config.num_grids
            self.grid_ratio = None

        self.usdt_per_grid = config.total_investment / config.num_grids

        self.grid_levels: list[GridLevel] = []
        for price in grid_prices:
            self.grid_levels.append(GridLevel(price=price))

        self.usdt_balance = config.total_investment
        self.crypto_balance = 0.0
        self.trades: list[Trade] = []
        self.total_fees_paid = 0.0
        self.total_profit = 0.0
        self.num_completed_cycles = 0
        self.peak_portfolio_value = config.total_investment
        self.stopped_reason = ""
        self.last_price: Optional[float] = None
        self.start_time = datetime.now().isoformat()
        self.running = False
        self.live_order_ids: list[str] = []

    def get_current_price(self) -> float:
        ticker = self.exchange.fetch_ticker(self.config.symbol)
        return ticker["last"]

    # ── Live order helpers ──

    def _place_live_buy(self, price: float, amount: float) -> str:
        try:
            order = self.exchange.create_limit_buy_order(self.config.symbol, amount, price)
            order_id = order["id"]
            self.live_order_ids.append(order_id)
            print(f"     [LIVE] Buy order placed: {order_id} | {amount:.6f} @ ${price:,.2f}")
            return order_id
        except Exception as e:
            print(f"     [LIVE] ERROR placing buy order: {e}")
            return ""

    def _place_live_sell(self, price: float, amount: float) -> str:
        try:
            order = self.exchange.create_limit_sell_order(self.config.symbol, amount, price)
            order_id = order["id"]
            self.live_order_ids.append(order_id)
            print(f"     [LIVE] Sell order placed: {order_id} | {amount:.6f} @ ${price:,.2f}")
            return order_id
        except Exception as e:
            print(f"     [LIVE] ERROR placing sell order: {e}")
            return ""

    def _cancel_live_order(self, order_id: str):
        if not order_id:
            return
        try:
            self.exchange.cancel_order(order_id, self.config.symbol)
            if order_id in self.live_order_ids:
                self.live_order_ids.remove(order_id)
            print(f"     [LIVE] Cancelled order: {order_id}")
        except Exception as e:
            print(f"     [LIVE] Error cancelling order {order_id}: {e}")

    def cancel_all_live_orders(self):
        if not self.is_live:
            return
        print(f"\n  [LIVE] Cancelling all open orders...")
        for level in self.grid_levels:
            if level.live_order_id:
                self._cancel_live_order(level.live_order_id)
                level.live_order_id = ""
        remaining = list(self.live_order_ids)
        for oid in remaining:
            self._cancel_live_order(oid)
        try:
            open_orders = self.exchange.fetch_open_orders(self.config.symbol)
            for o in open_orders:
                self._cancel_live_order(o["id"])
        except Exception as e:
            print(f"     [LIVE] Error fetching open orders for cleanup: {e}")
        print(f"  [LIVE] All orders cancelled.")

    def _sell_all_crypto(self, current_price: float):
        if self.crypto_balance <= 0:
            return
        print(f"\n  [SAFETY] Selling all crypto ({self.crypto_balance:.6f}) at market...")
        if self.is_live:
            try:
                order = self.exchange.create_market_sell_order(self.config.symbol, self.crypto_balance)
                revenue = float(order.get("cost", self.crypto_balance * current_price))
                fee = float(order.get("fee", {}).get("cost", revenue * self.config.fee_rate))
                print(f"  [LIVE] Market sell executed: {order['id']}")
            except Exception as e:
                print(f"  [LIVE] ERROR on market sell: {e}")
                revenue = self.crypto_balance * current_price
                fee = revenue * self.config.fee_rate
        else:
            revenue = self.crypto_balance * current_price
            fee = revenue * self.config.fee_rate

        self.usdt_balance += (revenue - fee)
        self.total_fees_paid += fee
        self.crypto_balance = 0.0
        for level in self.grid_levels:
            level.has_buy_order = False
            level.has_sell_order = False
            level.holding_crypto = False
        print(f"  [SAFETY] Sold all. USDT balance: ${self.usdt_balance:,.2f}")

    # ── Safety checks ──

    def _check_safety(self, current_price: float) -> bool:
        if self.config.stop_loss_price > 0 and current_price <= self.config.stop_loss_price:
            self.stopped_reason = f"STOP-LOSS triggered at ${current_price:,.2f} (limit: ${self.config.stop_loss_price:,.2f})"
            print(f"\n  {'!'*50}")
            print(f"  {self.stopped_reason}")
            print(f"  {'!'*50}")
            self.cancel_all_live_orders()
            self._sell_all_crypto(current_price)
            return True

        if self.config.take_profit_price > 0 and current_price >= self.config.take_profit_price:
            self.stopped_reason = f"TAKE-PROFIT triggered at ${current_price:,.2f} (limit: ${self.config.take_profit_price:,.2f})"
            print(f"\n  {'!'*50}")
            print(f"  {self.stopped_reason}")
            print(f"  {'!'*50}")
            self.cancel_all_live_orders()
            self._sell_all_crypto(current_price)
            return True

        crypto_value = self.crypto_balance * current_price
        portfolio_value = self.usdt_balance + crypto_value
        if portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = portfolio_value

        if self.peak_portfolio_value > 0:
            drawdown_pct = (self.peak_portfolio_value - portfolio_value) / self.peak_portfolio_value * 100
            if drawdown_pct >= self.config.max_drawdown_pct:
                self.stopped_reason = (
                    f"MAX DRAWDOWN triggered: {drawdown_pct:.1f}% "
                    f"(limit: {self.config.max_drawdown_pct:.1f}%) | "
                    f"Peak: ${self.peak_portfolio_value:,.2f} -> Current: ${portfolio_value:,.2f}"
                )
                print(f"\n  {'!'*50}")
                print(f"  {self.stopped_reason}")
                print(f"  {'!'*50}")
                self.cancel_all_live_orders()
                self._sell_all_crypto(current_price)
                return True

        return False

    # ── Grid initialization ──

    def initialize_grid(self, current_price: float):
        spacing_mode = "GEOMETRIC" if self.config.geometric else "LINEAR"
        mode_label = "LIVE TRADING" if self.is_live else "PAPER TRADING"

        print(f"\n{'='*60}")
        print(f"  GRID BOT INITIALIZATION ({mode_label})")
        print(f"{'='*60}")
        print(f"  Symbol:         {self.config.symbol}")
        print(f"  Current Price:  ${current_price:,.2f}")
        print(f"  Grid Range:     ${self.config.lower_price:,.2f} -- ${self.config.upper_price:,.2f}")
        if self.config.geometric:
            print(f"  Grid Ratio:     {self.grid_ratio:.6f} ({(self.grid_ratio - 1) * 100:.3f}% per level)")
        else:
            print(f"  Grid Step:      ${self.grid_step:,.2f}")
        print(f"  Spacing:        {spacing_mode}")
        print(f"  Num Grids:      {self.config.num_grids}")
        print(f"  Investment:     ${self.config.total_investment:,.2f} USDT")
        print(f"  Per Grid:       ${self.usdt_per_grid:,.2f} USDT")
        print(f"  Fee Rate:       {self.config.fee_rate * 100:.2f}%")
        if self.config.stop_loss_price > 0:
            print(f"  Stop Loss:      ${self.config.stop_loss_price:,.2f}")
        if self.config.take_profit_price > 0:
            print(f"  Take Profit:    ${self.config.take_profit_price:,.2f}")
        print(f"  Max Drawdown:   {self.config.max_drawdown_pct:.1f}%")
        print(f"{'='*60}\n")

        if self.is_live:
            print(f"  *** LIVE MODE: Real orders will be placed on OKX ***\n")

        for i, level in enumerate(self.grid_levels):
            if level.price < current_price:
                level.has_buy_order = True
                if self.is_live:
                    amount = self.usdt_per_grid / level.price
                    level.live_order_id = self._place_live_buy(level.price, amount)
                print(f"  BUY  Grid {i:2d} | ${level.price:>10,.2f} | BUY order placed")
            elif level.price > current_price:
                amount = self.usdt_per_grid / current_price
                fee = self.usdt_per_grid * self.config.fee_rate
                if self.usdt_balance >= self.usdt_per_grid + fee:
                    self.usdt_balance -= (self.usdt_per_grid + fee)
                    self.crypto_balance += amount
                    self.total_fees_paid += fee
                    level.has_sell_order = True
                    level.holding_crypto = True
                    if self.is_live:
                        level.live_order_id = self._place_live_sell(level.price, amount)
                    self.trades.append(Trade(
                        timestamp=datetime.now().isoformat(), side="buy",
                        price=level.price, actual_price=current_price,
                        amount=amount, cost=self.usdt_per_grid, fee=fee, grid_level=i
                    ))
                    print(f"  SELL Grid {i:2d} | ${level.price:>10,.2f} | SELL order (bought {amount:.6f} @ ${current_price:,.2f})")
            else:
                print(f"  ---- Grid {i:2d} | ${level.price:>10,.2f} | Current price zone")

        self.last_price = current_price
        self._print_status(current_price)
        self._save_state()

    def check_and_execute(self, current_price: float):
        if self.last_price is None:
            self.last_price = current_price
            return

        for i, level in enumerate(self.grid_levels):
            # BUY trigger
            if (level.has_buy_order
                and current_price <= level.price
                and self.last_price > level.price):

                amount = self.usdt_per_grid / current_price
                fee = self.usdt_per_grid * self.config.fee_rate

                if self.usdt_balance >= self.usdt_per_grid + fee:
                    self.usdt_balance -= (self.usdt_per_grid + fee)
                    self.crypto_balance += amount
                    self.total_fees_paid += fee

                    if self.is_live and level.live_order_id:
                        self._cancel_live_order(level.live_order_id)
                        level.live_order_id = ""

                    level.has_buy_order = False
                    level.holding_crypto = True

                    if i + 1 < len(self.grid_levels):
                        self.grid_levels[i + 1].has_sell_order = True
                        if self.is_live:
                            sell_level = self.grid_levels[i + 1]
                            sell_level.live_order_id = self._place_live_sell(sell_level.price, amount)

                    self.trades.append(Trade(
                        timestamp=datetime.now().isoformat(), side="buy",
                        price=level.price, actual_price=current_price,
                        amount=amount, cost=self.usdt_per_grid, fee=fee, grid_level=i
                    ))
                    print(f"\n  BUY  @ grid ${level.price:,.2f} (actual: ${current_price:,.2f})")
                    print(f"     Amount: {amount:.6f} | Cost: ${self.usdt_per_grid:,.2f} | Fee: ${fee:,.2f}")

            # SELL trigger
            elif (level.has_sell_order
                  and current_price >= level.price
                  and self.last_price < level.price):

                if self.is_live and level.live_order_id:
                    self._cancel_live_order(level.live_order_id)
                    level.live_order_id = ""

                buy_level_idx = i - 1
                if buy_level_idx >= 0 and self.grid_levels[buy_level_idx].holding_crypto:
                    buy_amount = self.usdt_per_grid / self.grid_levels[buy_level_idx].price
                    sell_revenue = buy_amount * current_price
                    fee = sell_revenue * self.config.fee_rate

                    if self.crypto_balance >= buy_amount:
                        self.crypto_balance -= buy_amount
                        self.usdt_balance += (sell_revenue - fee)
                        self.total_fees_paid += fee

                        grid_profit = sell_revenue - self.usdt_per_grid - fee - (self.usdt_per_grid * self.config.fee_rate)
                        self.total_profit += grid_profit
                        self.num_completed_cycles += 1

                        level.has_sell_order = False
                        self.grid_levels[buy_level_idx].holding_crypto = False
                        self.grid_levels[buy_level_idx].has_buy_order = True

                        if self.is_live:
                            bl = self.grid_levels[buy_level_idx]
                            bl.live_order_id = self._place_live_buy(bl.price, self.usdt_per_grid / bl.price)

                        self.trades.append(Trade(
                            timestamp=datetime.now().isoformat(), side="sell",
                            price=level.price, actual_price=current_price,
                            amount=buy_amount, cost=sell_revenue, fee=fee, grid_level=i
                        ))
                        print(f"\n  SELL @ grid ${level.price:,.2f} (actual: ${current_price:,.2f})")
                        print(f"     Amount: {buy_amount:.6f} | Revenue: ${sell_revenue:,.2f} | Fee: ${fee:,.2f}")
                        print(f"     Grid Profit: ${grid_profit:,.2f} | Total Profit: ${self.total_profit:,.2f}")

                elif level.holding_crypto:
                    buy_price_approx = self.trades[0].actual_price if self.trades else current_price
                    amount = self.usdt_per_grid / buy_price_approx
                    sell_revenue = amount * current_price
                    fee = sell_revenue * self.config.fee_rate

                    if self.crypto_balance >= amount:
                        self.crypto_balance -= amount
                        self.usdt_balance += (sell_revenue - fee)
                        self.total_fees_paid += fee

                        grid_profit = sell_revenue - self.usdt_per_grid - fee - (self.usdt_per_grid * self.config.fee_rate)
                        self.total_profit += grid_profit
                        self.num_completed_cycles += 1

                        level.has_sell_order = False
                        level.holding_crypto = False

                        if i - 1 >= 0:
                            self.grid_levels[i - 1].has_buy_order = True
                            if self.is_live:
                                bl = self.grid_levels[i - 1]
                                bl.live_order_id = self._place_live_buy(bl.price, self.usdt_per_grid / bl.price)

                        self.trades.append(Trade(
                            timestamp=datetime.now().isoformat(), side="sell",
                            price=level.price, actual_price=current_price,
                            amount=amount, cost=sell_revenue, fee=fee, grid_level=i
                        ))
                        print(f"\n  SELL @ grid ${level.price:,.2f} (actual: ${current_price:,.2f})")
                        print(f"     Amount: {amount:.6f} | Revenue: ${sell_revenue:,.2f}")
                        print(f"     Grid Profit: ${grid_profit:,.2f}")

        self.last_price = current_price

    def _print_status(self, current_price: float):
        crypto_value = self.crypto_balance * current_price
        total_value = self.usdt_balance + crypto_value
        unrealized_pnl = total_value - self.config.total_investment

        if total_value > self.peak_portfolio_value:
            self.peak_portfolio_value = total_value
        drawdown_pct = 0.0
        if self.peak_portfolio_value > 0:
            drawdown_pct = (self.peak_portfolio_value - total_value) / self.peak_portfolio_value * 100

        active_buys = sum(1 for l in self.grid_levels if l.has_buy_order)
        active_sells = sum(1 for l in self.grid_levels if l.has_sell_order)
        mode_tag = "[LIVE]" if self.is_live else "[PAPER]"
        spacing_tag = "geo" if self.config.geometric else "lin"

        print(f"\n  +-------------------------------------------+")
        print(f"  |  STATUS {mode_tag} @ {datetime.now().strftime('%H:%M:%S')}  ({spacing_tag})       |")
        print(f"  +-------------------------------------------+")
        print(f"  |  Price:    ${current_price:>12,.2f}              |")
        print(f"  |  USDT:     ${self.usdt_balance:>12,.2f}              |")
        print(f"  |  Crypto:    {self.crypto_balance:>12.6f}              |")
        print(f"  |  Value:    ${crypto_value:>12,.2f}              |")
        print(f"  |  Total:    ${total_value:>12,.2f}              |")
        print(f"  |  P&L:      ${unrealized_pnl:>+12,.2f}              |")
        print(f"  |  Profit:   ${self.total_profit:>+12,.2f}              |")
        print(f"  |  Fees:     ${self.total_fees_paid:>12,.2f}              |")
        print(f"  |  Cycles:    {self.num_completed_cycles:>12d}              |")
        print(f"  |  Buys:      {active_buys:>12d}              |")
        print(f"  |  Sells:     {active_sells:>12d}              |")
        print(f"  |  Drawdown:  {drawdown_pct:>11.1f}%              |")
        print(f"  +-------------------------------------------+")

    def _save_state(self):
        state = {
            "config": {
                k: v for k, v in asdict(self.config).items()
                if k not in ("api_key", "api_secret", "passphrase")
            },
            "grid_levels": [
                {"price": l.price, "has_buy_order": l.has_buy_order,
                 "has_sell_order": l.has_sell_order, "holding_crypto": l.holding_crypto}
                for l in self.grid_levels
            ],
            "trades": [asdict(t) for t in self.trades[-100:]],
            "usdt_balance": self.usdt_balance,
            "crypto_balance": self.crypto_balance,
            "total_fees_paid": self.total_fees_paid,
            "total_profit": self.total_profit,
            "num_completed_cycles": self.num_completed_cycles,
            "start_time": self.start_time,
            "last_price": self.last_price,
            "last_update": datetime.now().isoformat(),
            "total_value": self.usdt_balance + (self.crypto_balance * (self.last_price or 0)),
            "mode": "live" if self.is_live else "paper",
            "geometric": self.config.geometric,
            "peak_portfolio_value": self.peak_portfolio_value,
            "stopped_reason": self.stopped_reason,
            "stop_loss_price": self.config.stop_loss_price,
            "take_profit_price": self.config.take_profit_price,
            "max_drawdown_pct": self.config.max_drawdown_pct,
        }
        with open(self.config.state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _shutdown(self, current_price: float):
        self.running = False
        self.cancel_all_live_orders()
        self._print_status(current_price)
        self._save_state()
        mode_tag = "LIVE" if self.is_live else "PAPER"
        print(f"\n  State saved to {self.config.state_file}")
        print(f"  Mode: {mode_tag}")
        print(f"  Total trades: {len(self.trades)}")
        print(f"  Completed cycles: {self.num_completed_cycles}")
        print(f"  Total profit: ${self.total_profit:,.2f}")
        print(f"  Total fees: ${self.total_fees_paid:,.2f}")
        if self.stopped_reason:
            print(f"  Stop reason: {self.stopped_reason}")

    def run(self):
        mode_label = "LIVE" if self.is_live else "Paper"
        print(f"\n  Grid Bot starting ({mode_label} mode)...")
        print(f"  Fetching {self.config.symbol} price from OKX...\n")

        if self.is_live:
            print(f"  *** WARNING: LIVE TRADING MODE ***")
            print(f"  *** Real orders will be placed on OKX ***")
            print(f"  *** Investment: ${self.config.total_investment:,.2f} USDT ***\n")

        try:
            current_price = self.get_current_price()
        except Exception as e:
            print(f"  Failed to fetch price: {e}")
            print("  Make sure you have internet connection and ccxt installed.")
            return

        if current_price < self.config.lower_price or current_price > self.config.upper_price:
            print(f"  WARNING: Current price ${current_price:,.2f} is OUTSIDE your grid range!")
            print(f"  Grid range: ${self.config.lower_price:,.2f} -- ${self.config.upper_price:,.2f}")
            return

        if self.config.stop_loss_price > 0 and current_price <= self.config.stop_loss_price:
            print(f"  Current price already at/below stop-loss. Not starting.")
            return
        if self.config.take_profit_price > 0 and current_price >= self.config.take_profit_price:
            print(f"  Current price already at/above take-profit. Not starting.")
            return

        self.initialize_grid(current_price)
        self.running = True

        def signal_handler(signum, frame):
            print(f"\n\n  Bot stopped by signal ({signum}).")
            self._shutdown(current_price)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print(f"\n  Polling every {self.config.poll_interval}s... (Ctrl+C to stop)\n")

        tick_count = 0
        try:
            while self.running:
                time.sleep(self.config.poll_interval)
                tick_count += 1

                try:
                    current_price = self.get_current_price()
                except Exception as e:
                    print(f"  Price fetch error: {e}. Retrying...")
                    continue

                if self._check_safety(current_price):
                    self._shutdown(current_price)
                    return

                self.check_and_execute(current_price)

                if tick_count % 12 == 0:
                    self._print_status(current_price)
                else:
                    crypto_val = self.crypto_balance * current_price
                    total_val = self.usdt_balance + crypto_val
                    pnl = total_val - self.config.total_investment
                    mode_tag = "L" if self.is_live else "P"
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                          f"${current_price:>10,.2f} | "
                          f"P&L: ${pnl:>+8,.2f} | "
                          f"Cycles: {self.num_completed_cycles} [{mode_tag}]", end="\r")

                self._save_state()

        except KeyboardInterrupt:
            print(f"\n\n  Bot stopped by user.")
            self._shutdown(current_price)


# ─────────────────────────────────────────────
# Interactive Setup
# ─────────────────────────────────────────────

def interactive_setup() -> GridConfig:
    print("\n" + "="*60)
    print("  GRID TRADING BOT -- Setup")
    print("="*60)

    existing = load_config()
    if existing:
        print(f"\n  Found existing config in {CONFIG_FILE}")
        print(f"  Symbol: {existing.symbol} | Range: ${existing.lower_price:,.2f}-${existing.upper_price:,.2f}")
        print(f"  Grids: {existing.num_grids} | Geometric: {existing.geometric} | Investment: ${existing.total_investment:,.2f}")
        if existing.stop_loss_price > 0:
            print(f"  Stop Loss: ${existing.stop_loss_price:,.2f}")
        if existing.take_profit_price > 0:
            print(f"  Take Profit: ${existing.take_profit_price:,.2f}")
        print(f"  Max Drawdown: {existing.max_drawdown_pct}%")
        use_existing = input(f"\n  Use this config? [Y/n]: ").strip().lower()
        if use_existing != "n":
            existing = _setup_live_mode(existing)
            return existing

    print("\n  Which pair do you want to trade?")
    print("  1) BTC/USDT")
    print("  2) ETH/USDT")
    choice = input("\n  Enter 1 or 2 [1]: ").strip() or "1"
    symbol = "BTC/USDT" if choice == "1" else "ETH/USDT"

    print(f"\n  Fetching {symbol} price from OKX...")
    exchange = ccxt.okx({"enableRateLimit": True})
    ticker = exchange.fetch_ticker(symbol)
    current_price = ticker["last"]
    print(f"  Current price: ${current_price:,.2f}")

    if symbol == "BTC/USDT":
        default_lower = round(current_price * 0.95 / 1000) * 1000
        default_upper = round(current_price * 1.05 / 1000) * 1000
    else:
        default_lower = round(current_price * 0.95 / 50) * 50
        default_upper = round(current_price * 1.05 / 50) * 50

    print(f"\n  Set your grid range (suggested: +/-5% from current price)")
    lower = input(f"  Lower price [{default_lower:,.0f}]: ").strip()
    lower = float(lower) if lower else default_lower
    upper = input(f"  Upper price [{default_upper:,.0f}]: ").strip()
    upper = float(upper) if upper else default_upper

    num_grids = input(f"\n  Num grids [10]: ").strip()
    num_grids = int(num_grids) if num_grids else 10

    print(f"\n  Grid spacing mode:")
    print(f"  Geometric is usually better for crypto.")
    geo_input = input(f"  Use geometric spacing? [Y/n]: ").strip().lower()
    geometric = geo_input != "n"

    investment = input(f"\n  Investment USDT [753]: ").strip()
    investment = float(investment) if investment else 753.0

    interval = input(f"\n  Poll interval seconds [5]: ").strip()
    interval = int(interval) if interval else 5

    print(f"\n  --- Safety Settings ---")
    max_dd = input(f"  Max drawdown % [10]: ").strip()
    max_dd = float(max_dd) if max_dd else 10.0

    stop_loss = input(f"  Stop-loss price (0=disabled) [0]: ").strip()
    stop_loss = float(stop_loss) if stop_loss else 0.0

    take_profit = input(f"  Take-profit price (0=disabled) [0]: ").strip()
    take_profit = float(take_profit) if take_profit else 0.0

    grid_prices = build_grid_levels(lower, upper, num_grids, geometric)
    spacing_label = "geometric" if geometric else "linear"

    print(f"\n  {'_'*50}")
    print(f"  Summary:")
    print(f"  Symbol: {symbol} | Range: ${lower:,.2f}-${upper:,.2f} | {spacing_label}")
    print(f"  Grids: {num_grids} | Investment: ${investment:,.2f} | Per grid: ${investment/num_grids:,.2f}")
    if max_dd: print(f"  Max drawdown: {max_dd}%")
    if stop_loss > 0: print(f"  Stop-loss: ${stop_loss:,.2f}")
    if take_profit > 0: print(f"  Take-profit: ${take_profit:,.2f}")

    print(f"\n  Grid levels ({spacing_label}):")
    for idx, gp in enumerate(grid_prices):
        if idx > 0:
            diff = gp - grid_prices[idx - 1]
            pct = diff / grid_prices[idx - 1] * 100
            print(f"    {idx:2d}  ${gp:>10,.2f}  (+${diff:,.2f} / +{pct:.2f}%)")
        else:
            print(f"    {idx:2d}  ${gp:>10,.2f}")

    # Optional backtest before starting
    bt_input = input(f"\n  Run a backtest with these settings first? [Y/n]: ").strip().lower()
    if bt_input != "n":
        bt_days = input(f"  Backtest period in days (e.g. 30, 90, 180, 365) [30]: ").strip()
        bt_days = int(bt_days) if bt_days else 30
        try:
            from backtest import BacktestConfig, run_backtest, print_results
            bt_cfg = BacktestConfig(
                symbol=symbol, days=bt_days, num_grids=num_grids,
                total_investment=investment, fee_rate=0.001,
                upper_price=upper, lower_price=lower,
                geometric=geometric,
            )
            results = run_backtest(bt_cfg)
            print_results(results)
        except Exception as e:
            print(f"  Backtest error: {e}")
            print(f"  Skipping backtest, continuing to bot setup...")

    confirm = input(f"\n  Start bot? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("  Cancelled.")
        exit(0)

    config = GridConfig(
        symbol=symbol, upper_price=upper, lower_price=lower,
        num_grids=num_grids, geometric=geometric,
        total_investment=investment, poll_interval=interval,
        max_drawdown_pct=max_dd, stop_loss_price=stop_loss,
        take_profit_price=take_profit,
    )
    save_config(config)
    config = _setup_live_mode(config)
    return config


def _setup_live_mode(config: GridConfig) -> GridConfig:
    api_key = os.environ.get("OKX_API_KEY", "")
    api_secret = os.environ.get("OKX_API_SECRET", "")
    passphrase = os.environ.get("OKX_PASSPHRASE", "")

    if api_key and api_secret and passphrase:
        config.api_key = api_key
        config.api_secret = api_secret
        config.passphrase = passphrase
        print(f"\n  OKX API keys detected.")
        live_input = input(f"  Enable LIVE trading? (real money!) [y/N]: ").strip().lower()
        if live_input == "y":
            confirm = input(f"  Type YES to confirm: ").strip()
            if confirm == "YES":
                config.live = True
                print(f"  LIVE MODE ENABLED.")
            else:
                config.live = False
                print(f"  Paper mode.")
        else:
            config.live = False
    else:
        config.live = False
    return config


if __name__ == "__main__":
    config = interactive_setup()
    bot = GridBot(config)
    bot.run()
