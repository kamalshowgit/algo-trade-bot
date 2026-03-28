import yfinance as yf
import pandas as pd
import numpy as np
from engine import calculate_signals, risk_management

# --- SCALABLE FRAMEWORK SETTINGS ---
SYMBOL = "^NSEI" 
DAYS = 59
INTERVAL = "5m"

def run_pure_harness():
    print(f"--- 🛠️ STARTING PURE LOGIC HARNESS: {SYMBOL} ---")
    
    # 1. FETCH DATA (Source of Truth)
    df = yf.download(SYMBOL, period=f"{DAYS}d", interval=INTERVAL)
    if df.empty: return
    
    # Cleanup for yfinance Multi-Index
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    prices = df['Close'].values.flatten().tolist()
    volumes = df['Volume'].values.flatten().tolist()
    timestamps = df.index

    # 2. IMPORT PARAMETERS (Everything from Engine)
    # No hardcoding here; we trust engine.py for these numbers
    params = risk_management() 
    CAPITAL = params['position_size']
    LOT_SIZE = 50 # Nifty Lot constant
    
    trades = []
    in_position = False
    pos_type = ""
    entry_price = 0.0
    entry_time = None
    daily_pnl = 0
    current_day = None

    print(f"🚀 Running Framework with ₹{CAPITAL} Capital...")

    # 3. THE EXECUTION LOOP
    for i in range(70, len(prices)):
        now_price = float(prices[i])
        now_time = timestamps[i]
        
        # Reset Daily PnL tracker for Circuit Breaker logic
        if current_day != now_time.date():
            current_day = now_time.date()
            daily_pnl = 0

        # --- LOGIC LAYER 1: EXIT MANAGEMENT ---
        if in_position:
            # We call the engine to see if an EXIT signal is generated
            # or if we need to square off for the day
            signal_data = calculate_signals(
                price_list=prices[i-65:i+1],
                volume_list=volumes[i-65:i+1],
                current_pnl=daily_pnl,
                capital=CAPITAL,
                current_time=now_time
            )
            
            exit_signal = signal_data['action']
            
            # Check for Target/Stop Loss using Engine's percentages
            is_sl = (pos_type == "LONG" and now_price <= entry_price * (1 - params['stop_loss_pct'])) or \
                    (pos_type == "SHORT" and now_price >= entry_price * (1 + params['stop_loss_pct']))
            
            is_tp = (pos_type == "LONG" and now_price >= entry_price * (1 + params['target_pct'])) or \
                    (pos_type == "SHORT" and now_price <= entry_price * (1 - params['target_pct']))

            # Logic-based exit or Risk-based exit
            if exit_signal in ["EXIT_LONG", "EXIT_SHORT", "STOP_FOR_DAY"] or is_sl or is_tp:
                # Use the engine's "Price" which already includes SLIPPAGE
                exit_price = signal_data['price'] 
                
                points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                net_pnl = (points * LOT_SIZE) - params['brokerage_fee']
                daily_pnl += net_pnl
                
                trades.append({
                    "Time": now_time,
                    "Type": pos_type,
                    "Entry": round(entry_price, 2),
                    "Exit": round(exit_price, 2),
                    "Net_PnL": round(net_pnl, 2),
                    "Condition": exit_signal if "EXIT" in exit_signal else "Risk/Target"
                })
                in_position = False
            continue

        # --- LOGIC LAYER 2: ENTRY SEARCH ---
        # Direct call to engine.py
        signal_data = calculate_signals(
            price_list=prices[i-65:i+1],
            volume_list=volumes[i-65:i+1],
            current_pnl=daily_pnl,
            capital=CAPITAL,
            current_time=now_time
        )

        if signal_data['action'] in ["BUY_LONG", "SELL_SHORT"]:
            in_position = True
            pos_type = "LONG" if "BUY" in signal_data['action'] else "SHORT"
            entry_price = signal_data['price'] # Engine handles the slippage on entry
            entry_time = now_time

    # 4. REPORTING
    if trades:
        res_df = pd.DataFrame(trades)
        print("\n" + "="*40)
        print(f"FINAL AUDIT: ₹{res_df['Net_PnL'].sum():,.2f} Total PnL")
        print(f"Trade Count: {len(res_df)} | Win Rate: {(res_df['Net_PnL']>0).mean()*100:.1f}%")
        print("="*40)
        res_df.to_csv("framework_results.csv", index=False)
    else:
        print("❌ No trades matched the engine logic in this period.")

if __name__ == "__main__":
    run_pure_harness()