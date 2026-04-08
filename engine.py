import pandas as pd
import numpy as np

def get_stats(prices):
    if len(prices) < 5: return 0.0, 0.0, 0.0
    y = np.array(prices)
    x = np.arange(len(y))
    slope, _ = np.polyfit(x, y, 1)
    normalized_slope = (slope / y[-1]) * 100
    
    mean = np.mean(y)
    std = np.std(y)
    z_score = (y[-1] - mean) / (std if std != 0 else 0.001)
    
    if len(prices) >= 3:
        recent_slope = prices[-1] - prices[-2]
        prior_slope = prices[-2] - prices[-3]
        velocity = recent_slope - prior_slope
    else:
        velocity = 0
    
    return normalized_slope, z_score, velocity

def get_base_df(price_list):
    df = pd.DataFrame({'price': price_list})
    
    df['ema_fast'] = df['price'].ewm(span=5, adjust=False).mean()
    df['ema_slow'] = df['price'].ewm(span=12, adjust=False).mean()
    df['ema_very_fast'] = df['price'].ewm(span=3, adjust=False).mean()
    
    df['sma_20'] = df['price'].rolling(window=20).mean()
    df['std_20'] = df['price'].rolling(window=20).std()
    df['upper_band'] = df['sma_20'] + (df['std_20'] * 1.5)
    df['lower_band'] = df['sma_20'] - (df['std_20'] * 1.5)
    
    df['percent_b'] = (df['price'] - df['lower_band']) / (df['upper_band'] - df['lower_band'])
    
    delta = df['price'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    delta_fast = df['price'].diff()
    gain_fast = (delta_fast.where(delta_fast > 0, 0)).rolling(window=7).mean()
    loss_fast = (-delta_fast.where(delta_fast < 0, 0)).rolling(window=7).mean()
    rs_fast = gain_fast / (loss_fast + 1e-9)
    df['rsi_fast'] = 100 - (100 / (1 + rs_fast))
    
    df['roc'] = df['price'].pct_change() * 100
    
    return df

def risk_management():
    return {
        "stop_loss_pct": 0.0010,
        "breakeven_pct": 0.0002,
        "target_pct_1": 0.0004,
        "target_pct_2": 0.0006,
        "target_pct_3": 0.0008,
        "brokerage_fee": 60,
        "min_pnl_to_trail": 0.0002,
        "trail_distance": 0.0003,
        "suggested_qty": 100,
    }

def get_market_regime(df):
    """Get market trend: 1=Uptrend, -1=Downtrend, 0=Choppy"""
    if len(df) < 30: return 0
    
    price_now = df['price'].iloc[-1]
    price_30_ago = df['price'].iloc[-30]
    price_change_30 = (price_now - price_30_ago) / price_30_ago
    
    ema_fast = df['ema_fast'].iloc[-1]
    ema_slow = df['ema_slow'].iloc[-1]
    ema_very_fast = df['ema_very_fast'].iloc[-1]
    
    if ema_very_fast > ema_fast > ema_slow and price_change_30 > -0.001:
        return 1
    elif ema_very_fast < ema_fast < ema_slow and price_change_30 < 0.001:
        return -1
    else:
        return 0

# ============================================
# STRATEGY 1: EMA ALIGNMENT
# ============================================
def strategy_1_ema_alignment(current, current_time, entry_price, position, slope, z_score, velocity=0, df=None):
    now_m = current_time.hour * 60 + current_time.minute
    risk = risk_management()
    is_trading_hours = 555 <= now_m <= 915 
    regime = get_market_regime(df) if df is not None else 0

    if position != 0:
        pnl = (current['price'] - entry_price) / entry_price if position > 0 else (entry_price - current['price']) / entry_price
        
        if pnl >= risk['target_pct_3']:
            return "EXIT_SCALE_3"
        if pnl >= risk['target_pct_2']:
            return "EXIT_SCALE_2"
        if pnl >= risk['target_pct_1']:
            return "EXIT_SCALE_1"
        
        if pnl >= risk['min_pnl_to_trail']:
            if position > 0 and velocity < -0.0005:
                return "EXIT_REVERSAL"
            if position < 0 and velocity > 0.0005:
                return "EXIT_REVERSAL"
        
        if pnl <= -risk['stop_loss_pct']:
            return "EXIT_SL"

    if position == 0 and is_trading_hours:
        ema_aligned_long = current['ema_very_fast'] > current['ema_fast'] > current['ema_slow']
        ema_cross_long = (slope > 0.0008 and current['ema_fast'] > current['ema_slow'])
        
        if (ema_aligned_long or ema_cross_long):
            if current['rsi_fast'] > 42 and current['percent_b'] < 0.65 and regime >= 0:
                return "BUY_LONG"
        
        if current['percent_b'] < 0.30 and slope > 0.0010:
            if current['rsi_fast'] > 35 and current['ema_fast'] > current['ema_slow'] and regime >= 0:
                return "BUY_LONG"
        
        ema_aligned_short = current['ema_very_fast'] < current['ema_fast'] < current['ema_slow']
        ema_cross_short = (slope < -0.0008 and current['ema_fast'] < current['ema_slow'])
        
        if (ema_aligned_short or ema_cross_short):
            if current['rsi_fast'] < 58 and current['percent_b'] > 0.35 and regime <= 0:
                return "SELL_SHORT"
        
        if current['percent_b'] > 0.70 and slope < -0.0010:
            if current['rsi_fast'] < 65 and current['ema_fast'] < current['ema_slow'] and regime <= 0:
                return "SELL_SHORT"

    return "WAIT"

# ============================================
# STRATEGY 2: RSI-BASED MEAN REVERSION
# ============================================
def strategy_2_rsi_based(current, current_time, entry_price, position, slope, z_score, velocity=0, df=None):
    now_m = current_time.hour * 60 + current_time.minute
    risk = risk_management()
    is_trading_hours = 555 <= now_m <= 915

    if position != 0:
        pnl = (current['price'] - entry_price) / entry_price if position > 0 else (entry_price - current['price']) / entry_price
        
        if pnl >= risk['target_pct_3']:
            return "EXIT_SCALE_3"
        if pnl >= risk['target_pct_2']:
            return "EXIT_SCALE_2"
        if pnl >= risk['target_pct_1']:
            return "EXIT_SCALE_1"
        
        if position > 0 and current['rsi'] > 70:
            return "EXIT_RSI_OVERBOUGHT"
        if position < 0 and current['rsi'] < 30:
            return "EXIT_RSI_OVERSOLD"
        
        if pnl <= -risk['stop_loss_pct']:
            return "EXIT_SL"

    if position == 0 and is_trading_hours:
        if current['rsi'] < 35 and current['rsi_fast'] > current['rsi']:
            if slope > 0 and current['price'] > current['ema_slow']:
                return "BUY_LONG"
        
        if current['rsi'] < 40 and current['percent_b'] < 0.25 and current['roc'] > 0:
            return "BUY_LONG"
        
        if current['rsi'] > 65 and current['rsi_fast'] < current['rsi']:
            if slope < 0 and current['price'] < current['ema_slow']:
                return "SELL_SHORT"
        
        if current['rsi'] > 60 and current['percent_b'] > 0.75 and current['roc'] < 0:
            return "SELL_SHORT"

    return "WAIT"

# ============================================
# STRATEGY 3: BOLLINGER BANDS
# ============================================
def strategy_3_bollinger_mean_reversion(current, current_time, entry_price, position, slope, z_score, velocity=0, df=None):
    now_m = current_time.hour * 60 + current_time.minute
    risk = risk_management()
    is_trading_hours = 555 <= now_m <= 915

    if position != 0:
        pnl = (current['price'] - entry_price) / entry_price if position > 0 else (entry_price - current['price']) / entry_price
        
        if pnl >= risk['target_pct_3']:
            return "EXIT_SCALE_3"
        if pnl >= risk['target_pct_2']:
            return "EXIT_SCALE_2"
        if pnl >= risk['target_pct_1']:
            return "EXIT_SCALE_1"
        
        if position > 0 and current['price'] >= current['upper_band'] * 0.98:
            return "EXIT_PRICE_TARGET"
        if position < 0 and current['price'] <= current['lower_band'] * 1.02:
            return "EXIT_PRICE_TARGET"
        
        if pnl <= -risk['stop_loss_pct']:
            return "EXIT_SL"

    if position == 0 and is_trading_hours:
        if current['price'] < current['lower_band'] * 1.01 and slope > 0:
            if current['rsi_fast'] > 30:
                return "BUY_LONG"
        
        if current['percent_b'] < 0.15 and current['price'] < current['sma_20'] * 0.99:
            if current['roc'] > -0.05:
                return "BUY_LONG"
        
        if current['price'] > current['upper_band'] * 0.99 and slope < 0:
            if current['rsi_fast'] < 70:
                return "SELL_SHORT"
        
        if current['percent_b'] > 0.85 and current['price'] > current['sma_20'] * 1.01:
            if current['roc'] < 0.05:
                return "SELL_SHORT"

    return "WAIT"

# ============================================
# STRATEGY 4: BREAKOUT & MOMENTUM
# ============================================
def strategy_4_breakout_momentum(current, current_time, entry_price, position, slope, z_score, velocity=0, df=None):
    now_m = current_time.hour * 60 + current_time.minute
    risk = risk_management()
    is_trading_hours = 555 <= now_m <= 915
    regime = get_market_regime(df) if df is not None else 0

    if position != 0:
        pnl = (current['price'] - entry_price) / entry_price if position > 0 else (entry_price - current['price']) / entry_price
        
        if pnl >= risk['target_pct_3']:
            return "EXIT_SCALE_3"
        if pnl >= risk['target_pct_2']:
            return "EXIT_SCALE_2"
        if pnl >= risk['target_pct_1']:
            return "EXIT_SCALE_1"
        
        if velocity < -0.001 and position > 0:
            return "EXIT_MOMENTUM_REVERSAL"
        if velocity > 0.001 and position < 0:
            return "EXIT_MOMENTUM_REVERSAL"
        
        if pnl <= -risk['stop_loss_pct']:
            return "EXIT_SL"

    if position == 0 and is_trading_hours:
        if slope > 0.0015 and velocity > 0.0005:
            if current['rsi_fast'] > 50 and current['roc'] > 0.08 and (regime >= 0 or regime == 0):
                return "BUY_LONG"
        
        if current['price'] > current['ema_fast'] and current['ema_fast'] > current['ema_slow']:
            if slope > 0.001 and current['rsi'] > 55:
                return "BUY_LONG"
        
        if slope < -0.0015 and velocity < -0.0005:
            if current['rsi_fast'] < 50 and current['roc'] < -0.08 and (regime <= 0 or regime == 0):
                return "SELL_SHORT"
        
        if current['price'] < current['ema_fast'] and current['ema_fast'] < current['ema_slow']:
            if slope < -0.001 and current['rsi'] < 45:
                return "SELL_SHORT"

    return "WAIT"

# ============================================
# STRATEGY SELECTOR
# ============================================
STRATEGIES = {
    "strategy_1": strategy_1_ema_alignment,
    "strategy_2": strategy_2_rsi_based,
    "strategy_3": strategy_3_bollinger_mean_reversion,
    "strategy_4": strategy_4_breakout_momentum
}

def calculate_signals(price_list, current_time, position=0, entry_price=0, strategy_name="strategy_1", **kwargs):
    if len(price_list) < 20: 
        return {"action": "WAIT"}
    
    slope, z_score, velocity = get_stats(price_list[-10:])
    df = get_base_df(price_list)
    current = df.iloc[-1]
    risk = risk_management()
    regime = get_market_regime(df)
    
    strategy_func = STRATEGIES.get(strategy_name, strategy_1_ema_alignment)
    action = strategy_func(current, current_time, entry_price, position, slope, z_score, velocity, df)
    
    return {
        "action": action, 
        "price": round(float(current['price']), 2),
        "rsi": round(float(df['rsi'].iloc[-1]), 2),
        "rsi_fast": round(float(df['rsi_fast'].iloc[-1]), 2),
        "ema_f": round(float(current['ema_fast']), 2),
        "slope": round(slope, 4),
        "z_score": round(z_score, 2),
        "regime": regime,
        "stop_loss_pct": risk['stop_loss_pct'],
        "target_pct": risk['target_pct_1'],
        "brokerage_fee": risk['brokerage_fee'],
        "strategy": strategy_name
    }
