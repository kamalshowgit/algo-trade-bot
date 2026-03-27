import yfinance as yf
import pandas as pd
from engine import calculate_signals, risk_management

# --- SETTINGS ---
LOT_SIZE = 65  
CAPITAL = 100000

def run_true_backtest(symbol="^NSEI", days=60, strategy="moderate"):
    # Fetching 60 days of 5-minute data (Max allowed by free YFinance)
    print(f"Fetching {days} days of 5-minute data for {symbol}...")
    df = yf.download(symbol, period=f"{days}d", interval="5m")
    
    if df.empty:
        print("Failed to fetch data.")
        return

    prices = df['Close'].values
    timestamps = df.index
    
    # Pull Risk Rules directly from engine.py
    risk_rules = risk_management(CAPITAL)
    sl_pct = risk_rules['stop_loss_pct']   
    tp_pct = risk_rules['target_pct']      
    brokerage = risk_rules['brokerage_fee'] 

    trades = []
    in_position = False
    entry_price = 0.0
    position_type = ""
    entry_time = None

    print(f"Simulating live market for {strategy} strategy...")
    
    # Loop through the data chronologically (The Time Machine)
    for i in range(50, len(prices)):
        current_price = prices[i]
        current_time = timestamps[i]

        # --- STATE 1: HOLDING A POSITION ---
        if in_position:
            exit_triggered = False
            reason = ""
            
            # Intraday Hard Exit at 3:15 PM (15:15)
            if current_time.hour == 15 and current_time.minute >= 15:
                exit_triggered, reason = True, "Time Square-Off (3:15 PM)"
            
            # Check Target and Stop Loss conditions
            elif position_type == "BUY":
                if current_price >= entry_price * (1 + tp_pct):
                    exit_triggered, reason = True, "Target Hit"
                elif current_price <= entry_price * (1 - sl_pct):
                    exit_triggered, reason = True, "Stop Loss Hit"
                    
            elif position_type == "SELL":
                if current_price <= entry_price * (1 - tp_pct):
                    exit_triggered, reason = True, "Target Hit"
                elif current_price >= entry_price * (1 + sl_pct):
                    exit_triggered, reason = True, "Stop Loss Hit"

            if exit_triggered:
                points = (current_price - entry_price) if position_type == "BUY" else (entry_price - current_price)
                gross_pnl = points * LOT_SIZE
                net_pnl = gross_pnl - brokerage
                
                trades.append({
                    "Entry Time": entry_time,
                    "Exit Time": current_time,
                    "Type": position_type,
                    "Entry Price": round(entry_price, 2),
                    "Exit Price": round(current_price, 2),
                    "Points": round(points, 2),
                    "Net PnL": round(net_pnl, 2),
                    "Reason": reason
                })
                in_position = False 
            continue 

        # --- STATE 2: LOOKING FOR A TRADE ---
        # Feed the historical slice up to the current minute to the engine
        price_slice = prices[:i+1]
        
        # Pass current_time to the engine so it knows when to stop trading
        signal_data = calculate_signals(price_slice, current_time=current_time, strategy_name=strategy)
        
        if signal_data['action'] in ["BUY", "SELL"]:
            in_position = True
            position_type = signal_data['action']
            entry_price = current_price
            entry_time = current_time

    # --- COMPILE RESULTS ---
    results_df = pd.DataFrame(trades)
    if results_df.empty:
        print(f"No trades triggered by {strategy} in the last {days} days.")
        return

    csv_name = f"{strategy}_backtest.csv"
    results_df.to_csv(csv_name, index=False)
    
    win_rate = (results_df['Net PnL'] > 0).mean() * 100
    total_pnl = results_df['Net PnL'].sum()
    
    print("\n--- BACKTEST RESULTS ---")
    print(f"Total Trades: {len(results_df)}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total Net PnL: ₹{total_pnl:,.2f}")
    print(f"✅ Trade log saved to: {csv_name}")

if __name__ == "__main__":
    run_true_backtest(strategy="moderate")