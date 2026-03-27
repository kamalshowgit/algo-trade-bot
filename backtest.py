import yfinance as yf
import pandas as pd
import numpy as np
from engine import get_base_df, calculate_signals

# --- 2026 SETTINGS ---
LOT_SIZE = 65  # NSE Revised Lot Size as of Jan 2026
COSTS_PER_TRADE = 120  # Total Brokerage + STT + Taxes (Est)
MIN_NET_PROFIT = 50.0 

def run_backtest(symbol="^NSEI", years=3, strategy="scalper"):
    # 1. Fetch 3 Years of Data
    print(f"Fetching {years} years of data for {symbol}...")
    df = yf.download(symbol, period=f"{years}y", interval="1d")
    
    # 2. Process Indicators using your engine.py function
    # Note: engine.py expects a list/array of prices
    df_processed = get_base_df(df['Close'].values)
    df_processed.index = df.index
    
    # 3. Vectorized Signal Generation (Applying your logic)
    # We simulate the "current" row for each day in history
    signals = []
    for i in range(len(df_processed)):
        if i < 50: # Warm up period for MA 50
            signals.append("WAIT")
            continue
            
        price_slice = df_processed['price'].iloc[:i+1].values
        res = calculate_signals(price_slice, strategy_name=strategy)
        signals.append(res['action'])
    
    df_processed['signal'] = signals
    
    # 4. P&L Calculation
    # We "Buy" on the signal day's Close and "Sell" on the next day's Open (Simple model)
    df_processed['next_open'] = df_processed['price'].shift(-1)
    trades = df_processed[df_processed['signal'] == 'BUY'].copy()
    
    if trades.empty:
        return "No trades triggered."

    # Gross Profit = (Exit Price - Entry Price) * Lot Size
    trades['gross_pnl'] = (trades['next_open'] - trades['price']) * LOT_SIZE
    trades['net_pnl'] = trades['gross_pnl'] - COSTS_PER_TRADE
    
    # Summary Stats
    total_trades = len(trades)
    win_rate = (trades['net_pnl'] > 0).sum() / total_trades * 100
    total_profit = trades['net_pnl'].sum()
    
    print(f"\n--- BACKTEST RESULTS: {strategy.upper()} ---")
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Net P&L: ₹{total_profit:,.2f}")
    print(f"Avg Profit per Trade: ₹{trades['net_pnl'].mean():.2f}")
    
    return trades

if __name__ == "__main__":
    # Test your Scalper strategy
    results = run_backtest(strategy="scalper")