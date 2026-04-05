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
        "stop_loss_pct": 0.0010,       # 0.10%
        "target_pct_1": 0.0004,        # 0.04% (SMALL SCALP)
        "target_pct_2": 0.0006,        # 0.06% (MEDIUM SCALP)
        "target_pct_3": 0.0008,        # 0.08% (NORMAL EXIT)
        "brokerage_fee": 60,
        "min_pnl_to_trail": 0.0002,    # Trail at +0.02%
        "trail_distance": 0.0003,      # Trail 0.03% behind
        "suggested_qty": 100,
    }

def get_market_regime(df):
    """Get market trend: 1=Uptrend, -1=Downtrend, 0=Choppy"""
    if len(df) < 30: return 0
    
    # Check recent trend (last 30 candles)
    price_now = df['price'].iloc[-1]
    price_30_ago = df['price'].iloc[-30]
    price_change_30 = (price_now - price_30_ago) / price_30_ago
    
    # EMA configuration
    ema_fast = df['ema_fast'].iloc[-1]
    ema_slow = df['ema_slow'].iloc[-1]
    ema_very_fast = df['ema_very_fast'].iloc[-1]
    
    # Simple but effective: EMA stacking + Price trend alignment
    if ema_very_fast > ema_fast > ema_slow and price_change_30 > -0.001:
        return 1  # UPTREND
    elif ema_very_fast < ema_fast < ema_slow and price_change_30 < 0.001:
        return -1  # DOWNTREND
    else:
        return 0  # CHOPPY - just slight movement or mixed signals

def strategy_logic(current, current_time, entry_price, position, slope, z_score, velocity=0, df=None):
    now_m = current_time.hour * 60 + current_time.minute
    risk = risk_management()
    
    is_trading_hours = 555 <= now_m <= 915 
    
    # Get market regime but don't use it as hard filter
    regime = get_market_regime(df) if df is not None else 0

    if position != 0:
        pnl = (current['price'] - entry_price) / entry_price if position > 0 else (entry_price - current['price']) / entry_price
        
        # QUICK SCALING EXITS  
        if pnl >= risk['target_pct_1']:
            return "EXIT_SCALE_1"
        if pnl >= risk['target_pct_2']:
            return "EXIT_SCALE_2"
        if pnl >= risk['target_pct_3']:
            return "EXIT_SCALE_3"
        
        # Momentum reversal exit
        if pnl >= risk['min_pnl_to_trail']:
            if position > 0 and velocity < -0.0005:
                return "EXIT_REVERSAL"
            if position < 0 and velocity > 0.0005:
                return "EXIT_REVERSAL"
        
        # TIGHT STOP LOSS
        if pnl <= -risk['stop_loss_pct']:
            return "EXIT_SL"

    if position == 0 and is_trading_hours:
        
        # === ENTRY SIGNALS - EMA ALIGNMENT OR CROSSOVER ===
        
        # LONG: EMA stack OR fast crossing slow
        ema_aligned_long = current['ema_very_fast'] > current['ema_fast'] > current['ema_slow']
        ema_cross_long = (slope > 0.0008 and current['ema_fast'] > current['ema_slow'])
        
        if (ema_aligned_long or ema_cross_long):
            if current['rsi_fast'] > 42:
                if current['percent_b'] < 0.65:
                    if regime >= 0:  # Allow in uptrend or neutral
                        return "BUY_LONG"
        
        # LONG: Reversal from lower band
        if current['percent_b'] < 0.30 and slope > 0.0010:
            if current['rsi_fast'] > 35 and current['ema_fast'] > current['ema_slow']:
                if regime >= 0:
                    return "BUY_LONG"
        
        # SHORT: EMA stack OR fast crossing slow
        ema_aligned_short = current['ema_very_fast'] < current['ema_fast'] < current['ema_slow']
        ema_cross_short = (slope < -0.0008 and current['ema_fast'] < current['ema_slow'])
        
        if (ema_aligned_short or ema_cross_short):
            if current['rsi_fast'] < 58:
                if current['percent_b'] > 0.35:
                    if regime <= 0:  # Allow in downtrend or neutral
                        return "SELL_SHORT"
        
        # SHORT: Reversal from upper band
        if current['percent_b'] > 0.70 and slope < -0.0010:
            if current['rsi_fast'] < 65 and current['ema_fast'] < current['ema_slow']:
                if regime <= 0:
                    return "SELL_SHORT"

    return "WAIT"

def calculate_signals(price_list, current_time, position=0, entry_price=0, **kwargs):
    if len(price_list) < 20: return {"action": "WAIT"}
    
    slope, z_score, velocity = get_stats(price_list[-10:])
    
    df = get_base_df(price_list)
    current = df.iloc[-1]
    risk = risk_management()
    regime = get_market_regime(df)
    
    action = strategy_logic(current, current_time, entry_price, position, slope, z_score, velocity, df)
    
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
        "brokerage_fee": risk['brokerage_fee']
    }
