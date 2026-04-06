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
PRICE_HISTORY_PATH = os.getenv("PRICE_HISTORY_PATH", "./price_history.csv")
BACKTEST_RESULTS_PATH = os.getenv("BACKTEST_RESULTS_PATH", "./angel_backtest_results.csv")


def format_currency(value):
    return f"₹{value:,.2f}"


def get_summary():
    """Reads trade data and generates a detailed summary with price information."""
    try:
        trade_path = TRADE_DATA_PATH if os.path.exists(TRADE_DATA_PATH) else BACKTEST_RESULTS_PATH
        if not os.path.exists(trade_path):
            return "Error: Trade results file not found.", False, None, None, trade_path

        trades_df = pd.read_csv(trade_path)
        
        if trades_df.empty:
            return "No trades executed today.", False, None, None, trade_path

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
        profit_factor = (trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].sum() / abs(trades_df[trades_df['Net_PnL'] < 0]['Net_PnL'].sum())) if (trades_df['Net_PnL'] < 0).any() else float('inf')

        status = "✅ PROFIT" if total_pnl > 0 else ("⚠️ BREAKEVEN" if total_pnl == 0 else "🔻 LOSS")

        # Read price history
        price_data = None
        price_summary = {}
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
                    price_summary = {
                        'opening': opening_price,
                        'closing': closing_price,
                        'high': high_price,
                        'low': low_price,
                        'change': day_change,
                        'change_pct': day_change_pct,
                        'candles': len(price_df)
                    }
                    price_data = price_df
            except Exception as e:
                print(f"⚠️ Could not read price history: {e}")

        # Build text and HTML summary
        today = datetime.now().strftime("%d %b %Y")
        text_body = [
            f"TRADING PERFORMANCE REPORT - {today}",
            "=" * 60,
            status,
            "",
            "PROFIT & LOSS SUMMARY:",
            f"   Total Net P&L: {format_currency(total_pnl)}",
            f"   Average P&L/Trade: {format_currency(avg_pnl)}",
            f"   Best Trade: {format_currency(max_profit)}",
            f"   Worst Trade: {format_currency(abs(max_loss))}",
            "",
            "TRADE STATISTICS:",
            f"   Total Trades: {num_trades}",
            f"   Winning Trades: {winning_trades}",
            f"   Losing Trades: {losing_trades}",
            f"   Breakeven Trades: {breakeven_trades}",
            f"   Win Rate: {win_rate:.1f}%",
            f"   Profit Factor: {profit_factor:.2f}",
            ""
        ]

        if price_summary:
            text_body += [
                "PRICE ACTION SUMMARY:",
                f"   Opening: {format_currency(price_summary['opening'])}",
                f"   Closing: {format_currency(price_summary['closing'])}",
                f"   Day High: {format_currency(price_summary['high'])}",
                f"   Day Low: {format_currency(price_summary['low'])}",
                f"   Day Change: {format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)",
                f"   Total Candles: {price_summary['candles']}",
                ""
            ]

        text_body.append("TOP TRADES:")
        top_trades = trades_df.nlargest(5, 'Net_PnL')
        for idx, trade in top_trades.iterrows():
            text_body += [
                f"   Trade #{idx+1}: {trade['Type']} - {format_currency(trade['Net_PnL'])}",
                f"      Entry: {format_currency(trade['Entry_Price'])} @ {trade['Entry_Time']}",
                f"      Exit: {format_currency(trade['Exit_Price'])} @ {trade['Exit_Time']}",
                f"      Reason: {trade['Exit_Reason']}",
                ""
            ]

        text_body.append("Detailed trade history and minute-by-minute price data are attached.")
        text_body.append(f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}")

        text_body = "\n".join(text_body)

        html_body = f"""
<html>
  <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.5;">
    <h2 style="color: #2F6F8F;">Trading Performance Report — {today}</h2>
    <p style="font-size: 14px;">{status}</p>
    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
      <tr><th style="text-align:left; padding: 8px; background:#f2f2f2;">Metric</th><th style="text-align:left; padding: 8px; background:#f2f2f2;">Value</th></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Total Net P&L</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(total_pnl)}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Average P&L/Trade</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(avg_pnl)}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Best Trade</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(max_profit)}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Worst Trade</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(abs(max_loss))}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Total Trades</td><td style="padding:8px; border: 1px solid #ddd;">{num_trades}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Win Rate</td><td style="padding:8px; border: 1px solid #ddd;">{win_rate:.1f}%</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Profit Factor</td><td style="padding:8px; border: 1px solid #ddd;">{profit_factor:.2f}</td></tr>
    </table>
    """

        if price_summary:
            html_body += f"""
    <h3 style="color: #2F6F8F;">Price Action Summary</h3>
    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
      <tr><td style="padding:8px; border: 1px solid #ddd;">Opening</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(price_summary['opening'])}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Closing</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(price_summary['closing'])}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Day High</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(price_summary['high'])}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Day Low</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(price_summary['low'])}</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Day Change</td><td style="padding:8px; border: 1px solid #ddd;">{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</td></tr>
      <tr><td style="padding:8px; border: 1px solid #ddd;">Total Candles</td><td style="padding:8px; border: 1px solid #ddd;">{price_summary['candles']}</td></tr>
    </table>
    """

        html_body += """
    <h3 style="color: #2F6F8F;">Top Trades</h3>
    <table style="width: 100%; border-collapse: collapse;">
      <tr><th style="padding:8px; border: 1px solid #ddd; background:#f2f2f2;">Trade</th><th style="padding:8px; border: 1px solid #ddd; background:#f2f2f2;">Type</th><th style="padding:8px; border: 1px solid #ddd; background:#f2f2f2;">Net P&L</th><th style="padding:8px; border: 1px solid #ddd; background:#f2f2f2;">Entry</th><th style="padding:8px; border: 1px solid #ddd; background:#f2f2f2;">Exit</th><th style="padding:8px; border: 1px solid #ddd; background:#f2f2f2;">Reason</th></tr>
    """
        for idx, trade in top_trades.iterrows():
            html_body += f"""
      <tr>
        <td style=\"padding:8px; border: 1px solid #ddd;\">{idx+1}</td>
        <td style=\"padding:8px; border: 1px solid #ddd;\">{trade['Type']}</td>
        <td style=\"padding:8px; border: 1px solid #ddd;\">{format_currency(trade['Net_PnL'])}</td>
        <td style=\"padding:8px; border: 1px solid #ddd;\">{format_currency(trade['Entry_Price'])} @ {trade['Entry_Time']}</td>
        <td style=\"padding:8px; border: 1px solid #ddd;\">{format_currency(trade['Exit_Price'])} @ {trade['Exit_Time']}</td>
        <td style=\"padding:8px; border: 1px solid #ddd;\">{trade['Exit_Reason']}</td>
      </tr>
    """

        html_body += f"""
    </table>
    <p style=\"margin-top:20px;\">Detailed trade history and minute-by-minute price data are attached as CSV files.</p>
    <p style=\"font-size:12px;color:#666;\">Report generated at {datetime.now().strftime('%H:%M:%S IST')}</p>
  </body>
</html>
"""

        return text_body, html_body, True, trades_df, price_data, trade_path

    except Exception as e:
        return f"Error generating report: {e}", None, False, None, None, None


def send_email():
    """Constructs and sends the email with complete trade and price data."""
    text_body, html_body, should_attach, trades_df, price_df, trade_path = get_summary()

    msg = MIMEMultipart('mixed')
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(RECEIVER_EMAIL)
    msg['Subject'] = f"📈 Trading Report: {datetime.now().strftime('%d %b %Y')} | {datetime.now().strftime('%A')}"

    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(text_body, 'plain'))
    if html_body:
        alternative.attach(MIMEText(html_body, 'html'))
    msg.attach(alternative)

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