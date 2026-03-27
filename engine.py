# engine.py
import pandas as pd
import numpy as np

def get_base_df(price_list):
    """Processes technical indicators for all strategies"""
    
    # 1. EXPANDED WINDOW: Increased to 300 to allow the 200 MA to calculate
    if len(price_list) > 300:
        price_list = price_list[-300:]
        
    df = pd.DataFrame(price_list, columns=['price'])
    
    # Standard Moving Averages
    df['ma_20'] = df['price'].rolling(window=20).mean()
    df['std_20'] = df['price'].rolling(window=20).std()
    df['ma_50'] = df['price'].rolling(window=50).mean()
    
    # The Institutional Filter
    df['ma_200'] = df['price'].rolling(window=200).mean()
    
    # RSI Calculation
    delta = df['price'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, np.nan))))
    df['rsi'] = df['rsi'].fillna(50) 
    
    return df

# --- STRATEGY 1: 95% PRECISION (The "Sniper") ---
def strategy_sniper(current):
    upper = current['ma_20'] + (current['std_20'] * 3)
    lower = current['ma_20'] - (current['std_20'] * 3)
    
    potential_profit = abs(current['ma_20'] - current['price']) / current['price']
    if potential_profit < 0.012:
        return "WAIT"

    if current['price'] < lower and current['rsi'] < 25 and current['price'] > current['ma_50']:
        return "BUY"
    elif current['price'] > upper and current['rsi'] > 75 and current['price'] < current['ma_50']:
        return "SELL"
    return "WAIT"

# --- STRATEGY 2: QUICK SCALP ---
def strategy_scalper(current):
    upper = current['ma_20'] + (current['std_20'] * 2)
    lower = current['ma_20'] - (current['std_20'] * 2)
    
    if current['price'] < lower and current['rsi'] < 35:
        return "BUY"
    elif current['price'] > upper and current['rsi'] > 65:
        return "SELL"
    return "WAIT"

# --- STRATEGY 3: MODERATE INTRADAY (The "Active Trader") ---
def strategy_moderate(current, current_time=None):
    """
    Yields highly filtered, realistic intraday trades.
    Uses 200 MA for macro-trend alignment and RSI 35/65 for exhaustion.
    """
    if current_time is not None:
        # Avoid morning volatility and afternoon square-off risks
        if current_time.hour == 9 and current_time.minute < 30:
            return "WAIT"
        if current_time.hour >= 15:
            return "WAIT"

    upper = current['ma_20'] + (current['std_20'] * 2)
    lower = current['ma_20'] - (current['std_20'] * 2)
    
    # 2. MACRO TREND FILTER: Price must respect the 200 MA hierarchy
    is_uptrend = (current['ma_20'] > current['ma_50']) and (current['ma_50'] > current['ma_200'])
    is_downtrend = (current['ma_20'] < current['ma_50']) and (current['ma_50'] < current['ma_200'])
    
    # 3. STRICT PULLBACK: Ensures the dip is actually overextended
    if is_uptrend and (current['price'] <= lower) and (current['rsi'] <= 35):
        return "BUY"
    elif is_downtrend and (current['price'] >= upper) and (current['rsi'] >= 65):
        return "SELL"
        
    return "WAIT"

# --- MAIN DISPATCHER ---
def calculate_signals(price_list, current_time=None, strategy_name="moderate"):
    # Require enough data for the 200 MA to initialize
    if len(price_list) < 200:
        return {"action": "WAIT", "rsi": 50, "ma": 0}
    
    df = get_base_df(price_list)
    current = df.iloc[-1]
    
    if strategy_name == "sniper":
        action = strategy_sniper(current)
    elif strategy_name == "scalper":
        action = strategy_scalper(current)
    elif strategy_name == "moderate":
        action = strategy_moderate(current, current_time)
    else:
        action = "WAIT"

    return {
        "action": action,
        "price": round(current['price'], 2),
        "rsi": round(current['rsi'], 2),
        "ma": round(current['ma_20'], 2),
        "upper": round(current['ma_20'] + (current['std_20'] * 2), 2),
        "lower": round(current['ma_20'] - (current['std_20'] * 2), 2)
    }

def risk_management(capital):
    return {
        "position_size": capital,
        "stop_loss_pct": 0.0015,  # ~35 points: Escapes 5-minute market noise
        "target_pct": 0.0030,     # ~70 points: 1:2 Risk/Reward ratio
        "brokerage_fee": 120      
    }