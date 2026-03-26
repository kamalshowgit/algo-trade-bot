import pandas as pd
import os

def analyze_trades():
    file_path = 'paper_trade_history.csv'
    
    if not os.path.exists(file_path):
        print(f"❌ File '{file_path}' not found. Ensure the bot has traded.")
        return

    df = pd.read_csv(file_path)
    
    if df.empty:
        print("📭 Trade log is empty.")
        return

    # Identify Entry (BUY) and Exit (SELL) rows
    entries = df[df['Side'] == 'BUY'].copy()
    exits = df[df['Side'] == 'SELL'].copy()
    
    print("=" * 60)
    print(f"📊 HFT STRATEGY AUDIT: {df['Timestamp'].max()}")
    print("=" * 60)

    if exits.empty:
        print("⏳ STATUS: Position currently OPEN. No exits logged yet.")
        # Show entry details if open
        if not entries.empty:
            last_buy = entries.iloc[-1]
            print(f"   Current Entry: ₹{last_buy['Price']} | Entry RSI: {last_buy['RSI_Value']}")
        return

    # 1. Overall Portfolio Stats
    total_trades = len(exits)
    net_pnl = exits['Total_PnL'].iloc[-1]
    brokerage_paid = total_trades * 60
    
    wins = exits[exits['Trade_PnL'] > 60]
    win_rate = (len(wins) / total_trades) * 100

    print(f"🏢 OVERALL PORTFOLIO")
    print(f"   Net P&L:       ₹{net_pnl:.2f} (After ₹{brokerage_paid} fees)")
    print(f"   Win Rate:      {win_rate:.2f}%")
    print(f"   Total Cycles:  {total_trades}")
    print("-" * 60)

    # 2. Advanced Technical Audit (The Analyst View)
    print(f"🧪 TECHNICAL INDICATOR ANALYSIS (At Entry)")
    
    # Analyze RSI at the moment of entry for all trades
    avg_rsi_entry = entries['RSI_Value'].mean()
    
    # Strategy specific breakdown
    strat_groups = df.groupby('Strategy')
    
    for strat, data in strat_groups:
        strat_exits = data[data['Side'] == 'SELL']
        strat_entries = data[data['Side'] == 'BUY']
        
        if strat_exits.empty: continue
        
        strat_pnl = strat_exits['Trade_PnL'].sum() - (len(strat_exits) * 60)
        avg_rsi = strat_entries['RSI_Value'].mean()
        
        print(f"   ▶ {strat.upper()}:")
        print(f"     Net PnL:     ₹{strat_pnl:.2f}")
        print(f"     Avg Entry RSI: {avg_rsi:.2f}")
        
        # Feedback logic
        if strat == "sniper" and avg_rsi > 30:
            print("     💡 Tip: Sniper RSI is high. Tighten to < 20 for better '95%' accuracy.")
    
    print("-" * 60)
    
    # 3. Final Verdict
    if net_pnl > 0:
        print("🚀 VERDICT: PROFITABLE. Strategy is covering brokerage.")
    else:
        print("⚠️ VERDICT: UNDERPERFORMING. Brokerage is eating your alpha.")
    print("=" * 60)

if __name__ == "__main__":
    analyze_trades()