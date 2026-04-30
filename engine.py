import numpy as np
import pandas as pd

STRATEGIES = ["strategy_1", "strategy_2", "strategy_3", "strategy_4"]

# ==============================
# SAFE DATA BUILDER (CORE FIX)
# ==============================
def _build_market_df(price_list=None, candles_df=None):

    if candles_df is not None:
        df = candles_df.copy()
    else:
        df = pd.DataFrame({"Close": price_list})

    # Normalize OHLCV column names without mutating other arbitrary columns
    rename_map = {c: c.capitalize() for c in df.columns if c.lower() in ["open", "high", "low", "close", "volume"]}
    df = df.rename(columns=rename_map)

    if "Close" not in df.columns:
        raise ValueError("Close column required")

    # Ensure ALL columns exist (Angel + backtest compatible)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in df.columns:
            if col == "Volume":
                df[col] = 0.0
            else:
                df[col] = df["Close"]

    # Convert safely
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.ffill().bfill()

    df["price"] = df["Close"]

    return df.reset_index(drop=True)


# ==============================
# FEATURE ENGINEERING
# ==============================
def get_base_df(price_list=None, candles_df=None):

    df = _build_market_df(price_list, candles_df)

    # EMA TREND
    df["ema_fast"] = df["price"].ewm(span=9, adjust=False).mean()
    df["ema_mid"] = df["price"].ewm(span=21, adjust=False).mean()
    df["ema_slow"] = df["price"].ewm(span=50, adjust=False).mean()

    # VWAP (SAFE for zero volume)
    vol = df["Volume"].replace(0, np.nan)
    df["vwap"] = (df["price"] * vol).cumsum() / vol.cumsum()
    df["vwap"] = df["vwap"].fillna(df["price"])

    # Bollinger Bands
    df["sma_20"] = df["price"].rolling(20).mean()
    df["std_20"] = df["price"].rolling(20).std()
    df["upper_band"] = df["sma_20"] + 2 * df["std_20"]
    df["lower_band"] = df["sma_20"] - 2 * df["std_20"]

    # RSI
    delta = df["price"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    prev_close = df["price"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / df["price"]

    return df


# ==============================
# REGIME DETECTION (IMPROVED)
# ==============================
def get_market_regime(df):

    if len(df) < 30:
        return 0

    c = df.iloc[-1]

    ema_diff = abs(c["ema_fast"] - c["ema_mid"]) / c["price"]

    trend_up = c["ema_fast"] > c["ema_mid"] and c["price"] >= c["vwap"]
    trend_down = c["ema_fast"] < c["ema_mid"] and c["price"] <= c["vwap"]

    # Require an even stronger trend spread to avoid sideways chop whipsaws
    if ema_diff > 0.0015:
        if trend_up:
            return 1
        if trend_down:
            return -1

    return 0


# ==============================
# RISK MANAGEMENT
# ==============================
def risk_management(current=None, capital=100000, lot_size=50):

    atr_pct = 0.002

    if current is not None:
        try:
            val = float(current.get("atr_pct", atr_pct))
            if np.isfinite(val) and val > 0:
                atr_pct = val
        except:
            pass

    stop_loss_pct = float(np.clip(max(atr_pct * 1.5, 0.0025), 0.0025, 0.006)) # Tighten SL slightly
    # 1:2.5 R/R with dynamic trailing
    target_pct = float(max(stop_loss_pct * 2.5, 0.0065))
    breakeven_pct = float(stop_loss_pct * 0.5) # Move to breakeven MUCH faster
    trail_distance = float(stop_loss_pct * 0.4) # Tighten trail once in profit

    return {
        "stop_loss_pct": stop_loss_pct,
        "target_pct": target_pct,
        "breakeven_pct": breakeven_pct,
        "trail_distance": trail_distance,
        "brokerage_fee": 60,
        "risk_per_trade_pct": 0.01,
        "daily_loss_limit_pct": 0.02,
        "lot_size": lot_size,
        "capital": capital,
    }


# ==============================
# POSITION SIZING
# ==============================
def calculate_position_size(price, stop_loss_pct, capital=100000, lot_size=50, risk_per_trade_pct=0.01):

    if price <= 0 or stop_loss_pct <= 0:
        return lot_size

    risk_amount = capital * risk_per_trade_pct
    risk_per_lot = price * stop_loss_pct * lot_size

    if risk_per_lot <= 0:
        return lot_size

    risk_lots = max(1, int(np.floor(risk_amount / risk_per_lot)))
    
    # Smart Capital Rule: Never deploy > 25% of total capital on a single trade
    max_capital_for_trade = capital * 0.25
    cost_per_lot = price * lot_size
    capital_lots = max(1, int(np.floor(max_capital_for_trade / cost_per_lot)))

    lots = min(risk_lots, capital_lots)
    return lots * lot_size


# ==============================
# SIGNAL LOGIC
# ==============================
def trend_signal(c, regime):

    if regime == 1:
        if c["price"] > c["ema_fast"] > c["ema_mid"] and c["price"] >= c["vwap"] and c["rsi"] > 60:
            return "BUY_LONG"

    if regime == -1:
        if c["price"] < c["ema_fast"] < c["ema_mid"] and c["price"] <= c["vwap"] and c["rsi"] < 40:
            return "SELL_SHORT"

    return "WAIT"


def mean_reversion_signal(c, regime):

    if regime != 0:
        return "WAIT"

    if c["rsi"] < 30 and c["price"] <= c["lower_band"]:
        return "BUY_LONG"

    if c["rsi"] > 70 and c["price"] >= c["upper_band"]:
        return "SELL_SHORT"

    return "WAIT"


# ==============================
# MAIN SIGNAL ENGINE
# ==============================
def calculate_signals(price_list, current_time, position=0, entry_price=0, **kwargs):

    candles_df = kwargs.get("candles_df")
    capital = kwargs.get("capital", 100000)
    lot_size = kwargs.get("lot_size", 50)

    if candles_df is None and (price_list is None or len(price_list) < 30):
        return {"action": "WAIT"}

    df = get_base_df(price_list=price_list, candles_df=candles_df)

    if len(df) < 30:
        return {"action": "WAIT"}

    current = df.iloc[-1]

    regime = get_market_regime(df)
    risk = risk_management(current=current, capital=capital, lot_size=lot_size)

    qty = calculate_position_size(
        price=float(current["price"]),
        stop_loss_pct=risk["stop_loss_pct"],
        capital=capital,
        lot_size=lot_size,
        risk_per_trade_pct=risk["risk_per_trade_pct"],
    )

    # ================= ENTRY =================
    action = "WAIT"

    if position == 0:
        action = trend_signal(current, regime)

        if action == "WAIT":
            action = mean_reversion_signal(current, regime)

    # ================= EXIT =================
    elif position > 0:
        if regime == -1 or current["price"] < current["ema_mid"]:
            action = "EXIT_LONG"

    elif position < 0:
        if regime == 1 or current["price"] > current["ema_mid"]:
            action = "EXIT_SHORT"

    return {
        "action": action,
        "price": round(float(current["price"]), 2),
        "ema_fast": round(float(current["ema_fast"]), 2),
        "ema_mid": round(float(current["ema_mid"]), 2),
        "vwap": round(float(current["vwap"]), 2),
        "rsi": round(float(current["rsi"]), 2),
        "atr_pct": round(float(current["atr_pct"]), 5) if pd.notna(current["atr_pct"]) else None,
        "regime": regime,
        "stop_loss_pct": risk["stop_loss_pct"],
        "target_pct": risk["target_pct"],
        "breakeven_pct": risk["breakeven_pct"],
        "trail_distance": risk["trail_distance"],
        "suggested_qty": qty,
    }