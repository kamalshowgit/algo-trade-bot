# engine.py
import pandas as pd
import numpy as np

def get_base_df(price_list):
    """Processes technical indicators for all strategies"""
    
    # Process enough rows for the 50 EMA to smooth out
    if len(price_list) > 150:
        price_list = price_list[-150:]
        
    df = pd.DataFrame(price_list, columns=['price'])
    
    # 1. UPGRADE: Switch from Simple to Exponential Moving Averages (EMAs)
    # EMAs react much faster to recent price changes, crucial for 5-min charts.
    df['ema_9'] = df['price'].ewm(span=9, adjust=False).mean()
    df['ema_21'] = df['price'].ewm(span=21, adjust=False).mean()
    df['ema_50'] = df['price'].ewm(span=50, adjust=False).mean()
    
    # Legacy indicators for Sniper/Scalper
    df['ma_20'] = df['price'].rolling(window=20).mean()
    df['std_20'] = df['price'].rolling(window=20).std()
    
    # RSI Calculation
    delta = df['price'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, np.nan))))
    df['rsi'] = df['rsi'].fillna(50) 
    
    return df

# --- STRATEGY 1: 95% PRECISION (The "Sniper") ---
def strategy_sniper(current):
    # Kept intact as requested
    upper = current['ma_20'] + (current['std_20'] * 3)
    lower = current['ma_20'] - (current['std_20'] * 3)
    potential_profit = abs(current['ma_20'] - current['price']) / current['price']
    
    if potential_profit < 0.012: return "WAIT"
    if current['price'] < lower and current['rsi'] < 25: return "BUY"
    elif current['price'] > upper and current['rsi'] > 75: return "SELL"
    return "WAIT"

# --- STRATEGY 2: QUICK SCALP ---
def strategy_scalper(current):
    # Kept intact as requested
    upper = current['ma_20'] + (current['std_20'] * 2)
    lower = current['ma_20'] - (current['std_20'] * 2)
    
    if current['price'] < lower and current['rsi'] < 35: return "BUY"
    elif current['price'] > upper and current['rsi'] > 65: return "SELL"
    return "WAIT"

# --- STRATEGY 3: MODERATE INTRADAY (The "Momentum Pullback") ---
def strategy_moderate(current, current_time=None):
    """
    Rides existing intraday trends. 
    Waits for a strong trend, then buys small pullbacks to the 9 EMA.
    """
    if current_time is not None:
        if current_time.hour == 9 and current_time.minute < 30: return "WAIT"
        if current_time.hour >= 15: return "WAIT"

    # Define the trend using fast EMAs
    is_uptrend = (current['ema_21'] > current['ema_50'])
    is_downtrend = (current['ema_21'] < current['ema_50'])
    
    # BUY: In an uptrend, wait for price to dip to the 9 EMA, but stay above 21 EMA
    if is_uptrend and (current['price'] <= current['ema_9']) and (current['price'] > current['ema_21']):
        if current['rsi'] > 50: # Ensure overall momentum is still bullish
            return "BUY"
            
    # SELL: In a downtrend, wait for price to bounce up to 9 EMA, but stay below 21 EMA
    elif is_downtrend and (current['price'] >= current['ema_9']) and (current['price'] < current['ema_21']):
        if current['rsi'] < 50: # Ensure overall momentum is still bearish
            return "SELL"
        
    return "WAIT"

# --- MAIN DISPATCHER ---
def calculate_signals(price_list, current_time=None, strategy_name="moderate"):
    if len(price_list) < 50:
        return {"action": "WAIT", "rsi": 50, "price": 0}
    
    df = get_base_df(price_list)
    current = df.iloc[-1]
    
    if strategy_name == "sniper": action = strategy_sniper(current)
    elif strategy_name == "scalper": action = strategy_scalper(current)
    elif strategy_name == "moderate": action = strategy_moderate(current, current_time)
    else: action = "WAIT"

    return {
        "action": action,
        "price": round(current['price'], 2)
    }

def risk_management(capital):
    # REALITY CHECK FOR NIFTY 5-MIN SCALPING
    # On a 23,000 Nifty:
    # 0.06% = ~14 points (Tight stop loss to cut bad entries instantly)
    # 0.12% = ~28 points (Highly achievable target for a 5-min momentum burst)
    return {
        "position_size": capital,
        "stop_loss_pct": 0.0006,  
        "target_pct": 0.0012,     
        "brokerage_fee": 120      
    }