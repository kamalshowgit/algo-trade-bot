import numpy as np # Import numpy for fast numerical operations and NaN handling
import pandas as pd # Import pandas for data manipulation and DataFrame structures

STRATEGIES = ["strategy_1", "strategy_2", "strategy_3", "strategy_4"] # Define the available trading strategies
MIN_SIGNAL_CANDLES = 21 # 20-candle breakout window plus current candle
LATEST_ENTRY_MINUTE = 15 * 60 + 15 # Match the default profile entry window; profile rules remain the main gate

# ==============================
# SAFE DATA BUILDER (CORE FIX)
# ==============================
def _build_market_df(price_list=None, candles_df=None): # Function to safely build a standardized market dataframe

    if candles_df is not None: # Check if a dataframe of candles was passed
        df = candles_df.copy() # Make a copy to avoid mutating the original dataframe
    else: # If no dataframe was passed
        df = pd.DataFrame({"Close": price_list}) # Construct one using the provided price list

    # Normalize OHLCV column names without mutating other arbitrary columns
    rename_map = {c: c.capitalize() for c in df.columns if c.lower() in ["open", "high", "low", "close", "volume"]} # Map lowercase names to Capitalized
    df = df.rename(columns=rename_map) # Apply the renaming map to the dataframe columns

    if "Close" not in df.columns: # Check if the 'Close' column exists
        raise ValueError("Close column required") # Raise an error if 'Close' is missing, as it's mandatory

    # Ensure ALL columns exist (Angel + backtest compatible)
    for col in ["Open", "High", "Low", "Close", "Volume"]: # Loop through essential OHLCV columns
        if col not in df.columns: # If a required column is missing
            if col == "Volume": # If the missing column is Volume
                df[col] = 0.0 # Initialize it with 0.0 (no volume)
            else: # For missing Open, High, or Low
                df[col] = df["Close"] # Fallback to the Close price

    # Convert safely
    for col in ["Open", "High", "Low", "Close", "Volume"]: # Loop through columns again
        df[col] = pd.to_numeric(df[col], errors="coerce") # Coerce invalid parsing into NaN

    df = df.ffill().bfill() # Forward fill then backward fill any NaN values to ensure data continuity

    df["price"] = df["Close"] # Duplicate the 'Close' column as a generic 'price' column for easier access

    return df.reset_index(drop=True) # Reset the dataframe index and drop the old one before returning


# ==============================
# FEATURE ENGINEERING
# ==============================
def get_base_df(price_list=None, candles_df=None): # Function to extract technical features

    df = _build_market_df(price_list, candles_df) # Build and standardize the dataframe

    # EMA TREND
    df["ema_fast"] = df["price"].ewm(span=9, adjust=False).mean() # Calculate the 9-period Exponential Moving Average
    df["ema_mid"] = df["price"].ewm(span=21, adjust=False).mean() # Calculate the 21-period Exponential Moving Average
    df["ema_slow"] = df["price"].ewm(span=50, adjust=False).mean() # Calculate the 50-period Exponential Moving Average

    # VWAP (SAFE for zero volume)
    vol = df["Volume"].replace(0, np.nan)
    if vol.isna().all(): # Fallback to SMA if volume is missing entirely (e.g. Yahoo Finance indices)
        df["vwap"] = df["price"].rolling(window=60, min_periods=1).mean()
    else:
        df["vwap"] = (df["price"] * vol).rolling(window=60, min_periods=1).sum() / vol.rolling(window=60, min_periods=1).sum()
        df["vwap"] = df["vwap"].fillna(df["price"].rolling(window=60, min_periods=1).mean()) # Fill NaN VWAP values with SMA as fallback

    # Bollinger Bands
    df["sma_20"] = df["price"].rolling(20).mean() # Calculate the 20-period Simple Moving Average
    df["std_20"] = df["price"].rolling(20).std() # Calculate the 20-period standard deviation
    df["upper_band"] = df["sma_20"] + 2 * df["std_20"] # Upper Bollinger Band (SMA + 2 * StdDev)
    df["lower_band"] = df["sma_20"] - 2 * df["std_20"] # Lower Bollinger Band (SMA - 2 * StdDev)
    df["bb_width"] = (df["upper_band"] - df["lower_band"]) / df["sma_20"].replace(0, np.nan) # Prevent division by zero

    # RSI
    delta = df["price"].diff() # Find the difference in price between consecutive periods
    gain = delta.clip(lower=0).rolling(14).mean() # Isolate gains and calculate the 14-period rolling mean
    loss = (-delta.clip(upper=0)).rolling(14).mean() # Isolate losses and calculate the 14-period rolling mean
    rs = gain / (loss + 1e-9) # Compute Relative Strength (RS), adding epsilon (1e-9) to avoid division by zero
    df["rsi"] = 100 - (100 / (1 + rs)) # Convert RS to the Relative Strength Index (RSI) oscillator

    # MACD (Moving Average Convergence Divergence) - For Ultimate Trend Confirmation
    df["macd"] = df["price"].ewm(span=12, adjust=False).mean() - df["price"].ewm(span=26, adjust=False).mean()
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["macd_hist_slope"] = df["macd_hist"] - df["macd_hist"].shift(1)

    # ATR
    prev_close = df["price"].shift(1) # Get the previous period's closing price
    tr = pd.concat([ # Compute True Range as the maximum of three possible measures:
        df["High"] - df["Low"], # 1. Current High minus current Low
        (df["High"] - prev_close).abs(), # 2. Absolute value of current High minus previous Close
        (df["Low"] - prev_close).abs() # 3. Absolute value of current Low minus previous Close
    ], axis=1).max(axis=1) # Find the maximum of the three columns per row

    df["atr"] = tr.rolling(14).mean() # Calculate the Average True Range (14-period rolling mean of True Range)
    df["atr_pct"] = df["atr"] / df["price"] # Convert ATR into a percentage of the current price for normalized volatility
    df["recent_high"] = df["High"].rolling(20).max().shift(1) # Previous 20-candle high for breakout checks
    df["recent_low"] = df["Low"].rolling(20).min().shift(1) # Previous 20-candle low for breakout checks
    df["volume_sma"] = df["Volume"].rolling(20).mean() # Average volume for participation checks
    df["volume_ratio"] = df["Volume"] / df["volume_sma"].replace(0, np.nan) # Current volume relative to recent average
    df["volume_ratio"] = df["volume_ratio"].replace([np.inf, -np.inf], np.nan).fillna(1.0) # Keep volume ratio safe

    return df # Return the fully engineered dataframe


# ==============================
# REGIME DETECTION (IMPROVED)
# ==============================
def get_market_regime(df): # Function to determine the current market trend/regime

    if len(df) < 30: # Ensure there are enough candles to calculate EMAs reliably
        return 0 # Return 0 (sideways/neutral) if insufficient data

    c = df.iloc[-1] # Extract the latest candle (the current row)

    # Sideways detection using Bollinger Band Width (Volatility Squeeze)
    if c.get("bb_width", 1.0) < 0.002: # Strict: If bands are tight (< 0.20% width), avoid chop
        return 0 # Definitely sideways market

    ema_diff = abs(c["ema_fast"] - c["ema_mid"]) / c["price"] # Calculate the percentage spread between fast and mid EMAs

    trend_up = c["ema_fast"] > c["ema_mid"] and c["price"] >= c["vwap"] # Define uptrend criteria
    trend_down = c["ema_fast"] < c["ema_mid"] and c["price"] <= c["vwap"] # Define downtrend criteria

    # Require strong trend spread to avoid sideways chop whipsaws
    if ema_diff > 0.0008: # Strict: If the spread is significant enough (> 0.08%)
        if trend_up: # If uptrend conditions are met
            return 1 # Return 1 for Uptrend
        if trend_down: # If downtrend conditions are met
            return -1 # Return -1 for Downtrend

    return 0 # Return 0 for Sideways/Chop if no clear trend is detected


# ==============================
# RISK MANAGEMENT
# ==============================
def risk_management(current=None, capital=100000, lot_size=50): # Determine risk limits per trade

    atr_pct = 0.002 # Default Average True Range percentage (0.2%)
    brokerage_fee = 60.0 # Flat assumed brokerage fee per completed trade
    slippage_bps = 0.0003 # Match execution slippage used by the live/paper loops
    max_loss_per_trade_amount = capital * 0.03 # Hard cap: never plan more than 3% risk

    if current is not None: # If current candle data is provided
        try: # Safely attempt to extract recent ATR percentage
            val = float(current.get("atr_pct", atr_pct)) # Fetch dynamic ATR pct
            if np.isfinite(val) and val > 0: # Ensure valid positive number
                atr_pct = val # Override default ATR with current market volatility
        except: # Ignore extraction errors
            pass # Fallback to default ATR

    # Dynamic volatility stop, capped so one configured lot stays inside the 3% risk budget.
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
    
    # Target is dynamically set to 2.0x the actual risk (1:2 Risk/Reward) for higher profitability
    target_pct = stop_loss_pct * 2.0 
    
    # Move to breakeven when profit safely reaches 1.0x risk
    breakeven_pct = stop_loss_pct * 1.0  
    
    # Trail distance tightened to lock in profits effectively (0.8x risk)
    trail_distance = stop_loss_pct * 0.8  

    return { # Return the risk parameter dictionary
        "stop_loss_pct": stop_loss_pct, # Output calculated SL pct
        "target_pct": target_pct, # Output calculated Target pct
        "breakeven_pct": breakeven_pct, # Output breakeven trigger pct
        "trail_distance": trail_distance, # Output trailing distance pct
        "brokerage_fee": brokerage_fee, # Flat assumed brokerage fee per trade
        "risk_per_trade_pct": 0.03, # Risk max 3% per trade
        "max_loss_per_trade_amount": max_loss_per_trade_amount, # Absolute per-trade risk ceiling in rupees
        "daily_loss_limit_pct": 3000.0 / capital, # STRICT max daily loss limit is exact 3000.0 rupees
        "profit_protection_start_amount": 1000.0, # Protect session gains earlier (at 1000 profit)
        "profit_giveback_pct": 0.20, # Conserve 80% of peak daily profit, stop entries if 20% given back
        "lot_size": lot_size, # Instrument lot size
        "capital": capital, # Total working capital
        "slippage_bps": slippage_bps, # Execution slippage assumption
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
): # Determines how many lots to buy/sell

    if price <= 0 or stop_loss_pct <= 0: # Catch invalid prices or zero stop loss
        return 0 # Reject unsafe sizing inputs

    risk_amount = min(capital * risk_per_trade_pct, max_loss_per_trade_amount) # Absolute hard cap wins over percentage risk
    usable_risk_amount = max(0.0, risk_amount - brokerage_fee) # Reserve brokerage so net loss stays inside the cap
    per_unit_risk = price * (stop_loss_pct + (slippage_bps * 2)) # Entry and exit slippage are included in planned risk
    if per_unit_risk <= 0 or usable_risk_amount <= 0: # Avoid division by zero errors
        return 0 # Reject if we cannot size under the risk cap

    risk_qty = int(np.floor(usable_risk_amount / per_unit_risk)) # Calculate affordable raw quantity based on risk limit
    
    # Calculate valid F&O lot multipliers
    lots = risk_qty // lot_size
    
    if lots < 1: # If risk is too tight for even 1 lot, skip instead of exceeding the cap
        return 0
        
    return lots * lot_size # Return the total raw quantity of shares/contracts scaled to lot size


# ==============================
# SIGNAL LOGIC
# ==============================
def trend_signal(c, regime): # Core rules for trend following entries
    
    if c.get("bb_width", 1.0) < 0.002: # Filter low volatility
        return "WAIT"

    if regime == 1: # If market is in an uptrend
        if (c["price"] > c["ema_fast"] > c["ema_mid"] and 
            c["price"] >= c["vwap"] and 
            55 < c["rsi"] < 75 and 
            c["macd"] > c["macd_signal"]): # Check bullish alignments and momentum
            return "BUY_LONG" # Output Long Signal

    if regime == -1: # If market is in a downtrend
        if (c["price"] < c["ema_fast"] < c["ema_mid"] and 
            c["price"] <= c["vwap"] and 
            25 < c["rsi"] < 45 and 
            c["macd"] < c["macd_signal"]): # Check bearish alignments and momentum
            return "SELL_SHORT" # Output Short Signal

    return "WAIT" # No valid entry found


def mean_reversion_signal(c, regime): # DISABLED - use VWAP breakout instead
    """
    Mean reversion on 5-min candles doesn't work.
    Use bollinger_reversion_signal (VWAP breakout) for better results.
    """
    return "WAIT"


def bollinger_reversion_signal(c, regime): # BALANCED: Quality breakouts with light regime filter
    """
    BALANCED BREAKOUT (works both trending and sideways):
    - Light regime filter (allows some sideways breakouts)
    - Price must clear recent_high/low by 0.3%+ (less strict than breakout_signal)
    - Good volume + healthy RSI for quality
    """

    if pd.isna(c.get("recent_high")) or pd.isna(c.get("recent_low")):
        return "WAIT"

    has_vol = c.get("volume_sma", 0.0) > 0
    volume_ok = c.get("volume_ratio", 1.0) >= 1.0 if has_vol else True
    price = c["price"]
    
    # LONG: Moderate breakout above recent high
    if (price > c["recent_high"] * 1.0002 and  # 0.02% above recent high 
        volume_ok and
        35 <= c["rsi"] <= 85 and  # Healthy momentum range
        regime >= 0):  # Uptrend or sideways, NOT downtrend
        return "BUY_LONG"

    # SHORT: Moderate breakout below recent low
    if (price < c["recent_low"] * 0.9998 and  # 0.02% below recent low
        volume_ok and
        15 <= c["rsi"] <= 65 and  # Healthy momentum range
        regime <= 0):  # Downtrend or sideways, NOT uptrend
        return "SELL_SHORT"

    return "WAIT"


def fusion_strategy_signal(c, regime): # strategy_4

    """
    STRONG MOMENTUM TREND STRATEGY (MACD + EMA + VWAP)
    - Excludes sideways markets using BB Width & Regime
    - Entries triggered on strong MACD momentum and EMA alignments
    - Price must be strongly trending above/below VWAP
    """

    if pd.isna(c.get("recent_high")) or pd.isna(c.get("recent_low")):
        return "WAIT"
        
    # 1. Sideways Market Filter
    if c.get("bb_width", 1.0) < 0.002: # Must have volatility/expansion
        return "WAIT"

    # 2. Volume/OI Proxy Filter (Quantity & Institutional Interest)
    has_vol = c.get("volume_sma", 0.0) > 0
    # Require average volume instead of 20% exceptionally high volume
    volume_ok = c.get("volume_ratio", 1.0) >= 1.0 if has_vol else True
    price = c["price"]
    
    # 3. LONG: Trend Analysis + Momentum
    if regime == 1: 
        if (price > c["vwap"] and                 # Must be above VWAP (Trend support)
            c["ema_fast"] > c["ema_mid"] and      # Fast EMA above Mid EMA (Trend confirmation)
            price > c["ema_fast"] and             # Price is pushing up above short term average
            volume_ok and                         # Institutional volume confirmation
            55 <= c["rsi"] <= 75 and              # Bullish momentum intact, not extremely overbought
            c["macd"] > c["macd_signal"] and      # Confirmed Bullish MACD crossover
            c.get("macd_hist_slope", 0) > 0):     # Momentum is actively increasing
            return "BUY_LONG"

    # 4. SHORT: Trend Analysis + Momentum
    if regime == -1:
        if (price < c["vwap"] and                 # Must be below VWAP (Trend resistance)
            c["ema_fast"] < c["ema_mid"] and      # Fast EMA below Mid EMA (Trend confirmation)
            price < c["ema_fast"] and             # Price is pushing down below short term average
            volume_ok and                         # Institutional volume confirmation
            25 <= c["rsi"] <= 45 and              # Bearish momentum intact, not extremely oversold
            c["macd"] < c["macd_signal"] and      # Confirmed Bearish MACD crossover
            c.get("macd_hist_slope", 0) < 0):     # Momentum is actively decreasing
            return "SELL_SHORT"

    return "WAIT"


def select_entry_signal(current, regime, strategy_name): # Route configured strategy to its own entry rules

    if strategy_name == "strategy_1":
        return trend_signal(current, regime)
    if strategy_name == "strategy_2":
        return bollinger_reversion_signal(current, regime)  # VWAP breakout - works always
    if strategy_name == "strategy_3":
        return bollinger_reversion_signal(current, regime)  # VWAP breakout - works always
    if strategy_name == "strategy_4":
        return fusion_strategy_signal(current, regime)

    action = bollinger_reversion_signal(current, regime)  # Default to VWAP
    if action == "WAIT":
        action = trend_signal(current, regime)
    return action


# ==============================
# MAIN SIGNAL ENGINE
# ==============================
def calculate_signals(price_list, current_time, position=0, entry_price=0, **kwargs): # Master logic router

    candles_df = kwargs.get("candles_df") # Fetch provided DataFrame from kwargs
    capital = kwargs.get("capital", 100000) # Fetch configured capital
    lot_size = kwargs.get("lot_size", 50) # Fetch configured lot size
    strategy_name = kwargs.get("strategy_name", "strategy_1") # Fetch active strategy selector

    if candles_df is None and (price_list is None or len(price_list) < MIN_SIGNAL_CANDLES): # Sanity check for minimum data
        return {"action": "WAIT"} # Wait for more data

    df = get_base_df(price_list=price_list, candles_df=candles_df) # Process technical indicators

    if len(df) < MIN_SIGNAL_CANDLES: # Confirm again we have enough history post-processing
        return {"action": "WAIT"} # Wait for more data

    current = df.iloc[-1] # Get the current (most recent) candle data

    regime = get_market_regime(df) # Evaluate current market state (-1, 0, 1)
    risk = risk_management(current=current, capital=capital, lot_size=lot_size) # Evaluate dynamic risk parameters

    qty = calculate_position_size( # Calculate safest trade quantity
        price=float(current["price"]), # Current entry price
        stop_loss_pct=risk["stop_loss_pct"], # Risk percentage
        capital=capital, # Total capital limit
        lot_size=lot_size, # Block size
        risk_per_trade_pct=risk["risk_per_trade_pct"], # Risk profile
        max_loss_per_trade_amount=risk["max_loss_per_trade_amount"], # Absolute risk ceiling
        brokerage_fee=risk["brokerage_fee"], # Include costs in sizing
    ) 

    # ================= ENTRY =================
    action = "WAIT" # Default outcome is to do nothing

    if position == 0 and qty > 0: # If we are flat and sized safely
        # Avoid opening new trades too late in the day (after 14:15) to prevent forced DAY_CLOSE losses
        is_too_late = False
        if hasattr(current_time, "hour"):
            market_minute = current_time.hour * 60 + current_time.minute
            if market_minute >= LATEST_ENTRY_MINUTE: # Stop late entries while still allowing trend continuation trades
                is_too_late = True
                
        if not is_too_late:
            action = select_entry_signal(current, regime, strategy_name) # Evaluate configured entry setup

    # ================= EXIT =================
    elif position > 0: # If we are in a LONG trade
        if regime == -1 or current["price"] < current["ema_slow"]: # Bail if trend flips down or we break below Slow EMA (50)
            action = "EXIT_LONG" # Force exit

    elif position < 0: # If we are in a SHORT trade
        if regime == 1 or current["price"] > current["ema_slow"]: # Bail if trend flips up or we break above Slow EMA (50)
            action = "EXIT_SHORT" # Force exit

    return { # Return the calculated action and context parameters for execution
        "action": action, # 'BUY_LONG', 'SELL_SHORT', 'EXIT_LONG', 'EXIT_SHORT', or 'WAIT'
        "price": round(float(current["price"]), 2), # Snapshot price
        "ema_fast": round(float(current["ema_fast"]), 2), # Snapshot Fast EMA
        "ema_mid": round(float(current["ema_mid"]), 2), # Snapshot Mid EMA
        "vwap": round(float(current["vwap"]), 2), # Snapshot VWAP
        "ema_f": round(float(current["ema_fast"]), 2), # Backward-compatible alias used by CSV reports
        "rsi": round(float(current["rsi"]), 2), # Snapshot RSI
        "rsi_fast": round(float(current["rsi"]), 2), # Backward-compatible alias used by CSV reports
        "entry_score": round(float(current.get("rsi", 50.0)), 2), # Provide a metric for reporting
        "atr_pct": round(float(current["atr_pct"]), 5) if pd.notna(current["atr_pct"]) else None, # Snapshot Volatility
        "atr": round(float(current["atr"]), 2) if pd.notna(current["atr"]) else None, # Snapshot ATR points
        "volume_ratio": round(float(current["volume_ratio"]), 2) if pd.notna(current["volume_ratio"]) else None, # Volume participation snapshot
        "regime": regime, # Current Market State
        "strategy_name": strategy_name, # Active strategy selector
        "stop_loss_pct": risk["stop_loss_pct"], # Assigned SL parameter
        "target_pct": risk["target_pct"], # Assigned Target parameter
        "breakeven_pct": risk["breakeven_pct"], # Assigned Breakeven parameter
        "trail_distance": risk["trail_distance"], # Assigned Trailing parameter
        "suggested_qty": qty, # Total Quantity Size
        "brokerage_fee": risk["brokerage_fee"], # Brokerage used for risk checks and PnL
        "max_loss_per_trade_amount": risk["max_loss_per_trade_amount"], # Hard per-trade loss cap
        "daily_loss_limit_pct": risk["daily_loss_limit_pct"], # Session/day circuit breaker
        "profit_protection_start_amount": risk["profit_protection_start_amount"], # Profit protection threshold
        "profit_giveback_pct": risk["profit_giveback_pct"], # Allowed giveback after peak profit
    }
