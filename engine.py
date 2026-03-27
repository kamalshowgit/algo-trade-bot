# engine.py
import pandas as pd
import numpy as np

def get_base_df(price_list):
    """Processes technical indicators for all strategies"""
    df = pd.DataFrame(price_list, columns=['price'])
    
    # Standard Moving Averages
    df['ma_20'] = df['price'].rolling(window=20).mean()
    df['std_20'] = df['price'].rolling(window=20).std()
    df['ma_50'] = df['price'].rolling(window=50).mean()
    
    # RSI Calculation
    delta = df['price'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, np.nan))))
    df['rsi'] = df['rsi'].fillna(50) # Neutral RSI if no movement
    
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
def strategy_moderate(current):
    """
    Designed for 5-minute charts to yield 2-3 trades per day.
    Uses Trend-Aligned Mean Reversion.
    """
    upper = current['ma_20'] + (current['std_20'] * 2)
    lower = current['ma_20'] - (current['std_20'] * 2)
    
    # Determine the intraday trend using the 50 MA
    is_uptrend = current['ma_20'] > current['ma_50']
    is_downtrend = current['ma_20'] < current['ma_50']
    
    # BUY: In an uptrend, buy the 2-Standard Deviation dip when RSI cools off.
    if is_uptrend and (current['price'] <= lower) and (current['rsi'] <= 45):
        return "BUY"
        
    # SELL: In a downtrend, short the 2-Standard Deviation rip when RSI is warm.
    elif is_downtrend and (current['price'] >= upper) and (current['rsi'] >= 55):
        return "SELL"
        
    return "WAIT"

# --- MAIN DISPATCHER ---
def calculate_signals(price_list, strategy_name="moderate"):
    if len(price_list) < 50:
        return {"action": "WAIT", "rsi": 50, "ma": 0}
    
    df = get_base_df(price_list)
    current = df.iloc[-1]
    
    if strategy_name == "sniper":
        action = strategy_sniper(current)
    elif strategy_name == "scalper":
        action = strategy_scalper(current)
    elif strategy_name == "moderate":
        action = strategy_moderate(current)
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
        "stop_loss_pct": 0.005,  # Tightened to 0.5% for intraday safety
        "target_pct": 0.01,      # 1% target (easily covers the Rs 50 goal)
        "brokerage_fee": 60 
    }