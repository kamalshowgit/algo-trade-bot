import yfinance as yf # Import Yahoo Finance API library to download historical market data
import pandas as pd # Import pandas for dataframe management and time series analysis
import numpy as np # Import numpy for numerical and array operations
import random # Import random module to introduce variance in simulated slippage
import sys # Import sys to read command line arguments
from engine import calculate_signals # Import the core signal generation function from the engine module

# ==============================
# CONFIG
# ==============================
INITIAL_CAPITAL = 100000 # Define the starting simulated bankroll for the backtest
LOT_SIZE = 65 # Set the default lot size (number of shares/contracts) per trade
SLIPPAGE_BPS = 0.00015 # Define base slippage as 1.5 basis points (0.015%) - realistic for Nifty
MAX_DAILY_LOSS = 0.03 # Define the maximum allowed daily loss threshold (3% of initial capital, i.e., 3000 INR)
COOLDOWN_BARS = 10 # Set the number of bars to wait after a trade before entering a new one

SYMBOL = "^NSEI" # Define the default ticker symbol to backtest (NIFTY 50 index)

# OPTIMIZED: Support strategy selection from command line
# Usage: python backtest.py strategy_2
STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "strategy_1"  # Default to strategy_1 if not provided

# ==============================
# REALISTIC TRADING COSTS (INDIAN F&O)
# ==============================
def calculate_trading_costs(entry_price, exit_price, qty, instrument_type="FUTURES"):
    """
    Calculates detailed transaction costs based on Indian market regulations for NSE.
    Returns total cost and a breakdown.
    """
    # Fixed brokerage (e.g., standard discount broker rate: 20 per order = 40 round trip)
    brokerage = 40.0
    
    buy_value = entry_price * qty
    sell_value = exit_price * qty
    turnover = buy_value + sell_value
    
    if instrument_type == "FUTURES":
        # Exchange Transaction Charge (NSE Futures approx 0.0019%)
        exchange_txn_charge = turnover * 0.000019
        # STT (0.0125% on Sell Value for Futures)
        stt = sell_value * 0.000125
        # Stamp Duty (0.002% on Buy Value)
        stamp_duty = buy_value * 0.00002
    else: # OPTIONS (Assuming premium value turnover for simplicity)
        exchange_txn_charge = turnover * 0.0005  # NSE Options 0.05% on premium
        stt = sell_value * 0.000625 # 0.0625% on sell side premium
        stamp_duty = buy_value * 0.00003 # 0.003% on buy side premium

    # GST (18% on Brokerage + Exchange Txn Charge)
    gst = (brokerage + exchange_txn_charge) * 0.18
    
    # SEBI Charges (10 per crore = 0.0001%)
    sebi_charges = turnover * 0.000001
    
    total_cost = brokerage + exchange_txn_charge + gst + stt + sebi_charges + stamp_duty
    
    cost_breakdown = {
        'Brokerage': brokerage,
        'Exchange_Txn': exchange_txn_charge,
        'GST': gst,
        'STT': stt,
        'SEBI': sebi_charges,
        'Stamp_Duty': stamp_duty,
        'Total_Cost': total_cost
    }
    
    return total_cost, cost_breakdown


# ==============================
# DATA FETCH (ROBUST)
# ==============================
def fetch_data(): # Function to pull historical chart data safely
    import yfinance as yf # Re-import specifically for scope
    import pandas as pd # Re-import specifically for scope

    print("Fetching data...") # Console log progress

    # -------------------------------
    # Try intraday first (5m)
    # -------------------------------
    df = yf.download("^NSEI", period="59d", interval="5m", progress=False) # Get last 59 days of 5m intervals

    if not df.empty: # If intraday fetch was successful
        print("✅ Using 5m data (last 59 days)") # Confirm usage of intraday
    else: # If intraday failed (e.g. API limits or delisted)
        print("⚠️ 5m failed → switching to daily (2y)") # Fallback notice
        df = yf.download("^NSEI", period="2y", interval="1d", progress=False) # Get last 2 years of daily data

    if df.empty: # Check one final time if df is still empty
        raise ValueError("❌ No data fetched from yfinance") # Abort the script with an error

    # -------------------------------
    # Fix multi-index columns (IMPORTANT)
    # -------------------------------
    if isinstance(df.columns, pd.MultiIndex): # Yahoo Finance sometimes returns MultiIndex columns
        df.columns = df.columns.get_level_values(0) # Flatten them to a simple index

    df = df.reset_index() # Bring the Datetime index into the columns

    # -------------------------------
    # Normalize Datetime column
    # -------------------------------
    if "Datetime" not in df.columns: # If explicit Datetime column is missing
        if "Date" in df.columns: # See if it's called Date instead (happens with daily data)
            df.rename(columns={"Date": "Datetime"}, inplace=True) # Standardize the column to 'Datetime'
        else: # If absolutely no time column exists
            raise ValueError("❌ No Datetime column found") # Abort the script

    df["Datetime"] = pd.to_datetime(df["Datetime"]) # Guarantee column is an actual Datetime object
    
    if df["Datetime"].dt.tz is not None: # Standardize to IST for time-based engine rules
        df["Datetime"] = df["Datetime"].dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)

    # -------------------------------
    # Normalize OHLCV columns
    # -------------------------------
    column_map = {} # Dictionary to standardize columns

    for col in df.columns: # Iterate over the dataset columns
        lc = col.lower() # Convert to lowercase for easy matching

        if lc == "open": # Map Open
            column_map[col] = "Open" 
        elif lc == "high": # Map High
            column_map[col] = "High" 
        elif lc == "low": # Map Low
            column_map[col] = "Low" 
        elif lc == "close": # Map Close
            column_map[col] = "Close" 
        elif lc == "adj close": # Remap adjusted close to standard Close if present
            column_map[col] = "Close" 
        elif lc == "volume": # Map Volume
            column_map[col] = "Volume" 

    df = df.rename(columns=column_map) # Rename the DataFrame headers

    # -------------------------------
    # Ensure ALL required columns exist
    # -------------------------------
    required_cols = ["Open", "High", "Low", "Close", "Volume"] # List the mandatory columns

    for col in required_cols: # Check each
        if col not in df.columns: # If missing entirely
            print(f"⚠️ Missing {col} → filling with default") # Notify user
            df[col] = 0.0 # Substitute with zero to prevent crashes

    # Convert to numeric
    for col in required_cols: # Re-check columns
        df[col] = pd.to_numeric(df[col], errors="coerce") # Force valid numeric types

    # Drop bad rows
    df = df.dropna(subset=["Close"]) # Throw out rows where the Close price is NaN

    # Final selection
    df = df[["Datetime", "Open", "High", "Low", "Close", "Volume"]] # Reorder output exactly

    # -------------------------------
    # Convert to records
    # -------------------------------
    records = df.to_dict("records") # Convert the dataframe to a list of dicts for faster iteration

    # Debug sample
    print("Sample record:", records[0]) # Show the first valid record
    print("Data points:", len(records)) # Show total length
    
    if sum(r.get("Volume", 0.0) for r in records[:100]) == 0.0:
        print("⚠️ Notice: Volume data is zero (common for indices). Engine will adapt volume checks.")

    return records # Provide the payload


# ==============================
# SLIPPAGE
# ==============================
def apply_slippage(price, side): # Simulates market slippage randomly
    slip = SLIPPAGE_BPS * (1 + random.uniform(-0.5, 0.5)) # Fluctuate slippage slightly around base BPS
    return price * (1 + slip if side == "BUY" else 1 - slip) # Add for buys (pay more), subtract for sells (get less)


# ==============================
# BACKTEST ENGINE
# ==============================
def backtest(records): # The main iteration loop

    capital = INITIAL_CAPITAL # Set up working capital
    equity_curve = [] # Array tracking capital over time
    trades = [] # Array tracking individual trade details

    in_position = False # State flag
    pos_type = None # LONG or SHORT state
    entry_price = 0 # Entry watermark
    entry_time = None # Entry time tracker
    entry_signal_data = {} # Entry signal cache
    qty = 0 # Asset quantity
    stop_loss = None # SL watermark
    target_price = None # Target watermark
    pending_entry = None # Stage execution to remove look-ahead bias

    last_trade_bar = -COOLDOWN_BARS # Init cooldown tracker safely behind index 0
    daily_pnl = 0 # Intra-day limit tracking
    current_day = None # Loop day tracking

    for i in range(60, len(records)): # Start at index 60 so we have enough lookback data for EMAs/BBs

        row = records[i] # Get current iteration data
        price = float(row["Close"]) # Read current close
        time = row["Datetime"] # Read current time

        # Reset daily PnL and ensure no positions carry overnight
        if current_day != time.date():
            if in_position and i > 0:
                prev_row = records[i-1]
                prev_price = float(prev_row["Close"])
                exit_price = apply_slippage(prev_price, "SELL" if pos_type == "LONG" else "BUY")
                pnl_points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                
                total_cost, cost_breakdown = calculate_trading_costs(entry_price, exit_price, qty)
                net = pnl_points * qty - total_cost
                
                capital += net
                daily_pnl += net
                
                trades.append({
                    'Trade_ID': f"BT_{len(trades)+1}",
                    'Entry_Time': entry_time,
                    'Exit_Time': prev_row["Datetime"],
                    'Type': pos_type,
                    'Qty': qty,
                    'Entry_Price': round(entry_price, 2),
                    'Exit_Price': round(exit_price, 2),
                    'Points': round(pnl_points, 2),
                    'Net_PnL': round(net, 2),
                    'Exit_Reason': 'DAY_CLOSE',
                    'Entry_RSI': entry_signal_data.get("rsi"),
                    'Entry_EMA_F': entry_signal_data.get("ema_f"),
                    'Exit_RSI': None,
                    'Entry_Score': entry_signal_data.get("entry_score"),
                    'Strategy': STRATEGY,
                    'Planned_Risk': round(qty * (entry_price * entry_signal_data.get("stop_loss_pct", 0.0025)), 2) if entry_price else 0.0,
                    'Daily_PnL_After': round(daily_pnl, 2),
                    'Risk_Allowed': True,
                    'Session_Stop': ""
                })
                
                in_position = False
                pos_type = None
                entry_price = 0
                entry_time = None
                entry_signal_data = {}
                qty = 0
                stop_loss = None
                target_price = None

            current_day = time.date()
            daily_pnl = 0

        # Daily loss protection
        if daily_pnl <= -MAX_DAILY_LOSS * INITIAL_CAPITAL: # Check if maximum daily loss is blown
            equity_curve.append(capital) # Record untouched equity
            continue # Skip processing until next day

        # Cooldown
        if i - last_trade_bar < COOLDOWN_BARS: # Restrict taking a trade too soon after the last exit
            equity_curve.append(capital) # Record untouched equity
            continue # Skip processing
            
        # ================= EXECUTE PENDING ENTRY =================
        if pending_entry:
            # Execute on this new candle's open to guarantee realistic fills
            action = pending_entry["action"]
            signal = pending_entry["signal"]
            entry_price = apply_slippage(float(row["Open"]), "BUY" if action == "BUY_LONG" else "SELL")
            
            stop_loss = entry_price * ((1 - signal["stop_loss_pct"]) if action == "BUY_LONG" else (1 + signal["stop_loss_pct"]))
            target_price = entry_price * ((1 + signal["target_pct"]) if action == "BUY_LONG" else (1 - signal["target_pct"]))
            
            qty = pending_entry["qty"]
            pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
            in_position = True
            last_trade_bar = i
            entry_time = time
            entry_signal_data = signal
            pending_entry = None

        recent_records = records[i-60:i+1] # Slicing the lookback window
        candles_df = pd.DataFrame(recent_records) # Formatting to dataframe for the engine
        window = candles_df["Close"].tolist() # Extracting price list

        signal = calculate_signals( # Ping the logic engine
            price_list=window, # Send price list
            current_time=time, # Send current timestamp
            position=(1 if pos_type == "LONG" else -1) if in_position else 0, # Translate position to 1, 0, -1
            entry_price=entry_price, # Send current entry cost
            candles_df=candles_df, # Send full dataframe
            capital=capital, # Provide tracking capital
            lot_size=LOT_SIZE, # Provide standard lot sizing
            strategy_name=STRATEGY  # OPTIMIZED: Pass selected strategy
        ) 

        action = signal.get("action", "WAIT") # Default parse the intended action

        # DEBUG (every 200 steps)
        if i % 200 == 0: # Sporadic print tracking to monitor run health
            print(f"{time} | Action: {action}") # Print time and action

        # ================= ENTRY =================
        if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:

            entry_price = apply_slippage(price, "BUY" if action == "BUY_LONG" else "SELL")

            stop_loss = entry_price * (
                (1 - signal["stop_loss_pct"]) if action == "BUY_LONG"
                else (1 + signal["stop_loss_pct"])
            )
            target_price = entry_price * (
                (1 + signal["target_pct"]) if action == "BUY_LONG"
                else (1 - signal["target_pct"])
            )

            qty = int(signal.get("suggested_qty", LOT_SIZE))

            pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
            in_position = True
            last_trade_bar = i
            entry_time = time
            entry_signal_data = signal # Cache the entry context

        # ================= POSITION MANAGEMENT =================
        elif in_position:

            high_price = float(row["High"])
            low_price = float(row["Low"])
            
            pnl_pct = ((price - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - price) / entry_price)

            exit_flag = False
            exit_reason = ""
            exit_execution_price = price

            # Stop loss & Target (using high/low for realistic intraday fills)
            if pos_type == "LONG":
                if low_price <= stop_loss:
                    exit_flag = True
                    exit_reason = "SL"
                    exit_execution_price = stop_loss
                elif high_price >= target_price:
                    exit_flag = True
                    exit_reason = "TARGET"
                    exit_execution_price = target_price
            else:
                if high_price >= stop_loss:
                    exit_flag = True
                    exit_reason = "SL"
                    exit_execution_price = stop_loss
                elif low_price <= target_price:
                    exit_flag = True
                    exit_reason = "TARGET"
                    exit_execution_price = target_price

            # Signal exit
            if not exit_flag and action.startswith("EXIT"):
                exit_flag = True
                exit_reason = "SIGNAL"
                exit_execution_price = price

            # EOD exit
            if not exit_flag and hasattr(time, "hour") and time.hour == 15 and time.minute >= 15:
                exit_flag = True
                exit_reason = "EOD"
                exit_execution_price = price

            if exit_flag:
                exit_price_final = apply_slippage(exit_execution_price, "SELL" if pos_type == "LONG" else "BUY")

                pnl_points = (exit_price_final - entry_price) if pos_type == "LONG" else (entry_price - exit_price_final)
                
                total_cost, cost_breakdown = calculate_trading_costs(entry_price, exit_price_final, qty)
                net = pnl_points * qty - total_cost

                capital += net
                daily_pnl += net
                
                trades.append({
                    'Trade_ID': f"BT_{len(trades)+1}",
                    'Entry_Time': entry_time,
                    'Exit_Time': time,
                    'Type': pos_type,
                    'Qty': qty,
                    'Entry_Price': round(entry_price, 2),
                    'Exit_Price': round(exit_price_final, 2),
                    'Points': round(pnl_points, 2),
                    'Net_PnL': round(net, 2),
                    'Exit_Reason': exit_reason,
                    'Entry_RSI': entry_signal_data.get("rsi"),
                    'Entry_EMA_F': entry_signal_data.get("ema_f"),
                    'Exit_RSI': signal.get("rsi"),
                    'Entry_Score': entry_signal_data.get("entry_score"),
                    'Strategy': STRATEGY,
                    'Planned_Risk': round(qty * (entry_price * entry_signal_data.get("stop_loss_pct", 0.0025)), 2),
                    'Daily_PnL_After': round(daily_pnl, 2),
                    'Risk_Allowed': True,
                    'Session_Stop': ""
                })

                in_position = False
                pos_type = None
                entry_price = 0
                entry_time = None
                pending_entry = None
                entry_signal_data = {}
                qty = 0
                stop_loss = None
                target_price = None

            # Trailing logic updates AFTER checking exit for the current candle
            if in_position:
                if pos_type == "LONG":
                    # Trail standard SL from the current moment price to constantly reduce risk
                    stop_loss = max(stop_loss, price * (1 - signal["stop_loss_pct"]))
                    
                    # Once we hit breakeven threshold, lock it and tighten the trail
                    if pnl_pct >= signal["breakeven_pct"]:
                        stop_loss = max(stop_loss, entry_price) # Guarantee breakeven
                        stop_loss = max(stop_loss, price * (1 - signal["trail_distance"])) # Tighten trail
                else:
                    # Trail standard SL from the current moment price to constantly reduce risk
                    stop_loss = min(stop_loss, price * (1 + signal["stop_loss_pct"]))
                    
                    # Once we hit breakeven threshold, lock it and tighten the trail
                    if pnl_pct >= signal["breakeven_pct"]:
                        stop_loss = min(stop_loss, entry_price) # Guarantee breakeven
                        stop_loss = min(stop_loss, price * (1 + signal["trail_distance"])) # Tighten trail

        equity_curve.append(capital)

    # Flush any remaining open position at the absolute end of the backtest
    if in_position:
        exit_price = apply_slippage(price, "SELL" if pos_type == "LONG" else "BUY")
        pnl_points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
        
        total_cost, cost_breakdown = calculate_trading_costs(entry_price, exit_price, qty)
        net = pnl_points * qty - total_cost
        capital += net
        
        trades.append({
            'Trade_ID': f"BT_{len(trades)+1}",
            'Entry_Time': entry_time,
            'Exit_Time': time,
            'Type': pos_type,
            'Qty': qty,
            'Entry_Price': round(entry_price, 2),
            'Exit_Price': round(exit_price, 2),
            'Points': round(pnl_points, 2),
            'Net_PnL': round(net, 2),
            'Exit_Reason': 'BACKTEST_END',
            'Entry_RSI': entry_signal_data.get("rsi"),
            'Entry_EMA_F': entry_signal_data.get("ema_f"),
            'Exit_RSI': None,
            'Entry_Score': entry_signal_data.get("entry_score"),
            'Strategy': STRATEGY,
            'Planned_Risk': round(qty * (entry_price * entry_signal_data.get("stop_loss_pct", 0.0025)), 2) if entry_price else 0.0,
            'Daily_PnL_After': round(daily_pnl, 2),
            'Risk_Allowed': True,
            'Session_Stop': ""
        })
        equity_curve[-1] = capital

    return trades, equity_curve


# ==============================
# REPORT
# ==============================
def generate_report(trades, equity_curve): # Display human-readable metrics on success

    if not equity_curve: # Check for empty results
        print("❌ No equity data generated") # Raise warning to user
        return # Bail early

    pnl_list = [t['Net_PnL'] for t in trades] if trades else []
    total = sum(pnl_list)
    num_trades = len(trades) # Tabulate raw occurrences

    winning_trades = [p for p in pnl_list if p > 0]
    losing_trades = [p for p in pnl_list if p <= 0]
    
    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    
    win_rate = (len(winning_trades) / num_trades * 100) if num_trades > 0 else 0
    
    avg_trade = total / num_trades if num_trades else 0 # Mathematical trade expectancy
    avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0
    avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0
    
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
    risk_reward = (avg_win / avg_loss) if avg_loss > 0 else float('inf')

    peak = equity_curve[0] # Initialize local peak to calculate drawdowns
    max_dd = 0 # Initialize Max Drawdown to zero

    for val in equity_curve: # Loop through every moment in the bankroll
        peak = max(peak, val) # Identify the new highest watermark
        dd = (peak - val) / peak # Find the relative loss compared to the peak
        max_dd = max(max_dd, dd) # Update the worst-case drop
        
    total_return_pct = ((equity_curve[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100

    print("\n" + "="*80)
    print("                 BACKTEST REPORT & BUSINESS INSIGHTS")
    print("="*80)
    
    # 1. Overall Performance (Business Growth)
    print("\n--- 1. OVERALL PERFORMANCE ---")
    print(f"Initial Capital: {INITIAL_CAPITAL}")
    print(f"Final Capital:   {round(equity_curve[-1], 2)}")
    print(f"Total Net PnL:   {round(total, 2)}\t\t<- [Total profit or loss generated by the strategy]")
    print(f"Total Return:    {round(total_return_pct, 2)}%\t\t<- [Percentage growth of your initial capital]")
    
    # 2. Trade Analytics (Strategy Efficiency)
    print("\n--- 2. TRADE ANALYTICS ---")
    print(f"Total Trades:    {num_trades}\t\t<- [Total executed signals. High trades = more brokerage fees]")
    print(f"Win Rate:        {round(win_rate, 2)}%\t\t<- [Percentage of profitable trades. >50% is generally good]")
    print(f"Gross Profit:    {round(gross_profit, 2)}\t\t<- [Sum of all winning trades]")
    print(f"Gross Loss:      {round(gross_loss, 2)}\t\t<- [Sum of all losing trades]")
    
    # 3. Risk & Reward (Business Viability)
    # -------------------------------
    # ADVANCED METRICS MATH
    # -------------------------------
    trade_pnls = pd.Series(pnl_list)
    if len(trade_pnls) > 1 and trade_pnls.std() != 0:
        # System Quality Number (SQN)
        sqn = (avg_trade / trade_pnls.std()) * np.sqrt(num_trades)
        
        # Daily Equity-based Annualized Sharpe & Sortino
        df_trades = pd.DataFrame(trades)
        df_trades['Date'] = pd.to_datetime(df_trades['Exit_Time']).dt.date
        daily_returns = df_trades.groupby('Date')['Net_PnL'].sum() / INITIAL_CAPITAL
        
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() != 0 else 0
        downside = daily_returns[daily_returns < 0]
        sortino_ratio = (daily_returns.mean() / downside.std()) * np.sqrt(252) if not downside.empty and downside.std() != 0 else float('inf')
    else:
        sharpe_ratio = 0
        sortino_ratio = 0
        sqn = 0

    # Ulcer Index (Depth + Duration of Drawdown)
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    peaks[peaks == 0] = 1 # Safety division
    drawdowns_arr = (peaks - eq_arr) / peaks
    ulcer_index = np.sqrt(np.mean(drawdowns_arr**2)) * 100

    calmar_ratio = (total_return_pct / (max_dd * 100)) if max_dd > 0 else float('inf')
    recovery_factor = (total / gross_loss) if gross_loss > 0 else float('inf')
    expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

    print("\n--- 3. RISK & REWARD ---")
    print(f"Average Trade:   {round(avg_trade, 2)}\t\t<- [Expectancy: Average amount gained/lost per trade. Must be positive]")
    print(f"Average Win:     {round(avg_win, 2)}\t\t<- [Average profit on winning trades]")
    print(f"Average Loss:    {round(avg_loss, 2)}\t\t<- [Average loss on losing trades]")
    print(f"Risk/Reward:     {round(risk_reward, 2)}\t\t<- [Ratio of Avg Win to Avg Loss. Target > 1.5 for trend following]")
    print(f"Profit Factor:   {round(profit_factor, 2)}\t\t<- [Gross Profit / Gross Loss. >1.0 is profitable, >1.5 is excellent]")
    print(f"Max Drawdown:    {round(max_dd * 100, 2)}%\t\t<- [Largest percentage drop from peak. Measures worst-case risk/pain]")
    
    # 4. Institutional Metrics (Advanced)
    print("\n--- 4. INSTITUTIONAL METRICS ---")
    print(f"Sharpe Ratio:    {round(sharpe_ratio, 2)}\t\t<- [Risk-adjusted return. >1.0 is good, >2.0 is excellent]")
    print(f"Sortino Ratio:   {round(sortino_ratio, 2)}\t\t<- [Downside risk-adjusted return. Penalizes only negative volatility]")
    print(f"Calmar Ratio:    {round(calmar_ratio, 2)}\t\t<- [Total Return / Max Drawdown. >3.0 is excellent]")
    print(f"Recovery Factor: {round(recovery_factor, 2)}\t\t<- [Net Profit / Gross Loss. Measures ability to bounce back]")
    print(f"Expectancy:      {round(expectancy, 2)}\t\t<- [Mathematical expectation per trade based on WR and R:R]")
    print(f"SQN:             {round(sqn, 2)}\t\t<- [System Quality Number. >2.0 avg, >3.0 excellent]")
    print(f"Ulcer Index:     {round(ulcer_index, 2)}\t\t<- [Measures depth and duration of drawdowns]")
    
    print("="*80 + "\n")
    
    # Export to CSV
    if trades:
        df_trades = pd.DataFrame(trades)
        df_trades.to_csv(f'{STRATEGY}_backtest_results.csv', index=False)
        print(f"💾 Saved detailed trade log to '{STRATEGY}_backtest_results.csv'")


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":

    records = fetch_data()

    print("Running backtest...")
    trades, equity = backtest(records)

    print("Total trades:", len(trades))

    generate_report(trades, equity)