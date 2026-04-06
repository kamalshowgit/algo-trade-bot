import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "").split(',')
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
TRADE_DATA_PATH = os.getenv("TRADE_DATA_PATH", "./paper_trade_history.csv")
PRICE_HISTORY_PATH = "./price_history.csv"
BACKTEST_RESULTS_PATH = "./angel_backtest_results.csv"

def get_summary():
    """Reads trade data and generates a detailed summary with price information."""
    try:
        trade_path = TRADE_DATA_PATH if os.path.exists(TRADE_DATA_PATH) else BACKTEST_RESULTS_PATH
        if not os.path.exists(trade_path):
            return "Error: Trade results file not found.", False, None, None
        
        trades_df = pd.read_csv(trade_path)
        
        if trades_df.empty:
            return "No trades executed today.", False, None, None
        
        # Calculate summary metrics
        total_pnl = trades_df['Net_PnL'].sum()
        num_trades = len(trades_df)
        winning_trades = (trades_df['Net_PnL'] > 0).sum()
        losing_trades = (trades_df['Net_PnL'] < 0).sum()
        breakeven_trades = (trades_df['Net_PnL'] == 0).sum()
        
        avg_pnl = trades_df['Net_PnL'].mean()
        max_profit = trades_df['Net_PnL'].max()
        max_loss = trades_df['Net_PnL'].min()
        win_rate = (winning_trades / num_trades * 100) if num_trades > 0 else 0
        
        status = "✅ PROFIT" if total_pnl > 0 else ("⚠️ BREAKEVEN" if total_pnl == 0 else "🔻 LOSS")
        
        # Read price history
        price_data = None
        price_summary = ""
        if os.path.exists(PRICE_HISTORY_PATH):
            try:
                price_df = pd.read_csv(PRICE_HISTORY_PATH)
                if not price_df.empty:
                    opening_price = price_df['Price'].iloc[0]
                    closing_price = price_df['Price'].iloc[-1]
                    high_price = price_df['High'].max()
                    low_price = price_df['Low'].min()
                    day_change = closing_price - opening_price
                    day_change_pct = (day_change / opening_price * 100) if opening_price > 0 else 0
                    
                    price_summary = f"""
📊 PRICE ACTION SUMMARY:
   Opening: ₹{opening_price:,.2f}
   Closing: ₹{closing_price:,.2f}
   Day High: ₹{high_price:,.2f}
   Day Low: ₹{low_price:,.2f}
   Day Change: {'+' if day_change >= 0 else ''}{day_change:,.2f} ({day_change_pct:+.2f}%)
   Total Candles: {len(price_df)}
"""
                    price_data = price_df
            except Exception as e:
                print(f"⚠️ Could not read price history: {e}")
        
        # Build summary body
        today = datetime.now().strftime("%d %b %Y")
        body = f"""
TRADING PERFORMANCE REPORT - {today}
{'='*60}

{status}

PROFIT & LOSS SUMMARY:
   Total Net P&L: ₹{total_pnl:,.2f}
   Average P&L/Trade: ₹{avg_pnl:,.2f}
   Best Trade: +₹{max_profit:,.2f}
   Worst Trade: -₹{abs(max_loss):,.2f}

TRADE STATISTICS:
   Total Trades: {num_trades}
   Winning Trades: {winning_trades} ✅
   Losing Trades: {losing_trades} 🔻
   Breakeven Trades: {breakeven_trades} ⚠️
   Win Rate: {win_rate:.1f}%

{price_summary}

TOP TRADES:
"""
        
        # Add top 5 trades to the report
        top_trades = trades_df.nlargest(5, 'Net_PnL')
        for idx, trade in top_trades.iterrows():
            body += f"""
   Trade #{idx+1}: {trade['Type']} - ₹{trade['Net_PnL']:,.2f}
      Entry: ₹{trade['Entry_Price']:,.2f} @ {trade['Entry_Time']}
      Exit: ₹{trade['Exit_Price']:,.2f} @ {trade['Exit_Time']}
      Reason: {trade['Exit_Reason']}
"""
        
        body += f"""
{'='*60}
Detailed trade history and minute-by-minute price data are attached.
Report generated at {datetime.now().strftime('%H:%M:%S IST')}
"""
        
        return body, True, trades_df, price_data
        
    except Exception as e:
        return f"Error generating report: {e}", False, None, None

def send_email():
    """Constructs and sends the email with complete trade and price data."""
    body, should_attach, trades_df, price_df = get_summary()
    
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(RECEIVER_EMAIL)
    msg['Subject'] = f"📈 Trading Report: {datetime.now().strftime('%d %b %Y')} | {datetime.now().strftime('%A')}"
    
    msg.attach(MIMEText(body, 'plain'))

    # --- ATTACHMENT LOGIC ---
    # Attach trade results
    if should_attach and trades_df is not None:
        try:
            trades_csv = trades_df.to_csv(index=False).encode()
            part = MIMEBase("application", "octet-stream")
            part.set_payload(trades_csv)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment; filename=trades_summary.csv",
            )
            msg.attach(part)
        except Exception as e:
            print(f"❌ Failed to attach trades file: {e}")
    
    # Attach price history
    if should_attach and price_df is not None:
        try:
            price_csv = price_df.to_csv(index=False).encode()
            part = MIMEBase("application", "octet-stream")
            part.set_payload(price_csv)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment; filename=price_history_minute_by_minute.csv",
            )
            msg.attach(part)
        except Exception as e:
            print(f"❌ Failed to attach price history file: {e}")
    
    # --- SENDING ---
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        
        server.sendmail(SENDER_EMAIL, [email.strip() for email in RECEIVER_EMAIL], msg.as_string())
        
        server.quit()
        print(f"✅ Email sent successfully to: {', '.join(RECEIVER_EMAIL)}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

send_performance_email = send_email

if __name__ == "__main__":
    send_email()