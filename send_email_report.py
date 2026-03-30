import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from datetime import datetime

# --- CONFIG ---
SENDER_EMAIL = "kamalsoni3839@gmail.com"
RECEIVER_EMAIL = "kamalsoni3839@gmail.com"
APP_PASSWORD = "jhnb bqup hihq ebzd" # The one you just generated

def get_summary():
    file = "/home/ubuntu/trading_bot/paper_trade_history.csv"
    try:
        df = pd.read_csv(file)
        df.columns = df.columns.str.strip()
        today = datetime.now().strftime("%Y-%m-%d")
        df_today = df[df['Timestamp'].str.contains(today)]
        
        if df_today.empty: return f"No trades executed today ({today})."

        total_pnl = df_today['Total_PnL'].iloc[-1]
        trades = len(df_today) // 2
        status = "✅ PROFIT" if total_pnl > 0 else "🔻 LOSS"
        
        return f"Market Summary for {today}:\n\nStatus: {status}\nNet P&L: ₹{total_pnl:,.2f}\nTotal Trades: {trades}\n\nCheck GitHub for the full CSV!"
    except:
        return "Error: Could not read trade history file."

def send_email():
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"📈 Trading Report: {datetime.now().strftime('%d %b %Y')}"
    
    body = get_summary()
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

if __name__ == "__main__":
    send_email()