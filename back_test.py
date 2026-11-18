"""
Backtest the 3 strategies on Nifty / BankNifty / Sensex 15m candles.
Yahoo only gives ~60 days of 15m data, so this is a SHORT sample: treat results
as a rough sanity check, not proof. Results are in INDEX POINTS (not rupees,
not option premium). Costs/slippage are not included.

Rules: enter at next candle's open, SL = 1 ATR, target = 1.5 ATR (SL assumed
first if both hit in one candle), forced exit at 15:15, no entries after 14:45,
one trade at a time. Run with SEND=1 to also push the summary to Telegram.
"""
import os

import numpy as np
import pandas as pd
import requests

from fno_core import INDICES, STRATEGIES, STRATEGY_LABELS, add_indicators, fetch


def run(df: pd.DataFrame, sig: pd.Series, only_trending: bool = False) -> list:
    n, trades, i = len(df), [], 0
    idx = df.index
    while i < n - 1:
        s = sig.iloc[i]
        j = i + 1
        ok = (s != 0 and idx[j].date() == idx[i].date()
              and idx[j].hour * 60 + idx[j].minute < 14 * 60 + 45
              and (not only_trending or df["trending"].iloc[i]))
        if not ok:
            i += 1
            continue
        entry, atr = df["Open"].iloc[j], df["atr"].iloc[i]
        sl, tgt = entry - s * atr, entry + s * 1.5 * atr
        exit_px, k = None, j
        while k < n and idx[k].date() == idx[j].date():
            hi, lo = df["High"].iloc[k], df["Low"].iloc[k]
            hit_sl = lo <= sl if s == 1 else hi >= sl
            hit_t = hi >= tgt if s == 1 else lo <= tgt
            if hit_sl:
                exit_px = sl
                break
            if hit_t:
                exit_px = tgt
                break
            if idx[k].hour * 60 + idx[k].minute >= 15 * 60:
                exit_px = df["Close"].iloc[k]
                break
            k += 1
        if exit_px is None:  # data ended / day ended without a trigger
            k = min(k, n) - 1
            exit_px = df["Close"].iloc[k]
        trades.append(s * (exit_px - entry))
        i = k + 1
    return trades


def stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "win": 0, "total": 0, "avg": 0, "pf": 0, "dd": 0}
    t = np.array(trades)
    wins, losses = t[t > 0].sum(), -t[t < 0].sum()
    cum = t.cumsum()
    dd = (np.maximum.accumulate(cum) - cum).max()
    return {"n": len(t), "win": (t > 0).mean() * 100, "total": t.sum(),
            "avg": t.mean(), "pf": wins / losses if losses else float("inf"),
            "dd": dd}


def main() -> None:
    rows = []
    for name, cfg in INDICES.items():
        df = fetch(cfg["ticker"], period="60d")
        if df.empty or len(df) < 100:
            print(f"{name}: not enough data")
            continue
        df = add_indicators(df)
        days = len(set(df.index.date))
        for key, fn in STRATEGIES.items():
            sig = fn(df)
            for filt in (False, True):
                st = stats(run(df, sig, filt))
                rows.append((name, STRATEGY_LABELS[key], "trend-only" if filt else "all", days, st))

    lines = []
    for name, strat, mode, days, st in rows:
        lines.append(f"{name} | {strat} | {mode}: {st['n']} trades, win {st['win']:.0f}%, "
                     f"net {st['total']:+.0f} pts, avg {st['avg']:+.1f}, "
                     f"PF {st['pf']:.2f}, max DD {st['dd']:.0f} pts")
    msg = (f"BACKTEST (last ~{rows[0][3] if rows else 0} trading days, 15m, index points, "
           f"no costs)\n" + "\n".join(lines))
    print(msg)

    # Hardcoded fallback (use only in a PRIVATE repo). GitHub secrets take priority.
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or "8800834277:AAFPNTftIOyU8CNxUWTK7hPnJdNsosGoneo"
    chat = os.environ.get("TELEGRAM_CHAT_ID") or "1738674172"
    if os.environ.get("SEND") == "1" and token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": msg[:4000]}, timeout=20)


if __name__ == "__main__":
    main()
  
