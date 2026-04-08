import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import glob

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
SENDER_EMAIL = os.getenv("SENDER_EMAIL") or os.getenv("EMAIL_SENDER")
RECEIVER_EMAIL = [email.strip() for email in os.getenv("RECEIVER_EMAIL", os.getenv("RECIPIENT_EMAIL", "")).split(',') if email.strip()]
APP_PASSWORD = os.getenv("APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
TRADE_DATA_PATH = os.getenv("TRADE_DATA_PATH", "./paper_trade_history.csv")
PRICE_HISTORY_PATH = os.getenv("PRICE_HISTORY_PATH", "./price_history.csv")
BACKTEST_RESULTS_PATH = os.getenv("BACKTEST_RESULTS_PATH", "./angel_backtest_results.csv")


def format_currency(value):
    try:
        return f"₹{float(value):,.2f}"
    except Exception:
        return f"₹{value}"


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_parse_datetime(value):
    if pd.isna(value):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(str(value), fmt)
        except Exception:
            continue
    try:
        return pd.to_datetime(value)
    except Exception:
        return None


def validate_trade_frame(df):
    required_columns = [
        "Trade_ID",
        "Entry_Time",
        "Exit_Time",
        "Type",
        "Entry_Price",
        "Exit_Price",
        "Net_PnL",
        "Exit_Reason"
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Trade file missing required columns: {', '.join(missing)}")

    df['Entry_Price'] = pd.to_numeric(df['Entry_Price'], errors='coerce')
    df['Exit_Price'] = pd.to_numeric(df['Exit_Price'], errors='coerce')
    df['Net_PnL'] = pd.to_numeric(df['Net_PnL'], errors='coerce')
    if 'Points' in df.columns:
        df['Points'] = pd.to_numeric(df['Points'], errors='coerce')
    else:
        df['Points'] = pd.Series([None] * len(df))

    df['Net_PnL'] = df['Net_PnL'].fillna(0.0)
    df['Entry_Price'] = df['Entry_Price'].fillna(0.0)
    df['Exit_Price'] = df['Exit_Price'].fillna(0.0)

    return df


def compute_trade_metrics(trades_df):
    df = validate_trade_frame(trades_df.copy())
    metrics = {}
    metrics['total_pnl'] = df['Net_PnL'].sum()
    metrics['num_trades'] = len(df)
    metrics['winning_trades'] = int((df['Net_PnL'] > 0).sum())
    metrics['losing_trades'] = int((df['Net_PnL'] < 0).sum())
    metrics['breakeven_trades'] = int((df['Net_PnL'] == 0).sum())
    metrics['avg_pnl'] = float(df['Net_PnL'].mean()) if metrics['num_trades'] > 0 else 0.0
    metrics['median_pnl'] = float(df['Net_PnL'].median()) if metrics['num_trades'] > 0 else 0.0
    metrics['std_pnl'] = float(df['Net_PnL'].std(ddof=0)) if metrics['num_trades'] > 0 else 0.0
    metrics['max_profit'] = float(df['Net_PnL'].max()) if metrics['num_trades'] > 0 else 0.0
    metrics['max_loss'] = float(df['Net_PnL'].min()) if metrics['num_trades'] > 0 else 0.0
    metrics['win_rate'] = (metrics['winning_trades'] / metrics['num_trades'] * 100) if metrics['num_trades'] > 0 else 0.0

    total_profit = df.loc[df['Net_PnL'] > 0, 'Net_PnL'].sum()
    total_loss = abs(df.loc[df['Net_PnL'] < 0, 'Net_PnL'].sum())
    metrics['profit_factor'] = (total_profit / total_loss) if total_loss > 0 else float('inf')
    metrics['expectancy'] = ((total_profit - total_loss) / metrics['num_trades']) if metrics['num_trades'] > 0 else 0.0
    metrics['avg_points'] = float(df['Points'].mean()) if 'Points' in df.columns and not df['Points'].isna().all() else None
    metrics['long_trades'] = int((df['Type'].str.upper() == 'LONG').sum()) if 'Type' in df.columns else 0
    metrics['short_trades'] = int((df['Type'].str.upper() == 'SHORT').sum()) if 'Type' in df.columns else 0

    equity = df['Net_PnL'].cumsum()
    high_watermark = equity.cummax()
    drawdown = equity - high_watermark
    metrics['max_drawdown'] = float(drawdown.min()) if not drawdown.empty else 0.0
    metrics['max_drawdown_pct'] = float((metrics['max_drawdown'] / high_watermark.max() * 100)) if high_watermark.max() > 0 else 0.0

    entry_times = df['Entry_Time'].apply(safe_parse_datetime)
    exit_times = df['Exit_Time'].apply(safe_parse_datetime)
    valid_duration = (exit_times - entry_times).dropna().dt.total_seconds() / 60.0
    metrics['avg_duration_min'] = float(valid_duration.mean()) if not valid_duration.empty else 0.0
    metrics['median_duration_min'] = float(valid_duration.median()) if not valid_duration.empty else 0.0

    return metrics


def read_price_history():
    if not os.path.exists(PRICE_HISTORY_PATH):
        return None, {}
    try:
        price_df = pd.read_csv(PRICE_HISTORY_PATH)
        if price_df.empty:
            return None, {}
        opening_price = safe_float(price_df['Price'].iloc[0])
        closing_price = safe_float(price_df['Price'].iloc[-1])
        high_price = safe_float(price_df['High'].max())
        low_price = safe_float(price_df['Low'].min())
        daily_change = closing_price - opening_price
        change_pct = (daily_change / opening_price * 100) if opening_price != 0 else 0.0
        summary = {
            'opening': opening_price,
            'closing': closing_price,
            'high': high_price,
            'low': low_price,
            'change': daily_change,
            'change_pct': change_pct,
            'candles': len(price_df)
        }
        return price_df, summary
    except Exception as e:
        print(f"⚠️ Could not read price history: {e}")
        return None, {}


def read_all_strategy_results():
    """Read results from all 4 strategies"""
    strategies_data = {}
    strategy_files = [
        "strategy_1_backtest_results.csv",
        "strategy_2_backtest_results.csv",
        "strategy_3_backtest_results.csv",
        "strategy_4_backtest_results.csv"
    ]
    
    for strategy_file in strategy_files:
        if os.path.exists(strategy_file):
            try:
                df = pd.read_csv(strategy_file)
                strategy_name = strategy_file.replace("_backtest_results.csv", "")
                metrics = compute_trade_metrics(df)
                strategies_data[strategy_name] = {
                    "df": df,
                    "metrics": metrics,
                    "file": strategy_file
                }
            except Exception as e:
                print(f"⚠️ Could not read {strategy_file}: {e}")
    
    return strategies_data


def get_summary():
    """Reads all strategy results and generates a comprehensive comparison report."""
    try:
        # Try to read multiple strategy results first
        strategies_data = read_all_strategy_results()
        
        if strategies_data:
            # Multiple strategies found - generate comparison report
            price_df, price_summary = read_price_history()
            
            # Find best strategy
            best_strategy = max(strategies_data.items(), key=lambda x: x[1]['metrics']['total_pnl'] if x[1]['metrics']['num_trades'] > 0 else float('-inf'))
            best_strategy_name, best_strategy_data = best_strategy
            metrics = best_strategy_data['metrics']
            trade_path = best_strategy_data['file']
            trades_df = best_strategy_data['df']
        else:
            # Fallback to single strategy result
            trade_path = TRADE_DATA_PATH if os.path.exists(TRADE_DATA_PATH) else BACKTEST_RESULTS_PATH
            if not os.path.exists(trade_path):
                return "Error: Trade results file not found.", None, None, None, trade_path

            trades_df = pd.read_csv(trade_path)
            if trades_df.empty:
                return "No trades executed today.", None, None, None, trade_path

            metrics = compute_trade_metrics(trades_df)
            price_df, price_summary = read_price_history()
            strategies_data = {}
            best_strategy_name = "Single Strategy"

        source_label = "BACKTEST" if "backtest" in trade_path.lower() else "PAPER TRADE"
        status = "✅ PROFIT" if metrics['total_pnl'] > 0 else ("⚠️ BREAKEVEN" if metrics['total_pnl'] == 0 else "🔻 LOSS")
        today = datetime.now().strftime("%d %b %Y")

        text_body = [
            f"TRADING PERFORMANCE REPORT - {today}",
            "=" * 70,
            status,
            f"Source: {source_label}",
            f"Best Performing Strategy: {best_strategy_name.upper()}" if strategies_data else "",
            "",
            "PROFIT & LOSS SUMMARY:",
            f"   Total Net P&L: {format_currency(metrics['total_pnl'])}",
            f"   Average P&L/Trade: {format_currency(metrics['avg_pnl'])}",
            f"   Median P&L/Trade: {format_currency(metrics['median_pnl'])}",
            f"   Trade Std Dev: {format_currency(metrics['std_pnl'])}",
            f"   Profit Factor: {metrics['profit_factor']:.2f}" if metrics['profit_factor'] != float('inf') else f"   Profit Factor: Infinite (No losses)",
            f"   Expectancy: {format_currency(metrics['expectancy'])}",
            "",
            "TRADE STATISTICS:",
            f"   Total Trades: {metrics['num_trades']}",
            f"   Long Trades: {metrics['long_trades']}",
            f"   Short Trades: {metrics['short_trades']}",
            f"   Winning Trades: {metrics['winning_trades']}",
            f"   Losing Trades: {metrics['losing_trades']}",
            f"   Breakeven Trades: {metrics['breakeven_trades']}",
            f"   Win Rate: {metrics['win_rate']:.1f}%",
            f"   Max Drawdown: {format_currency(metrics['max_drawdown'])} ({metrics['max_drawdown_pct']:.2f}%)",
            "",
            "DURATION METRICS:",
            f"   Avg Time in trade: {metrics['avg_duration_min']:.1f} minutes",
            f"   Median Time in trade: {metrics['median_duration_min']:.1f} minutes",
            ""
        ]

        if metrics['avg_points'] is not None:
            text_body.append(f"   Average Points per Trade: {metrics['avg_points']:.2f}")
            text_body.append("")

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

        # Add strategy comparison if multiple strategies
        if strategies_data:
            text_body.append("STRATEGY COMPARISON:")
            for strat_name, strat_data in sorted(strategies_data.items(), key=lambda x: x[1]['metrics']['total_pnl'], reverse=True):
                m = strat_data['metrics']
                indicator = "🏆" if strat_name == best_strategy_name else "  "
                text_body.append(f"{indicator} {strat_name.upper()}: ₹{m['total_pnl']:,.2f} PnL | {m['num_trades']} trades | {m['win_rate']:.1f}% win rate")
            text_body.append("")

        top_trades = trades_df.nlargest(5, 'Net_PnL')
        text_body.append("TOP 5 TRADES:")
        for idx, trade in top_trades.iterrows():
            text_body += [
                f"   Trade #{idx+1}: {trade.get('Type', 'N/A')} | PnL: {format_currency(trade.get('Net_PnL', 0))}",
                f"      Entry: {format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}",
                f"      Exit: {format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}",
                f"      Reason: {trade.get('Exit_Reason', '')}",
                ""
            ]

        text_body.append("Detailed trade and price history data are attached for forward testing review.")
        text_body.append(f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}")
        text_body = "\n".join([line for line in text_body if line])

        html_body = [
            f"<html><body style='font-family: Arial, sans-serif; color: #333; line-height: 1.5;'>",
            f"<h2 style='color: #2F6F8F;'>Trading Performance Report — {today}</h2>",
            f"<p style='font-size: 14px;'>{status}</p>",
            f"<p><strong>Source:</strong> {source_label}</p>"
        ]
        
        if strategies_data:
            html_body.append(f"<p><strong>Best Strategy:</strong> {best_strategy_name.upper()}</p>")

        html_body += [
            "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px;'>",
            "<tr><th style='text-align:left; padding: 8px; background:#f2f2f2;'>Metric</th><th style='text-align:left; padding: 8px; background:#f2f2f2;'>Value</th></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Total Net P&L</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['total_pnl'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Avg P&L/Trade</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['avg_pnl'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Median P&L/Trade</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['median_pnl'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Profit Factor</td><td style='padding:8px; border: 1px solid #ddd;'>{metrics['profit_factor']:.2f if metrics['profit_factor'] != float('inf') else 'Infinite (No losses)'}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Expectancy</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['expectancy'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Win Rate</td><td style='padding:8px; border: 1px solid #ddd;'>{metrics['win_rate']:.1f}%</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Max Drawdown</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['max_drawdown'])} ({metrics['max_drawdown_pct']:.2f}%)</td></tr>",
            "</table>"
        ]

        if price_summary:
            html_body += [
                "<h3 style='color: #2F6F8F;'>Price Action Summary</h3>",
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px;'>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Opening</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['opening'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Closing</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['closing'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Day High</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['high'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Day Low</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['low'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Day Change</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Total Candles</td><td style='padding:8px; border: 1px solid #ddd;'>{price_summary['candles']}</td></tr>",
                "</table>"
            ]

        if strategies_data:
            html_body += [
                "<h3 style='color: #2F6F8F;'>Strategy Comparison</h3>",
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px;'>",
                "<tr><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Strategy</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Total PnL</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Trades</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Win Rate</th></tr>"
            ]
            for strat_name, strat_data in sorted(strategies_data.items(), key=lambda x: x[1]['metrics']['total_pnl'], reverse=True):
                m = strat_data['metrics']
                bg_color = "#e8f5e9" if strat_name == best_strategy_name else "transparent"
                html_body += [
                    f"<tr style='background-color: {bg_color};'>",
                    f"<td style='padding:8px; border: 1px solid #ddd;'>{strat_name.upper()}</td>",
                    f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(m['total_pnl'])}</td>",
                    f"<td style='padding:8px; border: 1px solid #ddd;'>{m['num_trades']}</td>",
                    f"<td style='padding:8px; border: 1px solid #ddd;'>{m['win_rate']:.1f}%</td>",
                    "</tr>"
                ]
            html_body.append("</table>")

        html_body += [
            "<h3 style='color: #2F6F8F;'>Top 5 Trades</h3>",
            "<table style='width: 100%; border-collapse: collapse;'>",
            "<tr><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>#</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Type</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Net P&L</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Entry</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Exit</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Reason</th></tr>"
        ]

        for idx, trade in top_trades.iterrows():
            html_body += [
                "<tr>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{idx+1}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{trade.get('Type', 'N/A')}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(trade.get('Net_PnL', 0))}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{trade.get('Exit_Reason', '')}</td>",
                "</tr>"
            ]

        html_body += [
            "</table>",
            "<p style='margin-top:20px;'>Detailed trade and price history data are attached for forward testing review.</p>",
            f"<p style='font-size:12px;color:#666;'>Report generated at {datetime.now().strftime('%H:%M:%S IST')}</p>",
            "</body></html>"
        ]

        return text_body, '\n'.join(html_body), True, trades_df, price_df, trade_path

    except Exception as e:
        return f"Error generating report: {e}", None, False, None, None, None


def send_email():
    """Constructs and sends the email with complete trade and price data."""
    text_body, html_body, should_attach, trades_df, price_df, trade_path = get_summary()

    if not SENDER_EMAIL or not APP_PASSWORD or not RECEIVER_EMAIL:
        print("❌ Email settings are incomplete. Set SENDER_EMAIL, APP_PASSWORD and RECEIVER_EMAIL.")
        return

    msg = MIMEMultipart('mixed')
    msg['From'] = SENDER_EMAIL
    msg['To'] = SENDER_EMAIL
    msg['Bcc'] = ", ".join(RECEIVER_EMAIL)
    msg['Subject'] = f"📈 Trading Report: {datetime.now().strftime('%d %b %Y')} | {datetime.now().strftime('%A')}"

    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(text_body, 'plain'))
    if html_body:
        alternative.attach(MIMEText(html_body, 'html'))
    msg.attach(alternative)

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

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        print(f"✅ Email sent successfully to {len(RECEIVER_EMAIL)} recipient(s) via BCC")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")



def format_currency(value):
    try:
        return f"₹{float(value):,.2f}"
    except Exception:
        return f"₹{value}"


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_parse_datetime(value):
    if pd.isna(value):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(str(value), fmt)
        except Exception:
            continue
    try:
        return pd.to_datetime(value)
    except Exception:
        return None


def validate_trade_frame(df):
    required_columns = [
        "Trade_ID",
        "Entry_Time",
        "Exit_Time",
        "Type",
        "Entry_Price",
        "Exit_Price",
        "Net_PnL",
        "Exit_Reason"
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Trade file missing required columns: {', '.join(missing)}")

    df['Entry_Price'] = pd.to_numeric(df['Entry_Price'], errors='coerce')
    df['Exit_Price'] = pd.to_numeric(df['Exit_Price'], errors='coerce')
    df['Net_PnL'] = pd.to_numeric(df['Net_PnL'], errors='coerce')
    if 'Points' in df.columns:
        df['Points'] = pd.to_numeric(df['Points'], errors='coerce')
    else:
        df['Points'] = pd.Series([None] * len(df))

    df['Net_PnL'] = df['Net_PnL'].fillna(0.0)
    df['Entry_Price'] = df['Entry_Price'].fillna(0.0)
    df['Exit_Price'] = df['Exit_Price'].fillna(0.0)

    return df


def compute_trade_metrics(trades_df):
    df = validate_trade_frame(trades_df.copy())
    metrics = {}
    metrics['total_pnl'] = df['Net_PnL'].sum()
    metrics['num_trades'] = len(df)
    metrics['winning_trades'] = int((df['Net_PnL'] > 0).sum())
    metrics['losing_trades'] = int((df['Net_PnL'] < 0).sum())
    metrics['breakeven_trades'] = int((df['Net_PnL'] == 0).sum())
    metrics['avg_pnl'] = float(df['Net_PnL'].mean()) if metrics['num_trades'] > 0 else 0.0
    metrics['median_pnl'] = float(df['Net_PnL'].median()) if metrics['num_trades'] > 0 else 0.0
    metrics['std_pnl'] = float(df['Net_PnL'].std(ddof=0)) if metrics['num_trades'] > 0 else 0.0
    metrics['max_profit'] = float(df['Net_PnL'].max()) if metrics['num_trades'] > 0 else 0.0
    metrics['max_loss'] = float(df['Net_PnL'].min()) if metrics['num_trades'] > 0 else 0.0
    metrics['win_rate'] = (metrics['winning_trades'] / metrics['num_trades'] * 100) if metrics['num_trades'] > 0 else 0.0

    total_profit = df.loc[df['Net_PnL'] > 0, 'Net_PnL'].sum()
    total_loss = abs(df.loc[df['Net_PnL'] < 0, 'Net_PnL'].sum())
    metrics['profit_factor'] = (total_profit / total_loss) if total_loss > 0 else float('inf')
    metrics['expectancy'] = ((total_profit - total_loss) / metrics['num_trades']) if metrics['num_trades'] > 0 else 0.0
    metrics['avg_points'] = float(df['Points'].mean()) if 'Points' in df.columns and not df['Points'].isna().all() else None
    metrics['long_trades'] = int((df['Type'].str.upper() == 'LONG').sum()) if 'Type' in df.columns else 0
    metrics['short_trades'] = int((df['Type'].str.upper() == 'SHORT').sum()) if 'Type' in df.columns else 0

    equity = df['Net_PnL'].cumsum()
    high_watermark = equity.cummax()
    drawdown = equity - high_watermark
    metrics['max_drawdown'] = float(drawdown.min()) if not drawdown.empty else 0.0
    metrics['max_drawdown_pct'] = float((metrics['max_drawdown'] / high_watermark.max() * 100)) if high_watermark.max() > 0 else 0.0

    entry_times = df['Entry_Time'].apply(safe_parse_datetime)
    exit_times = df['Exit_Time'].apply(safe_parse_datetime)
    valid_duration = (exit_times - entry_times).dropna().dt.total_seconds() / 60.0
    metrics['avg_duration_min'] = float(valid_duration.mean()) if not valid_duration.empty else 0.0
    metrics['median_duration_min'] = float(valid_duration.median()) if not valid_duration.empty else 0.0

    return metrics


def read_price_history():
    if not os.path.exists(PRICE_HISTORY_PATH):
        return None, {}
    try:
        price_df = pd.read_csv(PRICE_HISTORY_PATH)
        if price_df.empty:
            return None, {}
        opening_price = safe_float(price_df['Price'].iloc[0])
        closing_price = safe_float(price_df['Price'].iloc[-1])
        high_price = safe_float(price_df['High'].max())
        low_price = safe_float(price_df['Low'].min())
        daily_change = closing_price - opening_price
        change_pct = (daily_change / opening_price * 100) if opening_price != 0 else 0.0
        summary = {
            'opening': opening_price,
            'closing': closing_price,
            'high': high_price,
            'low': low_price,
            'change': daily_change,
            'change_pct': change_pct,
            'candles': len(price_df)
        }
        return price_df, summary
    except Exception as e:
        print(f"⚠️ Could not read price history: {e}")
        return None, {}


def get_summary():
    """Reads trade data and generates a detailed summary with price information."""
    try:
        trade_path = TRADE_DATA_PATH if os.path.exists(TRADE_DATA_PATH) else BACKTEST_RESULTS_PATH
        if not os.path.exists(trade_path):
            return "Error: Trade results file not found.", None, None, None, trade_path

        trades_df = pd.read_csv(trade_path)
        if trades_df.empty:
            return "No trades executed today.", None, None, None, trade_path

        metrics = compute_trade_metrics(trades_df)
        price_df, price_summary = read_price_history()
        source_label = "PAPER TRADE" if os.path.exists(TRADE_DATA_PATH) else "BACKTEST"
        status = "✅ PROFIT" if metrics['total_pnl'] > 0 else ("⚠️ BREAKEVEN" if metrics['total_pnl'] == 0 else "🔻 LOSS")
        today = datetime.now().strftime("%d %b %Y")

        text_body = [
            f"TRADING PERFORMANCE REPORT - {today}",
            "=" * 70,
            status,
            f"Source: {source_label}",
            "",
            "PROFIT & LOSS SUMMARY:",
            f"   Total Net P&L: {format_currency(metrics['total_pnl'])}",
            f"   Average P&L/Trade: {format_currency(metrics['avg_pnl'])}",
            f"   Median P&L/Trade: {format_currency(metrics['median_pnl'])}",
            f"   Trade Std Dev: {format_currency(metrics['std_pnl'])}",
            f"   Profit Factor: {metrics['profit_factor']:.2f}",
            f"   Expectancy: {format_currency(metrics['expectancy'])}",
            "",
            "TRADE STATISTICS:",
            f"   Total Trades: {metrics['num_trades']}",
            f"   Long Trades: {metrics['long_trades']}",
            f"   Short Trades: {metrics['short_trades']}",
            f"   Winning Trades: {metrics['winning_trades']}",
            f"   Losing Trades: {metrics['losing_trades']}",
            f"   Breakeven Trades: {metrics['breakeven_trades']}",
            f"   Win Rate: {metrics['win_rate']:.1f}%",
            f"   Max Drawdown: {format_currency(metrics['max_drawdown'])} ({metrics['max_drawdown_pct']:.2f}%)",
            "",
            "DURATION METRICS:",
            f"   Avg Time in trade: {metrics['avg_duration_min']:.1f} minutes",
            f"   Median Time in trade: {metrics['median_duration_min']:.1f} minutes",
            ""
        ]

        if metrics['avg_points'] is not None:
            text_body.append(f"   Average Points per Trade: {metrics['avg_points']:.2f}")
            text_body.append("")

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

        top_trades = trades_df.nlargest(5, 'Net_PnL')
        text_body.append("TOP 5 TRADES:")
        for idx, trade in top_trades.iterrows():
            text_body += [
                f"   Trade #{idx+1}: {trade.get('Type', 'N/A')} | PnL: {format_currency(trade.get('Net_PnL', 0))}",
                f"      Entry: {format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}",
                f"      Exit: {format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}",
                f"      Reason: {trade.get('Exit_Reason', '')}",
                ""
            ]

        text_body.append("Detailed trade and price history data are attached for forward testing review.")
        text_body.append(f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}")
        text_body = "\n".join(text_body)

        html_body = [
            f"<html><body style='font-family: Arial, sans-serif; color: #333; line-height: 1.5;'>",
            f"<h2 style='color: #2F6F8F;'>Trading Performance Report — {today}</h2>",
            f"<p style='font-size: 14px;'>{status}</p>",
            f"<p><strong>Source:</strong> {source_label}</p>",
            "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px;'>",
            "<tr><th style='text-align:left; padding: 8px; background:#f2f2f2;'>Metric</th><th style='text-align:left; padding: 8px; background:#f2f2f2;'>Value</th></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Total Net P&L</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['total_pnl'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Avg P&L/Trade</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['avg_pnl'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Median P&L/Trade</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['median_pnl'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Profit Factor</td><td style='padding:8px; border: 1px solid #ddd;'>{metrics['profit_factor']:.2f}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Expectancy</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['expectancy'])}</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Win Rate</td><td style='padding:8px; border: 1px solid #ddd;'>{metrics['win_rate']:.1f}%</td></tr>",
            f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Max Drawdown</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(metrics['max_drawdown'])} ({metrics['max_drawdown_pct']:.2f}%)</td></tr>",
            "</table>"
        ]

        if price_summary:
            html_body += [
                "<h3 style='color: #2F6F8F;'>Price Action Summary</h3>",
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px;'>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Opening</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['opening'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Closing</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['closing'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Day High</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['high'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Day Low</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['low'])}</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Day Change</td><td style='padding:8px; border: 1px solid #ddd;'>{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</td></tr>",
                f"<tr><td style='padding:8px; border: 1px solid #ddd;'>Total Candles</td><td style='padding:8px; border: 1px solid #ddd;'>{price_summary['candles']}</td></tr>",
                "</table>"
            ]

        html_body += [
            "<h3 style='color: #2F6F8F;'>Top 5 Trades</h3>",
            "<table style='width: 100%; border-collapse: collapse;'>",
            "<tr><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>#</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Type</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Net P&L</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Entry</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Exit</th><th style='padding:8px; border: 1px solid #ddd; background:#f2f2f2;'>Reason</th></tr>"
        ]

        for idx, trade in top_trades.iterrows():
            html_body += [
                "<tr>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{idx+1}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{trade.get('Type', 'N/A')}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(trade.get('Net_PnL', 0))}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}</td>",
                f"<td style='padding:8px; border: 1px solid #ddd;'>{trade.get('Exit_Reason', '')}</td>",
                "</tr>"
            ]

        html_body += [
            "</table>",
            "<p style='margin-top:20px;'>Detailed trade and price history data are attached for forward testing review.</p>",
            f"<p style='font-size:12px;color:#666;'>Report generated at {datetime.now().strftime('%H:%M:%S IST')}</p>",
            "</body></html>"
        ]

        return text_body, '\n'.join(html_body), True, trades_df, price_df, trade_path

    except Exception as e:
        return f"Error generating report: {e}", None, False, None, None, None


def send_email():
    """Constructs and sends the email with complete trade and price data."""
    text_body, html_body, should_attach, trades_df, price_df, trade_path = get_summary()

    if not SENDER_EMAIL or not APP_PASSWORD or not RECEIVER_EMAIL:
        print("❌ Email settings are incomplete. Set SENDER_EMAIL, APP_PASSWORD and RECEIVER_EMAIL.")
        return

    msg = MIMEMultipart('mixed')
    msg['From'] = SENDER_EMAIL
    msg['To'] = SENDER_EMAIL  # Put sender in To field
    msg['Bcc'] = ", ".join(RECEIVER_EMAIL)  # All recipients in BCC
    msg['Subject'] = f"📈 Trading Report: {datetime.now().strftime('%d %b %Y')} | {datetime.now().strftime('%A')}"

    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(text_body, 'plain'))
    if html_body:
        alternative.attach(MIMEText(html_body, 'html'))
    msg.attach(alternative)

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

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())  # Send to all recipients
        server.quit()
        print(f"✅ Email sent successfully to {len(RECEIVER_EMAIL)} recipient(s) via BCC")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

