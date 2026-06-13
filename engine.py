import numpy as np # Import numpy for fast numerical operations and NaN handling
import pandas as pd # Import pandas for data manipulation and DataFrame structures

STRATEGIES = ["strategy_1", "strategy_2", "strategy_3", "strategy_4"] # Define the available trading strategies
MIN_SIGNAL_CANDLES = 50 # Increased for ADX and slow EMA stabilization
LATEST_ENTRY_MINUTE = 15 * 60 + 00 # Stop taking new entries at 3:00 PM
# Safety thresholds to avoid high-risk entries
SHORT_MIN_RSI = 30.0  # Do not open new SHORTs when RSI is below this (avoids shorting deeply oversold bounces)

# ==============================
# SAFE DATA BUILDER
# ==============================
def _build_market_df(price_list=None, candles_df=None):

    if candles_df is not None: 
        df = candles_df.copy() 
    else: 
        df = pd.DataFrame({"Close": price_list}) 

    rename_map = {c: c.capitalize() for c in df.columns if c.lower() in ["open", "high", "low", "close", "volume"]}
    df = df.rename(columns=rename_map)

    if "Close" not in df.columns: 
        raise ValueError("Close column required")

    for col in ["Open", "High", "Low", "Close", "Volume"]: 
        if col not in df.columns: 
            if col == "Volume": 
                df[col] = 0.0 
            else: 
                df[col] = df["Close"] 

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
    if vol.isna().all(): 
        df["vwap"] = df["price"].rolling(window=60, min_periods=1).mean()
    else:
        df["vwap"] = (df["price"] * vol).rolling(window=60, min_periods=1).sum() / vol.rolling(window=60, min_periods=1).sum()
        df["vwap"] = df["vwap"].fillna(df["price"].rolling(window=60, min_periods=1).mean())

    # Bollinger Bands
    df["sma_20"] = df["price"].rolling(20).mean()
    df["std_20"] = df["price"].rolling(20).std()
    df["upper_band"] = df["sma_20"] + 2 * df["std_20"]
    df["lower_band"] = df["sma_20"] - 2 * df["std_20"]
    df["bb_width"] = (df["upper_band"] - df["lower_band"]) / df["sma_20"].replace(0, np.nan)

    # RSI
    delta = df["price"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    df["macd"] = df["price"].ewm(span=12, adjust=False).mean() - df["price"].ewm(span=26, adjust=False).mean()
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["macd_hist_slope"] = df["macd_hist"] - df["macd_hist"].shift(1)

    # ATR & ADX (For Market Regime Detection)
    prev_close = df["price"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / df["price"]

    up_move = df["High"] - df["High"].shift(1)
    down_move = df["Low"].shift(1) - df["Low"]
    df["+dm"] = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    df["-dm"] = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    df["+dm_smoothed"] = df["+dm"].ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df["-dm_smoothed"] = df["-dm"].ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df["atr_smoothed"] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    df["+di"] = 100 * (df["+dm_smoothed"] / (df["atr_smoothed"] + 1e-9))
    df["-di"] = 100 * (df["-dm_smoothed"] / (df["atr_smoothed"] + 1e-9))
    df["dx"] = 100 * (abs(df["+di"] - df["-di"]) / (df["+di"] + df["-di"] + 1e-9))
    df["adx"] = df["dx"].ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    df["recent_high"] = df["High"].rolling(20).max().shift(1)
    df["recent_low"] = df["Low"].rolling(20).min().shift(1)
    df["volume_sma"] = df["Volume"].rolling(20).mean()
    df["volume_ratio"] = df["Volume"] / df["volume_sma"].replace(0, np.nan)
    df["volume_ratio"] = df["volume_ratio"].replace([np.inf, -np.inf], np.nan).fillna(1.0)
    
    # Adaptive Percentile Baselines
    df["bb_width_pct_25"] = df["bb_width"].rolling(60, min_periods=1).quantile(0.25)
    df["ema_diff"] = abs(df["ema_fast"] - df["ema_mid"]) / df["price"]
    df["ema_diff_pct_75"] = df["ema_diff"].rolling(60, min_periods=1).quantile(0.75)

    return df


# ==============================
# REGIME DETECTION (IMPROVED)
# ==============================
def get_market_regime(df):
    if len(df) < 50:
        return 0

    c = df.iloc[-1]
    
    # Adaptive Sideways detection (Bottom 25% of recent volatility)
    if c.get("bb_width", 1.0) < c.get("bb_width_pct_25", 0.002):
        return 0

    trend_up = c["ema_fast"] > c["ema_mid"] and c["price"] >= c["vwap"]
    trend_down = c["ema_fast"] < c["ema_mid"] and c["price"] <= c["vwap"]

    # Require top 25% trend spread to avoid sideways chop whipsaws
    if c.get("ema_diff", 0) > c.get("ema_diff_pct_75", 0.0008):
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
    brokerage_fee = 60.0
    slippage_bps = 0.0003
    max_loss_per_trade_amount = capital * 0.03

    if current is not None:
        try:
            val = float(current.get("atr_pct", atr_pct))
            if np.isfinite(val) and val > 0:
                atr_pct = val
        except:
            pass

    # Robust dynamic volatility stop, capped so one configured lot stays inside the risk budget.
    base_stop_loss_pct = max(0.0030, atr_pct * 2.5)
    stop_loss_pct = base_stop_loss_pct
    
    if current is not None:
        try:
            price = float(current.get("price", 0.0))
        except Exception:
            price = 0.0
        usable_risk_amount = max(0.0, max_loss_per_trade_amount - brokerage_fee)
        if price > 0 and lot_size > 0 and usable_risk_amount > 0:
            max_stop_for_one_lot = (usable_risk_amount / (price * lot_size)) - (slippage_bps * 2)
            if max_stop_for_one_lot > 0:
                stop_loss_pct = min(base_stop_loss_pct, max_stop_for_one_lot)
    
    # Target is dynamically set to 2.5x the actual risk for high expectancy
    target_pct = stop_loss_pct * 2.5 
    # Move to breakeven when profit reaches 1.0x risk
    breakeven_pct = stop_loss_pct * 1.0  
    # Tight trailing distance to secure profits
    trail_distance = stop_loss_pct * 0.5  

    return {
        "stop_loss_pct": stop_loss_pct,
        "target_pct": target_pct,
        "breakeven_pct": breakeven_pct,
        "trail_distance": trail_distance,
        "brokerage_fee": brokerage_fee,
        "risk_per_trade_pct": 0.03,
        "max_loss_per_trade_amount": max_loss_per_trade_amount,
        "daily_loss_limit_pct": 3000.0 / capital,
        "profit_protection_start_amount": 1000.0,
        "profit_giveback_pct": 0.20,
        "lot_size": lot_size,
        "capital": capital,
        "slippage_bps": slippage_bps,
    }


# ==============================
# POSITION SIZING
# ==============================
def calculate_position_size(
    price,
    stop_loss_pct,
    capital=100000,
    lot_size=50,
    risk_per_trade_pct=0.03,
    max_loss_per_trade_amount=3000.0,
    brokerage_fee=60.0,
    slippage_bps=0.0003,
):
    if price <= 0 or stop_loss_pct <= 0:
        return 0

    risk_amount = min(capital * risk_per_trade_pct, max_loss_per_trade_amount)
    usable_risk_amount = max(0.0, risk_amount - brokerage_fee)
    per_unit_risk = price * (stop_loss_pct + (slippage_bps * 2))
    
    if per_unit_risk <= 0 or usable_risk_amount <= 0:
        return 0

    risk_qty = int(np.floor(usable_risk_amount / per_unit_risk))
    lots = risk_qty // lot_size
    
    if lots < 1:
        return 0
        
    return lots * lot_size


# ==============================
# SIGNAL LOGIC
# ==============================
def trend_signal(c, regime):
    """
    VWAP BOUNCE STRATEGY
    High expectancy strategy entering pullbacks to VWAP/EMA in a strong trend.
    """
    if regime == 0:
        return "WAIT"

    price = c["price"]

    # Trend alignment (slightly loosened to capture earlier trends)
    bull_trend = c["ema_fast"] > c["ema_mid"] and c["ema_slow"] > c["vwap"] * 0.998
    bear_trend = c["ema_fast"] < c["ema_mid"] and c["ema_slow"] < c["vwap"] * 1.002

    # Pullback to value zone (widened value zone for more opportunities)
    value_zone_long = c["ema_fast"] * 1.002 >= price >= c["vwap"] * 0.998
    value_zone_short = c["ema_fast"] * 0.998 <= price <= c["vwap"] * 1.002

    # Momentum turning back in direction of trend
    mom_up = c.get("macd_hist_slope", 0) > 0 and c["macd"] > c["macd_signal"]
    mom_down = c.get("macd_hist_slope", 0) < 0 and c["macd"] < c["macd_signal"]

    if regime == 1 and bull_trend:
        if (value_zone_long and 
            mom_up and
            45 < c["rsi"] < 70):
            return "BUY_LONG"

    if regime == -1 and bear_trend:
        if (value_zone_short and 
            mom_down and
            30 < c["rsi"] < 55):
            return "SELL_SHORT"

    return "WAIT"


def bollinger_reversion_signal(c, regime):
    if pd.isna(c.get("recent_high")) or pd.isna(c.get("recent_low")):
        return "WAIT"

    has_vol = c.get("volume_sma", 0.0) > 0
    volume_ok = c.get("volume_ratio", 1.0) >= 1.0 if has_vol else True
    price = c["price"]
    
    if (price > c["recent_high"] * 1.0002 and
        volume_ok and
        35 <= c["rsi"] <= 85 and
        regime >= 0):
        return "BUY_LONG"

    if (price < c["recent_low"] * 0.9998 and
        volume_ok and
        15 <= c["rsi"] <= 65 and
        regime <= 0):
        return "SELL_SHORT"

    return "WAIT"


def fusion_strategy_signal(c, regime):
    if pd.isna(c.get("recent_high")) or pd.isna(c.get("recent_low")):
        return "WAIT"
        
    if c.get("bb_width", 1.0) < 0.002:
        return "WAIT"

    has_vol = c.get("volume_sma", 0.0) > 0
    volume_ok = c.get("volume_ratio", 1.0) >= 1.0 if has_vol else True
    price = c["price"]
    
    if regime == 1: 
        if (price > c["vwap"] and
            c["ema_fast"] > c["ema_mid"] and
            price > c["ema_fast"] and
            volume_ok and
            55 <= c["rsi"] <= 75 and
            c["macd"] > c["macd_signal"] and
            c.get("macd_hist_slope", 0) > 0):
            return "BUY_LONG"

    if regime == -1:
        if (price < c["vwap"] and
            c["ema_fast"] < c["ema_mid"] and
            price < c["ema_fast"] and
            volume_ok and
            25 <= c["rsi"] <= 45 and
            c["macd"] < c["macd_signal"] and
            c.get("macd_hist_slope", 0) < 0):
            return "SELL_SHORT"

    return "WAIT"


def select_entry_signal(current, regime, strategy_name):
    if strategy_name == "strategy_1":
        return trend_signal(current, regime)
    if strategy_name == "strategy_2":
        return bollinger_reversion_signal(current, regime)
    if strategy_name == "strategy_3":
        return bollinger_reversion_signal(current, regime)
    if strategy_name == "strategy_4":
        return fusion_strategy_signal(current, regime)

    action = bollinger_reversion_signal(current, regime)
    if action == "WAIT":
        action = trend_signal(current, regime)
    return action


# ==============================
# MAIN SIGNAL ENGINE
# ==============================
def calculate_signals(price_list, current_time, position=0, entry_price=0, **kwargs):

    candles_df = kwargs.get("candles_df")
    capital = kwargs.get("capital", 100000)
    lot_size = kwargs.get("lot_size", 50)
    strategy_name = kwargs.get("strategy_name", "strategy_1")

    if candles_df is None and (price_list is None or len(price_list) < MIN_SIGNAL_CANDLES):
        return {"action": "WAIT"}

    df = get_base_df(price_list=price_list, candles_df=candles_df)

    if len(df) < MIN_SIGNAL_CANDLES:
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
        max_loss_per_trade_amount=risk["max_loss_per_trade_amount"],
        brokerage_fee=risk["brokerage_fee"],
    ) 

    # ================= ENTRY =================
    action = "WAIT"

    if position == 0 and qty > 0:
        is_too_late = False
        if hasattr(current_time, "hour"):
            market_minute = current_time.hour * 60 + current_time.minute
            if market_minute >= LATEST_ENTRY_MINUTE:
                is_too_late = True
                
        if not is_too_late:
            action = select_entry_signal(current, regime, strategy_name)

            try:
                current_rsi = float(current.get("rsi", 50.0))
            except Exception:
                current_rsi = 50.0

            if action == "SELL_SHORT" and current_rsi < SHORT_MIN_RSI:
                action = "WAIT"

    # ================= EXIT =================
    elif position > 0:
        if regime == -1 or current["price"] < current["ema_slow"]:
            action = "EXIT_LONG"

    elif position < 0:
        if regime == 1 or current["price"] > current["ema_slow"]:
            action = "EXIT_SHORT"

    return {
        "action": action,
        "price": round(float(current["price"]), 2),
        "ema_fast": round(float(current["ema_fast"]), 2),
        "ema_mid": round(float(current["ema_mid"]), 2),
        "vwap": round(float(current["vwap"]), 2),
        "ema_f": round(float(current["ema_fast"]), 2),
        "rsi": round(float(current["rsi"]), 2),
        "rsi_fast": round(float(current["rsi"]), 2),
        "entry_score": round(float(current.get("rsi", 50.0)), 2),
        "atr_pct": round(float(current["atr_pct"]), 5) if pd.notna(current["atr_pct"]) else None,
        "atr": round(float(current["atr"]), 2) if pd.notna(current["atr"]) else None,
        "volume_ratio": round(float(current["volume_ratio"]), 2) if pd.notna(current["volume_ratio"]) else None,
        "regime": regime,
        "strategy_name": strategy_name,
        "stop_loss_pct": risk["stop_loss_pct"],
        "target_pct": risk["target_pct"],
        "breakeven_pct": risk["breakeven_pct"],
        "trail_distance": risk["trail_distance"],
        "suggested_qty": qty,
        "brokerage_fee": risk["brokerage_fee"],
        "max_loss_per_trade_amount": risk["max_loss_per_trade_amount"],
        "daily_loss_limit_pct": risk["daily_loss_limit_pct"],
        "profit_protection_start_amount": risk["profit_protection_start_amount"],
        "profit_giveback_pct": risk["profit_giveback_pct"],
    }
