# engine.py
import pandas as pd
import numpy as np

def get_base_df(price_list):
    """Processes technical indicators for all strategies"""
    df = pd.DataFrame(price_list, columns=['price'])
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
    
    # 1.2% move requirement to clear ₹60 brokerage
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

# --- MAIN DISPATCHER ---
def calculate_signals(price_list, strategy_name="sniper"):
    if len(price_list) < 50:
        return {"action": "WAIT", "rsi": 50, "ma": 0}
    
    df = get_base_df(price_list)
    current = df.iloc[-1]
    
    if strategy_name == "sniper":
        action = strategy_sniper(current)
    elif strategy_name == "scalper":
        action = strategy_scalper(current)
    else:
        action = "WAIT"

    # Returning a DICTIONARY so main.py has full data
    return {
        "action": action,
        "price": round(current['price'], 2),
        "rsi": round(current['rsi'], 2),
        "ma": round(current['ma_20'], 2),
        "upper": round(current['ma_20'] + (current['std_20'] * (3 if strategy_name=="sniper" else 2)), 2),
        "lower": round(current['ma_20'] - (current['std_20'] * (3 if strategy_name=="sniper" else 2)), 2)
    }

def risk_management(capital):
    return {
        "position_size": capital,
        "stop_loss_pct": 0.01,  
        "target_pct": 0.02,
        "brokerage_fee": 60 
    }