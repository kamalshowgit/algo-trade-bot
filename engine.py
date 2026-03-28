"""
FILE: engine.py
AUTHOR: Kamal Soni
VERSION: 8.0 (Nifty-F&O Optimized)
"""
import pandas as pd
import numpy as np

def get_base_df(price_list, volume_list=None):
    df = pd.DataFrame(price_list, columns=['price'])
    
    # --- F&O VOLUME HANDLING ---
    if volume_list and len(volume_list) == len(price_list):
        df['volume'] = volume_list
    else:
        df['volume'] = 1.0 # Fallback only if API fails
        
    df['vol_ma'] = df['volume'].rolling(window=20).mean()
    
    # --- EMA STACK ---
    df['ema_9']  = df['price'].ewm(span=9,  adjust=False).mean()
    df['ema_21'] = df['price'].ewm(span=21, adjust=False).mean()
    
    # --- WILDER'S RSI (The Nifty Standard) ---
    delta = df['price'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Wilder's uses alpha = 1/period
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = (100 - (100 / (1 + rs))).fillna(50)
    return df

def strategy_moderate(current, current_time=None):
    """
    Nifty F&O High-Yield Strategy
    Logic: EMA Pullback + RSI Confirmation
    """
    # 1. Trend Definition
    is_uptrend   = (current['ema_9'] > current['ema_21'])
    is_downtrend = (current['ema_9'] < current['ema_21'])
    
    # 2. Timing Guard (9:20 AM - 3:15 PM)
    if current_time:
        now_m = current_time.hour * 60 + current_time.minute
        if now_m < (9 * 60 + 20) or now_m > (15 * 60 + 15):
            return "WAIT"

    # --- LONG ENTRY (Buy the Dip) ---
    if is_uptrend:
        # Price within 0.1% of EMA-9 and RSI shows strength (>45)
        if (current['price'] <= current['ema_9'] * 1.001) and current['rsi'] > 45:
            return "BUY_LONG"
            
    # --- SHORT ENTRY (Sell the Rip) ---
    elif is_downtrend:
        # Price within 0.1% of EMA-9 bounce and RSI shows weakness (<55)
        if (current['price'] >= current['ema_9'] * 0.999) and current['rsi'] < 55:
            return "SELL_SHORT"

    # --- TECHNICAL EXITS ---
    if is_downtrend and current['rsi'] > 65: return "EXIT_LONG"
    if is_uptrend and current['rsi'] < 35: return "EXIT_SHORT"
    
    return "WAIT"

def risk_management(capital=None):
    cap = capital if capital else 100000
    return {
        "position_size": cap,
        "stop_loss_pct": 0.0020,  # 0.2% (~45 Nifty Points)
        "target_pct": 0.0050,     # 0.5% (~110 Nifty Points)
        "brokerage_fee": 60,      # Flat fee for Nifty Futures
        "daily_loss_limit": cap * 0.015 # 1.5% Circuit Breaker
    }

def calculate_signals(price_list, volume_list=None, current_pnl=0, capital=None, current_time=None, strategy_name="moderate"):
    # Guard against insufficient data for EMA-21
    if len(price_list) < 25: 
        return {"action": "WAIT", "price": 0, "rsi": 50, "ma": 0}
    
    # Portfolio Circuit Breaker
    risk = risk_management(capital)
    if current_pnl <= -risk['daily_loss_limit']:
        return {"action": "STOP_FOR_DAY", "price": 0, "rsi": 50, "ma": 0}

    df = get_base_df(price_list, volume_list)
    current = df.iloc[-1]
    
    action = strategy_moderate(current, current_time)
    
    return {
        "action": action, 
        "price": round(float(current['price']), 2),
        "rsi": round(float(current['rsi']), 2),
        "ma": round(float(current['ema_21']), 2)
    }