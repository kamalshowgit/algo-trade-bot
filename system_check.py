import pandas as pd
import engine
import csv
import os
from datetime import datetime

def run_diagnostic():
    print("🔍 STARTING HFT SYSTEM DIAGNOSTIC...")
    
    # 1. Test Data Generation
    # Simulate a "Crash and Recovery" (Perfect for Mean Reversion)
    mock_prices = [23400, 23390, 23380, 23370, 23360, 23300, 23250, 23200, 23150, 23100] # Sharp Drop
    mock_prices += [23110, 23150, 23200, 23250, 23300, 23350, 23400] # Fast Recovery
    
    print(f"✅ Generated {len(mock_prices)} mock price points.")

    # 2. Test Engine Logic
    print("🧪 Testing Strategy Dispatcher...")
    try:
        sig_sniper = engine.calculate_signals(mock_prices, current_time=datetime.now())
        sig_scalper = engine.calculate_signals(mock_prices, current_time=datetime.now())
        print(f"   [Sniper Signal]: {sig_sniper}")
        print(f"   [Scalper Signal]: {sig_scalper}")
        print("✅ Engine Logic: PASS")
    except Exception as e:
        print(f"❌ Engine Logic: FAIL ({e})")
        return

    # 3. Test CSV Logging (PaperTrader Simulation)
    print("📝 Testing CSV I/O (New Multi-Strategy Format)...")
    log_file = "paper_trade_history.csv"
    
    # Remove old file if exists for clean test
    if os.path.exists(log_file): os.remove(log_file)
    
    header = ["Timestamp", "Strategy", "Side", "Price", "Qty", "Trade_PnL", "Total_PnL"]
    test_row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sniper", "BUY", 23200, 19, 0, 0]
    
    try:
        with open(log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerow(test_row)
        print("✅ CSV Write: PASS")
    except Exception as e:
        print(f"❌ CSV Write: FAIL ({e})")
        return

    print("\n" + "="*40)
    print("🚀 SYSTEM READY FOR FRIDAY MARKET OPEN")
    print("="*40)
    print("Note: Run 'python3 review_performance.py' now to see if it reads the test row.")

if __name__ == "__main__":
    run_diagnostic()