"""
Nifty, BankNifty & Sensex F&O scanner (15-min candles) -> Telegram alerts.
PAPER TRADING / educational only. Not financial advice.

Env vars:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  STRATEGIES     comma list, default "ema,supertrend,orb"
  REQUIRE_TREND  "1" = skip signals when market is SIDEWAYS/CHOPPY
  TEST           "1" = send a market snapshot now, even if closed
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import requests

from fno_core import (IST, INDICES, STRATEGIES, STRATEGY_LABELS, add_indicators,
                      fetch, fmt_context, market_context)

# Hardcoded fallback (use only in a PRIVATE repo). GitHub secrets, if set, take priority.
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "8800834277:AAFPNTftIOyU8CNxUWTK7hPnJdNsosGoneo"
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or "1738674172"
TEST = os.environ.get("TEST", "") == "1"
REQUIRE_TREND = os.environ.get("REQUIRE_TREND", "") == "1"
ACTIVE = [s.strip() for s in os.environ.get("STRATEGIES", "ema,supertrend,orb").split(",")
          if s.strip() in STRATEGIES]


def send(msg: str) -> None:
    print(msg, "\n")
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets missing, skipping send")
        return
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    if not r.ok:
        print("Telegram error:", r.text)


def scan(name: str, cfg: dict):
    """Returns (snapshot_line, is_opening_candle)."""
    df = fetch(cfg["ticker"])
    now = datetime.now(IST)
    if df.empty:
        print(f"{name}: no data")
        return None
    df = df[df.index + pd.Timedelta(minutes=15) <= now]  # completed candles only
    if len(df) < 60:
        print(f"{name}: not enough completed candles")
        return None
    df = add_indicators(df)
    last = df.iloc[-1]
    ctx = market_context(df)
    candle_start = df.index[-1]
    fresh = (now - (candle_start + pd.Timedelta(minutes=15))) <= timedelta(minutes=20)

    if fresh:
        for strat in ACTIVE:
            s = STRATEGIES[strat](df).iloc[-1]
            if s == 0:
                continue
            if REQUIRE_TREND and ctx["state"] != "TRENDING":
                print(f"{name} {strat}: signal skipped (choppy market)")
                continue
            opt = "CE" if s == 1 else "PE"
            strike = int(round(last["Close"] / cfg["step"]) * cfg["step"])
            sl = last["Close"] - s * last["atr"]
            tgt = last["Close"] + s * 1.5 * last["atr"]
            send(
                f"[PAPER] {name} 15m: BUY {opt} ({'bullish' if s == 1 else 'bearish'})\n"
                f"Strategy: {STRATEGY_LABELS[strat]}\n"
                f"Spot: {last['Close']:.2f} | ATM strike: {strike} {opt}\n"
                f"Index SL: {sl:.1f} | Target: {tgt:.1f}\n"
                f"Market: {fmt_context(ctx)}\n"
                f"Candle: {candle_start.strftime('%d-%b %H:%M')} IST\n"
                f"Check expiry/premium yourself. Paper trade only."
            )

    line = f"{name} {last['Close']:.2f}\n  {fmt_context(ctx)}"
    is_open = fresh and candle_start.hour == 9 and candle_start.minute == 15
    return line, is_open


def main() -> None:
    now = datetime.now(IST)
    if not TEST and (now.weekday() >= 5 or not (9 <= now.hour < 16)):
        print("Market closed, exiting")
        return
    lines, opening = [], False
    for name, cfg in INDICES.items():
        try:
            res = scan(name, cfg)
            if res:
                lines.append(res[0])
                opening = opening or res[1]
        except Exception as e:  # keep going if one index fails
            print(f"{name} error: {e}", file=sys.stderr)
    if lines and (TEST or opening):
        send("Market snapshot (" + now.strftime("%d-%b %H:%M") + " IST)\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
  
