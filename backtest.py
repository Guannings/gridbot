"""
Grid Bot Backtester
===================
Fetches historical candles from OKX and simulates the grid strategy.

Uses HIGH and LOW prices within each candle to detect grid crossings,
matching how real exchange grid bots work (limit orders fill at exact
grid prices, not just at candle closes).

Usage:
    python backtest.py                    # defaults: BTC/USDT, 30 days
    python backtest.py --days 90          # 90-day backtest
    python backtest.py --grids 100        # 100 grid levels (tight spacing)
    python backtest.py --symbol ETH/USDT  # test on ETH
    python backtest.py --geometric        # use geometric (%) spacing
    python backtest.py --sweep            # find best settings automatically

Run with --help for all options.
"""

import ccxt
import argparse
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass


@dataclass
class BacktestConfig:
    symbol: str = "BTC/USDT"
    days: int = 30
    timeframe: str = "5m"
    num_grids: int = 10
    total_investment: float = 10000.0
    fee_rate: float = 0.001
    upper_price: float = 0.0
    lower_price: float = 0.0
    geometric: bool = False
    range_pct: float = 10.0


def fetch_candles(symbol: str, timeframe: str, days: int) -> list[list]:
    exchange = ccxt.okx({"enableRateLimit": True})
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    all_candles = []
    print(f"  Fetching {symbol} {timeframe} candles for {days} days...")
    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=300)
        if not candles:
            break
        all_candles.extend(candles)
        since = candles[-1][0] + 1
        if since > int(datetime.now(timezone.utc).timestamp() * 1000):
            break
        time.sleep(exchange.rateLimit / 1000)
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    unique.sort(key=lambda c: c[0])
    t0 = datetime.fromtimestamp(unique[0][0] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    t1 = datetime.fromtimestamp(unique[-1][0] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    print(f"  Got {len(unique)} candles from {t0} to {t1}")
    return unique


def build_grid_levels(lower, upper, num_grids, geometric):
    if geometric:
        ratio = (upper / lower) ** (1 / num_grids)
        return [round(lower * (ratio ** i), 2) for i in range(num_grids + 1)]
    else:
        step = (upper - lower) / num_grids
        return [round(lower + i * step, 2) for i in range(num_grids + 1)]


def _simulate(config, candles):
    grid_prices = build_grid_levels(config.lower_price, config.upper_price, config.num_grids, config.geometric)
    n_levels = len(grid_prices)
    usdt_per_grid = config.total_investment / config.num_grids

    has_buy = [False] * n_levels
    has_sell = [False] * n_levels
    holding = [False] * n_levels
    bought_amount = [0.0] * n_levels

    usdt_balance = config.total_investment
    crypto_balance = 0.0
    total_fees = 0.0
    total_profit = 0.0
    num_cycles = 0
    num_trades = 0

    start_price = candles[0][4]
    for i, gp in enumerate(grid_prices):
        if gp < start_price:
            has_buy[i] = True
        elif gp > start_price:
            amount = usdt_per_grid / start_price
            fee = usdt_per_grid * config.fee_rate
            if usdt_balance >= usdt_per_grid + fee:
                usdt_balance -= (usdt_per_grid + fee)
                crypto_balance += amount
                total_fees += fee
                has_sell[i] = True
                holding[i] = True
                bought_amount[i] = amount
                num_trades += 1

    max_equity = config.total_investment
    max_drawdown = 0.0

    def _try_buy(i):
        nonlocal usdt_balance, crypto_balance, total_fees, num_trades
        if not has_buy[i]:
            return
        gp = grid_prices[i]
        amount = usdt_per_grid / gp
        fee = usdt_per_grid * config.fee_rate
        if usdt_balance >= usdt_per_grid + fee:
            usdt_balance -= (usdt_per_grid + fee)
            crypto_balance += amount
            total_fees += fee
            has_buy[i] = False
            holding[i] = True
            bought_amount[i] = amount
            if i + 1 < n_levels:
                has_sell[i + 1] = True
            num_trades += 1

    def _try_sell(i):
        nonlocal usdt_balance, crypto_balance, total_fees, total_profit, num_cycles, num_trades
        if not has_sell[i]:
            return
        gp = grid_prices[i]
        buy_idx = i - 1
        amount = 0.0
        buy_cost = usdt_per_grid
        if buy_idx >= 0 and holding[buy_idx]:
            amount = bought_amount[buy_idx]
        elif holding[i]:
            amount = bought_amount[i]
            buy_idx = i
        else:
            return
        if amount <= 0 or crypto_balance < amount * 0.999:
            return
        revenue = amount * gp
        fee = revenue * config.fee_rate
        crypto_balance -= amount
        usdt_balance += (revenue - fee)
        total_fees += fee
        grid_profit = revenue - buy_cost - fee - (buy_cost * config.fee_rate)
        total_profit += grid_profit
        num_cycles += 1
        has_sell[i] = False
        holding[buy_idx] = False
        bought_amount[buy_idx] = 0.0
        if buy_idx < n_levels:
            has_buy[buy_idx] = True
        num_trades += 1

    for candle in candles:
        ts, o, h, l, c, v = candle
        bullish = c >= o
        if bullish:
            for i in range(n_levels):
                if has_buy[i] and grid_prices[i] >= l:
                    _try_buy(i)
            for i in range(n_levels):
                if has_sell[i] and grid_prices[i] <= h:
                    _try_sell(i)
        else:
            for i in range(n_levels):
                if has_sell[i] and grid_prices[i] <= h:
                    _try_sell(i)
            for i in range(n_levels):
                if has_buy[i] and grid_prices[i] >= l:
                    _try_buy(i)

        equity = usdt_balance + crypto_balance * c
        if equity > max_equity:
            max_equity = equity
        dd = (max_equity - equity) / max_equity if max_equity > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

    end_price = candles[-1][4]
    final_equity = usdt_balance + crypto_balance * end_price
    total_return = (final_equity - config.total_investment) / config.total_investment * 100
    buy_hold_return = (end_price - start_price) / start_price * 100
    days_actual = (candles[-1][0] - candles[0][0]) / (1000 * 86400)
    ann_return = ((final_equity / config.total_investment) ** (365 / days_actual) - 1) * 100 if days_actual > 0 and final_equity > 0 else 0.0
    closes = [c[4] for c in candles]
    in_range = sum(1 for p in closes if config.lower_price <= p <= config.upper_price)

    return {
        "start_price": start_price, "end_price": end_price,
        "price_min": min(c[3] for c in candles), "price_max": max(c[2] for c in candles),
        "final_equity": final_equity, "total_return_pct": total_return,
        "annualized_return_pct": ann_return, "buy_hold_return_pct": buy_hold_return,
        "grid_profit": total_profit, "total_fees": total_fees,
        "num_cycles": num_cycles, "total_trades": num_trades,
        "max_drawdown_pct": max_drawdown * 100,
        "in_range_pct": in_range / len(candles) * 100,
        "usdt_balance": usdt_balance, "crypto_balance": crypto_balance,
        "days_actual": days_actual,
    }


def run_backtest(config):
    candles = fetch_candles(config.symbol, config.timeframe, config.days)
    if config.upper_price == 0 or config.lower_price == 0:
        closes = [c[4] for c in candles]
        mid = (min(closes) + max(closes)) / 2
        spread = config.range_pct / 100
        config.lower_price = round(mid * (1 - spread), 2)
        config.upper_price = round(mid * (1 + spread), 2)
        print(f"  Auto range: ${config.lower_price:,.2f} - ${config.upper_price:,.2f} (+/-{config.range_pct}% from mid ${mid:,.2f})")
    r = _simulate(config, candles)
    r["config"] = config
    r["grid_prices"] = build_grid_levels(config.lower_price, config.upper_price, config.num_grids, config.geometric)
    return r


def print_results(r):
    c = r["config"]
    spacing = "geometric" if c.geometric else "linear"
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*60}")
    print(f"  Symbol:           {c.symbol}")
    print(f"  Period:           {c.days} days ({r['days_actual']:.1f} actual)")
    print(f"  Timeframe:        {c.timeframe}")
    print(f"  Grid range:       ${c.lower_price:,.2f} - ${c.upper_price:,.2f}")
    print(f"  Grid spacing:     {spacing}, {c.num_grids} levels")
    print(f"  Investment:       ${c.total_investment:,.2f}")
    print(f"{'─'*60}")
    print(f"  Start price:      ${r['start_price']:,.2f}")
    print(f"  End price:        ${r['end_price']:,.2f}")
    print(f"  Price range:      ${r['price_min']:,.2f} - ${r['price_max']:,.2f}")
    print(f"  Time in range:    {r['in_range_pct']:.1f}%")
    print(f"{'─'*60}")
    print(f"  Final equity:     ${r['final_equity']:,.2f}")
    print(f"  Total return:     {r['total_return_pct']:+.2f}%")
    print(f"  Annualized:       {r['annualized_return_pct']:+.2f}%")
    print(f"  Buy & hold:       {r['buy_hold_return_pct']:+.2f}%")
    print(f"  Grid vs B&H:      {r['total_return_pct'] - r['buy_hold_return_pct']:+.2f}%")
    print(f"{'─'*60}")
    print(f"  Grid profit:      ${r['grid_profit']:,.2f}")
    print(f"  Fees paid:        ${r['total_fees']:,.2f}")
    print(f"  Completed cycles: {r['num_cycles']}")
    print(f"  Total trades:     {r['total_trades']}")
    print(f"  Max drawdown:     {r['max_drawdown_pct']:.2f}%")
    print(f"{'='*60}")

    gp = r["grid_prices"]
    if len(gp) <= 25:
        print(f"\n  Grid levels ({spacing}):")
        for i, p in enumerate(gp):
            if i > 0:
                diff = p - gp[i - 1]
                pct = diff / gp[i - 1] * 100
                print(f"    {i:3d}  ${p:>10,.2f}  (+${diff:,.2f} / +{pct:.2f}%)")
            else:
                print(f"    {i:3d}  ${p:>10,.2f}")
    else:
        step_pct = (gp[1] - gp[0]) / gp[0] * 100
        print(f"\n  {len(gp)} grid levels from ${gp[0]:,.2f} to ${gp[-1]:,.2f} (~{step_pct:.3f}%/level)")

    avg = r["grid_profit"] / r["num_cycles"] if r["num_cycles"] > 0 else 0
    print(f"\n  Avg profit per cycle: ${avg:,.2f}")
    print()


def run_sweep(base_config):
    candles = fetch_candles(base_config.symbol, base_config.timeframe, base_config.days)
    closes = [c[4] for c in candles]
    mid = (min(closes) + max(closes)) / 2

    grid_options = [10, 20, 30, 50, 75, 100, 150, 200]
    range_options = [3, 5, 8, 10, 15, 20]
    geo_options = [False, True]

    print(f"\n{'='*70}")
    print(f"  PARAMETER SWEEP - {base_config.symbol} ({base_config.days}d)")
    print(f"  Price range: ${min(closes):,.2f} - ${max(closes):,.2f}")
    print(f"{'='*70}")
    print(f"  {'Grids':>6} {'Range%':>7} {'Spc':>4} {'Return%':>9} {'vs B&H':>8} {'Cycles':>7} {'Fees':>8} {'MaxDD%':>7}")
    print(f"  {'─'*60}")

    best = None
    results_list = []

    for rng in range_options:
        for ng in grid_options:
            for geo in geo_options:
                lower = round(mid * (1 - rng / 100), 2)
                upper = round(mid * (1 + rng / 100), 2)
                cfg = BacktestConfig(
                    symbol=base_config.symbol, days=base_config.days,
                    timeframe=base_config.timeframe, num_grids=ng,
                    total_investment=base_config.total_investment,
                    fee_rate=base_config.fee_rate, upper_price=upper,
                    lower_price=lower, geometric=geo, range_pct=rng,
                )
                r = _simulate(cfg, candles)
                spc = "geo" if geo else "lin"
                bh = r["buy_hold_return_pct"]
                vs = r["total_return_pct"] - bh
                print(f"  {ng:>6} {rng:>6}% {spc:>4} {r['total_return_pct']:>+8.2f}% "
                      f"{vs:>+7.2f}% {r['num_cycles']:>7} ${r['total_fees']:>7.0f} {r['max_drawdown_pct']:>6.1f}%")
                r["_cfg"] = cfg
                results_list.append(r)
                if best is None or r["total_return_pct"] > best["total_return_pct"]:
                    best = r

    if best:
        bc = best["_cfg"]
        spc = "geometric" if bc.geometric else "linear"
        print(f"\n  BEST: {bc.num_grids} grids, +/-{bc.range_pct}% range, {spc}")
        print(f"        Return: {best['total_return_pct']:+.2f}% | Cycles: {best['num_cycles']} | MaxDD: {best['max_drawdown_pct']:.1f}%")

    results_list.sort(key=lambda r: -r["total_return_pct"])
    print(f"\n  TOP 10:")
    print(f"  {'Grids':>6} {'Range%':>7} {'Spc':>4} {'Return%':>9} {'Cycles':>7} {'Fees':>8} {'MaxDD%':>7}")
    print(f"  {'─'*55}")
    for r in results_list[:10]:
        rc = r["_cfg"]
        spc = "geo" if rc.geometric else "lin"
        print(f"  {rc.num_grids:>6} {rc.range_pct:>6}% {spc:>4} {r['total_return_pct']:>+8.2f}% "
              f"{r['num_cycles']:>7} ${r['total_fees']:>7.0f} {r['max_drawdown_pct']:>6.1f}%")
    print()


def main():
    parser = argparse.ArgumentParser(description="Grid Bot Backtester")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--grids", type=int, default=10)
    parser.add_argument("--investment", type=float, default=10000)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--upper", type=float, default=0)
    parser.add_argument("--lower", type=float, default=0)
    parser.add_argument("--range-pct", type=float, default=10)
    parser.add_argument("--geometric", action="store_true")
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()

    config = BacktestConfig(
        symbol=args.symbol, days=args.days, timeframe=args.timeframe,
        num_grids=args.grids, total_investment=args.investment,
        fee_rate=args.fee, upper_price=args.upper, lower_price=args.lower,
        geometric=args.geometric, range_pct=args.range_pct,
    )

    if args.sweep:
        run_sweep(config)
    else:
        results = run_backtest(config)
        print_results(results)


if __name__ == "__main__":
    main()
