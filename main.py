import pandas as pd
import numpy as np
import yfinance as yf
import os
from datetime import datetime, timedelta
from engine import calculate_signals, risk_management
from dotenv import load_dotenv
import pyotp
from SmartApi import SmartConnect

load_dotenv()

CONFIG = {
    "SYMBOL": "^NSEI", 
    "LOT_SIZE": 50,
    "CAPITAL": 100000,
    "SLIPPAGE_BPS": 0.0004,
    "OUTPUT_FILE": "angel_backtest_results.csv",
    "LIVE_MODE": False  # Set to True for live trading
}

# Angel One credentials
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

def place_order(smart_api, symbol, side, quantity, price):
    """Place an order via Angel One API."""
    try:
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": "99926000",  # NSE NIFTY token
            "transactiontype": side,
            "exchange": "NSE",
            "ordertype": "LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": str(price),
            "quantity": str(quantity)
        }
        response = smart_api.placeOrder(order_params)
        return response
    except Exception as e:
        print(f"Order placement failed: {e}")
        return None

def run_angel_backtest():
    # Initialize API if live mode
    smart_api = None
    if CONFIG['LIVE_MODE']:
        smart_api = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        login_response = smart_api.generateSession(CLIENT_ID, PASSWORD, totp)
        if login_response['status']:
            print("✅ Angel One login successful")
        else:
            print("❌ Angel One login failed")
            return
    # 1. Fetching valid 60-day window
    start_date = (datetime.now() - timedelta(days=58)).strftime('%Y-%m-%d')
    print(f"📡 Fetching data for {CONFIG['SYMBOL']} from {start_date}...")
    df = yf.download(CONFIG['SYMBOL'], start=start_date, interval="5m")
    
    if df.empty:
        print("❌ Data is empty")
        return

    df = df.dropna()  # Remove NaN values
    if len(df) < 30:
        print(f"❌ Insufficient data: {len(df)} < 30 required")
        return

    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    data_records = df.reset_index().to_dict('records')
    
    trades = []
    price_history = []  # Track minute-by-minute prices
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    daily_pnl, current_day = 0, None
    entry_data = {}

    print(f"📊 Analyzing {len(data_records)} candles...")

    for i in range(30, len(data_records)):
        params = risk_management()
        row = data_records[i]
        now_time, now_close = row['Datetime'], float(row['Close'])
        
        # Track price history for each minute
        price_history.append({
            "DateTime": now_time,
            "Price": now_close,
            "High": float(row['High']),
            "Low": float(row['Low']),
            "Volume": float(row['Volume']) if 'Volume' in row else 0
        })
        
        # Day Reset & Overnight Protection
        if current_day != now_time.date():
            if in_position and i > 0:
                trades.append({
                    "Trade_ID": f"ANGEL_{len(trades)+1}", "Entry_Time": entry_time, "Exit_Time": data_records[i-1]['Datetime'],
                    "Type": pos_type, "Entry_Price": entry_price, "Exit_Price": data_records[i-1]['Close'],
                    "Net_PnL": ((data_records[i-1]['Close'] - entry_price) if pos_type == "LONG" else (entry_price - data_records[i-1]['Close'])) * CONFIG['LOT_SIZE'] - params['brokerage_fee'],
                    "Exit_Reason": "GAP_PROTECTION", "Entry_RSI": entry_data.get('rsi'), "Entry_EMA_F": entry_data.get('ema_f')
                })
                in_position = False
            current_day, daily_pnl = now_time.date(), 0

        # Signal Fetching
        price_window = [r['Close'] for r in data_records[i-25:i+1]]
        signal_data = calculate_signals(price_list=price_window, current_time=now_time, position=(1 if pos_type == "LONG" else -1) if in_position else 0, entry_price=entry_price)
        
        action = signal_data.get('action', 'WAIT')

        # Entry
        if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
            in_position = True
            pos_type = "LONG" if "BUY" in action else "SHORT"
            entry_price = now_close * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
            entry_time = now_time
            entry_data = signal_data # Save RSI/EMA for logging
            
            if CONFIG['LIVE_MODE'] and smart_api:
                side = "BUY" if pos_type == "LONG" else "SELL"
                order_response = place_order(smart_api, "NIFTY26FEB25600CE", side, CONFIG['LOT_SIZE'], entry_price)
                if order_response:
                    print(f"✅ Placed {side} order at {entry_price}")
                else:
                    print("❌ Order placement failed")
        
        # Exit
        elif in_position and "EXIT" in action:
            exit_price = now_close * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
            points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
            net_pnl = (points * CONFIG['LOT_SIZE']) - params['brokerage_fee']
            daily_pnl += net_pnl
            
            trades.append({
                "Trade_ID": f"ANGEL_{len(trades)+1}",
                "Entry_Time": entry_time,
                "Exit_Time": now_time,
                "Type": pos_type,
                "Entry_Price": round(entry_price, 2),
                "Exit_Price": round(exit_price, 2),
                "Points": round(points, 2),
                "Net_PnL": round(net_pnl, 2),
                "Exit_Reason": action,
                "Entry_RSI": entry_data.get('rsi'),
                "Entry_EMA_F": entry_data.get('ema_f'),
                "Exit_RSI": signal_data.get('rsi')
            })
            in_position = False

    if trades:
        report_df = pd.DataFrame(trades)
        report_df.to_csv(CONFIG['OUTPUT_FILE'], index=False)
        
        # Save price history for email reporting
        price_history_df = pd.DataFrame(price_history)
        price_history_df.to_csv("price_history.csv", index=False)
        
        print(f"\n✅ DONE. Total PnL: ₹{report_df['Net_PnL'].sum():,.2f} | Trades: {len(report_df)}")
        print(f"   Avg PnL per trade: ₹{report_df['Net_PnL'].mean():,.2f}")
        print(f"   Win rate: {(report_df['Net_PnL'] > 0).sum()}/{len(report_df)} trades")
    else:
        print("\n❌ NO TRADES.")

if __name__ == "__main__":
    run_angel_backtest()