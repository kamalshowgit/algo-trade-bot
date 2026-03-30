import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import pandas as pd
from datetime import datetime

# --- CONFIG ---
SENDER_EMAIL = "kamalsoni3839@gmail.com"
RECEIVER_EMAIL = ["kamalsoni3839@gmail.com", "Jinalsoni3581@gmail.com"]
APP_PASSWORD = "jhnb bqup hihq ebzd" # The one you just generated
CSV_FILE_PATH = "/home/ubuntu/trading_bot/paper_trade_history.csv"

def get_summary():
    """Reads the CSV and generates a summary for the current date."""
    try:
        if not os.path.exists(CSV_FILE_PATH):
            return "Error: Trade history file not found.", False
            
        df = pd.read_csv(CSV_FILE_PATH)
        df.columns = df.columns.str.strip()
        
        # Get today's date in the format used in your CSV
        today = datetime.now().strftime("%Y-%m-%d")
        df_today = df[df['Timestamp'].str.contains(today)]
        
        if df_today.empty: 
            return f"No trades executed today ({today}).", False

        # Get the last recorded P&L for the day
        total_pnl = df_today['Total_PnL'].iloc[-1]
        # Calculate number of completed trades (Buy + Sell = 1 trade)
        trades = len(df_today[df_today['Side'].isin(['BUY', 'SELL'])]) // 2
        status = "✅ PROFIT" if total_pnl > 0 else "🔻 LOSS"
        
        body = (f"Market Summary for {today}:\n\n"
                f"Status: {status}\n"
                f"Net P&L: ₹{total_pnl:,.2f}\n"
                f"Total Trades: {trades}\n\n"
                f"The full trade history is attached as a CSV.")
        return body, True
        
    except Exception as e:
        return f"Error reading logs: {e}", False

def send_email():
    """Constructs and sends the email with an optional CSV attachment."""
    body, should_attach = get_summary()
    
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    # For the email header, we join the list into a comma-separated string
    msg['To'] = ", ".join(RECEIVER_EMAIL)
    msg['Subject'] = f"📈 Trading Report: {datetime.now().strftime('%d %b %Y')}"
    
    msg.attach(MIMEText(body, 'plain'))

    # --- ATTACHMENT LOGIC ---
    if should_attach and os.path.exists(CSV_FILE_PATH):
        try:
            with open(CSV_FILE_PATH, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename= {os.path.basename(CSV_FILE_PATH)}",
            )
            msg.attach(part)
        except Exception as e:
            print(f"❌ Failed to attach file: {e}")

    # --- SENDING ---
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        
        # We use sendmail here because it accepts the list of receivers correctly
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        
        server.quit()
        print(f"✅ Email sent successfully to: {', '.join(RECEIVER_EMAIL)}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

if __name__ == "__main__":
    send_email()