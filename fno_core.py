"""Shared code: data, indicators, strategies, market-condition check. PAPER TRADING / educational only. Not financial advice."""
from datetime import timedelta, timezone

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))

INDICES = {
    "NIFTY": {"ticker": "^NSEI", "step": 50},
    "BANKNIFTY": {"ticker": "^NSEBANK", "step": 100},
    "SENSEX": {"ticker": "^BSESN", "step": 100},
}

STRATEGY_LABELS = {
    "ema": "EMA 9/21 cross",
    "supertrend": "Supertrend (10,3)",
    "orb": "Opening-range breakout",
}


# ---------------------------------------------------------------- data
def fetch(ticker: str, period: str = "5d") -> pd.DataFrame:
    import yfinance as yf  # imported here so the logic can be tested offline

    df = yf.download(ticker, period=period, interval="15m",
                     progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(IST)
    return df


# ---------------------------------------------------------- indicators
def _supertrend(df: pd.DataFrame, atr: pd.Series, mult: float = 3.0):
    hl2 = ((df["High"] + df["Low"]) / 2).values
    a = atr.values
    close = df["Close"].values
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb = ub.copy(), lb.copy()
    direction = np.ones(len(df), dtype=int)
    for i in range(1, len(df)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or close[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or close[i - 1] < flb[i - 1]) else flb[i - 1]
        if close[i] > fub[i - 1]:
            direction[i] = 1
        elif close[i] < flb[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return direction


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["ema9"] = c.ewm(span=9, adjust=False).mean()
    df["ema21"] = c.ewm(span=21, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, 1e-9))
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - c.shift()).abs(),
        (df["Low"] - c.shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr10 = tr.ewm(alpha=1 / 10, adjust=False).mean()
    df["st_dir"] = _supertrend(df, atr10, 3.0)
    df["trending"] = ((df["ema21"] - df["ema50"]).abs() / df["atr"]) >= 0.5
    return df


# ---------------------------------------------------------- strategies
# Each returns a Series: +1 = buy CE (bullish), -1 = buy PE (bearish), 0 = none
def sig_ema(df: pd.DataFrame) -> pd.Series:
    p9, p21 = df["ema9"].shift(), df["ema21"].shift()
    up = (p9 <= p21) & (df["ema9"] > df["ema21"]) & (df["rsi"] > 50) & (df["Close"] > df["ema50"])
    dn = (p9 >= p21) & (df["ema9"] < df["ema21"]) & (df["rsi"] < 50) & (df["Close"] < df["ema50"])
    return pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=df.index)


def sig_supertrend(df: pd.DataFrame) -> pd.Series:
    d, p = df["st_dir"], df["st_dir"].shift()
    up = (d == 1) & (p == -1)
    dn = (d == -1) & (p == 1)
    return pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=df.index)


def sig_orb(df: pd.DataFrame) -> pd.Series:
    """Opening range = first two 15m candles (09:15-09:45). First close outside the range (until 14:30) gives the day's signal."""
    sig = pd.Series(0, index=df.index)
    for _, g in df.groupby(df.index.date):
        if len(g) < 3:
            continue
        orh, orl = g["High"].iloc[:2].max(), g["Low"].iloc[:2].min()
        for ts, row in g.iloc[2:].iterrows():
            if ts.hour * 60 + ts.minute > 14 * 60 + 30:
                break
            if row["Close"] > orh:
                sig.loc[ts] = 1
                break
            if row["Close"] < orl:
                sig.loc[ts] = -1
                break
    return sig


STRATEGIES = {"ema": sig_ema, "supertrend": sig_supertrend, "orb": sig_orb}


# ------------------------------------------------- market-condition check
def market_context(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    today = df.index[-1].date()
    day = df[df.index.date == today]
    prev = df[df.index.date < today]
    prev_close = prev["Close"].iloc[-1] if len(prev) else np.nan
    gap = (day["Open"].iloc[0] / prev_close - 1) * 100
    chg = (last["Close"] / prev_close - 1) * 100
    return {
        "day_change": chg,
        "gap": gap,
        "trend": "UP" if last["ema21"] > last["ema50"] else "DOWN",
        "state": "TRENDING" if last["trending"] else "SIDEWAYS/CHOPPY",
        "atr_pct": last["atr"] / last["Close"] * 100,
        "range_pts": day["High"].max() - day["Low"].min(),
        "rsi": last["rsi"],
    }


def fmt_context(ctx: dict) -> str:
    return (f"Day {ctx['day_change']:+.2f}% | Gap {ctx['gap']:+.2f}% | "
            f"Trend {ctx['trend']} ({ctx['state']}) | RSI {ctx['rsi']:.0f} | "
            f"Volatility {ctx['atr_pct']:.2f}% | Range {ctx['range_pts']:.0f} pts")
