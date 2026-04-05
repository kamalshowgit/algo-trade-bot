import pandas as pd
import numpy as np
import yfinance as yf
import os
import time
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

def run_live_trading():
    """Run live trading during market hours and exit after market close."""
    print("🚀 Starting LIVE TRADING MODE")
    
    # Initialize API
    smart_api = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    login_response = smart_api.generateSession(CLIENT_ID, PASSWORD, totp)
    if not login_response['status']:
        print("❌ Angel One login failed")
        return
    
    print("✅ Angel One login successful")
    
    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    daily_pnl = 0
    entry_data = {}
    
    # Trading loop - runs until market close
    while True:
        now = datetime.now()
        now_m = now.hour * 60 + now.minute
        
        # Market close check - send email and exit
        if now_m >= 915:  # 3:15 PM IST
            print("🏁 Market closed. Sending final report...")
            
            if trades:
                report_df = pd.DataFrame(trades)
                report_df.to_csv(CONFIG['OUTPUT_FILE'], index=False)
                
                price_history_df = pd.DataFrame(price_history)
                price_history_df.to_csv("price_history.csv", index=False)
                
                # Send email report
                try:
                    from send_email_report import send_performance_email
                    send_performance_email()
                    print("✅ Email report sent")
                except Exception as e:
                    print(f"❌ Email failed: {e}")
            
            print("✅ Live trading session complete. Exiting...")
            return  # Exit gracefully for PM2 restart tomorrow
        
        # Only trade during market hours
        if not (555 <= now_m <= 915):  # 9:15 AM to 3:15 PM
            time.sleep(60)  # Wait 1 minute before checking again
            continue
        
        try:
            # Fetch latest 5-minute data
            end_time = now.replace(second=0, microsecond=0)
            start_time = end_time - timedelta(hours=1)  # Get last hour of data
            
            df = yf.download(CONFIG['SYMBOL'], start=start_time, end=end_time, interval="5m")
            if df.empty or len(df) < 2:
                time.sleep(60)
                continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            current_price = float(df['Close'].iloc[-1])
            current_time = df.index[-1].to_pydatetime()
            
            # Track price history
            price_history.append({
                "DateTime": current_time,
                "Price": current_price,
                "High": float(df['High'].iloc[-1]),
                "Low": float(df['Low'].iloc[-1]),
                "Volume": float(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 0
            })
            
            # Get price window for signals (last 26 candles = ~2 hours)
            price_window = df['Close'].tail(26).tolist()
            if len(price_window) < 20:
                time.sleep(60)
                continue
            
            # Generate signal
            signal_data = calculate_signals(price_list=price_window, current_time=current_time, 
                                          position=(1 if pos_type == "LONG" else -1) if in_position else 0, 
                                          entry_price=entry_price)
            
            action = signal_data.get('action', 'WAIT')
            
            # Entry logic
            if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
                in_position = True
                pos_type = "LONG" if "BUY" in action else "SHORT"
                entry_price = current_price * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                entry_time = current_time
                entry_data = signal_data
                
                # Place live order
                side = "BUY" if pos_type == "LONG" else "SELL"
                order_response = place_order(smart_api, "NIFTY26FEB25600CE", side, CONFIG['LOT_SIZE'], entry_price)
                if order_response:
                    print(f"✅ Placed {side} order at {entry_price}")
                else:
                    print("❌ Order placement failed")
            
            # Exit logic
            elif in_position and "EXIT" in action:
                exit_price = current_price * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                net_pnl = (points * CONFIG['LOT_SIZE']) - risk_management()['brokerage_fee']
                daily_pnl += net_pnl
                
                trades.append({
                    "Trade_ID": f"ANGEL_{len(trades)+1}",
                    "Entry_Time": entry_time,
                    "Exit_Time": current_time,
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
                
                # Place exit order
                exit_side = "SELL" if pos_type == "LONG" else "BUY"
                exit_order = place_order(smart_api, "NIFTY26FEB25600CE", exit_side, CONFIG['LOT_SIZE'], exit_price)
                if exit_order:
                    print(f"✅ Placed {exit_side} exit order at {exit_price}")
                
                in_position = False
            
            # Wait 5 minutes before next check
            time.sleep(300)
            
        except Exception as e:
            print(f"❌ Live trading error: {e}")
            time.sleep(60)

def run_angel_backtest():
    # ... existing backtest code ...
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
    if CONFIG['LIVE_MODE']:
        run_live_trading()
    else:
        run_angel_backtest()