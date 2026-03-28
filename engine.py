"""
FILE: engine.py
AUTHOR: Kamal Soni
VERSION: 7.0 (Backtest-Ready)
"""
import pandas as pd
import numpy as np

def get_base_df(price_list, volume_list=None):
    df = pd.DataFrame(price_list, columns=['price'])
    # In backtests, volume is often missing from Index data, so we bypass
    df['volume'] = volume_list if volume_list else 1.0
    df['vol_ma'] = df['volume'].rolling(window=20).mean() if volume_list else 1.0
    
    df['ema_9']  = df['price'].ewm(span=9,  adjust=False).mean()
    df['ema_21'] = df['price'].ewm(span=21, adjust=False).mean()
    
    delta = df['price'].diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df['rsi'] = (100 - (100 / (1 + (avg_gain / avg_loss.replace(0, np.nan))))).fillna(50)
    return df

def strategy_moderate(current, current_time=None):
    # LOOSENED: 1.1x Volume instead of 1.5x
    # Removed EMA-50 requirement for more trades
    is_uptrend   = (current['ema_9'] > current['ema_21'])
    is_downtrend = (current['ema_9'] < current['ema_21'])
    
    if is_uptrend and (current['price'] <= current['ema_9'] * 1.001) and current['rsi'] > 45:
        return "BUY_LONG"
    elif is_downtrend and (current['price'] >= current['ema_9'] * 0.999) and current['rsi'] < 55:
        return "SELL_SHORT"
    return "WAIT"

def risk_management(capital=None):
    cap = capital if capital else 100000
    return {
        "position_size": cap,
        "stop_loss_pct": 0.0020, # 0.2% SL
        "target_pct": 0.0050,    # 0.5% TP (Aggressive)
        "brokerage_fee": 60,
        "daily_loss_limit": cap * 0.015
    }

def calculate_signals(price_list, volume_list=None, current_pnl=0, capital=None, current_time=None, strategy_name="moderate"):
    # Basic guard
    if len(price_list) < 30: return {"action": "WAIT", "price": 0}
    
    df = get_base_df(price_list, volume_list)
    current = df.iloc[-1]
    action = strategy_moderate(current, current_time)
    
    return {
        "action": action, 
        "price": round(float(current['price']), 2),
        "rsi": round(float(current['rsi']), 2),
        "ma": round(float(current['ema_21']), 2) # used for logging
    }