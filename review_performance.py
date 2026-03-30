import pandas as pd
import os

def analyze_trades():
    file_path = "paper_trade_history.csv"
    
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        print("❌ No trade data found.")
        return

    df = pd.read_csv(file_path)
    
    # ── COLUMN CLEANING ───────────────────────────────────────────────────
    # This strip() removes hidden spaces that often cause KeyErrors
    df.columns = [c.strip() for c in df.columns]
    
    # Check if RSI column exists under different possible names
    rsi_col = next((c for c in ["RSI_Value", "RSI", "rsi_value"] if c in df.columns), None)
    
    # ── STATUS CHECK ──────────────────────────────────────────────────────
    # If the last row is a 'BUY', we are in an open position
    last_row = df.iloc[-1]
    if last_row['Side'] in ['BUY', 'BUY_LONG', 'SELL_SHORT']:
        print("\n⏳ STATUS: Position currently OPEN.")
        entry_price = last_row['Price']
        # Use the rsi_col we found to avoid the KeyError
        rsi_val = last_row[rsi_col] if rsi_col else "N/A"
        print(f"   Current Entry: ₹{entry_price} | Entry RSI: {rsi_val}")
        
        # We drop the last row for the rest of the P&L math so it doesn't break
        df = df.iloc[:-1]

    if df.empty:
        print("📊 No completed trades to analyze yet.")
        return

    # ── P&L MATH ──────────────────────────────────────────────────────────
    total_net_pnl = df['Total_PnL'].iloc[-1]
    win_rate = (df['Trade_PnL'] > 0).mean() * 100
    
    print(f"\n✅ COMPLETED TRADES AUDIT")
    print(f"   Total Net P&L: ₹{total_net_pnl:,.2f}")
    print(f"   Win Rate:      {win_rate:.1f}%")
    print(f"   Total Trades:  {len(df)}")