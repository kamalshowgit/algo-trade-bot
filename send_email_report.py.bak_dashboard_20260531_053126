import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL") or os.getenv("EMAIL_SENDER")
RECEIVER_EMAIL = [
    email.strip()
    for email in os.getenv("RECEIVER_EMAIL", os.getenv("RECIPIENT_EMAIL", "")).split(",")
    if email.strip()
]
APP_PASSWORD = os.getenv("APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
TRADE_DATA_PATH = os.getenv("TRADE_DATA_PATH", "./paper_trade_history.csv")
PRICE_HISTORY_PATH = os.getenv("PRICE_HISTORY_PATH", "./price_history.csv")
BACKTEST_RESULTS_PATH = os.getenv("BACKTEST_RESULTS_PATH", "./angel_backtest_results.csv")
PAPER_MODE = os.getenv("PAPER_MODE", "false").strip().lower() == "true"
EMPTY_TRADE_COLUMNS = [
    "Trade_ID",
    "Entry_Time",
    "Exit_Time",
    "Type",
    "Entry_Price",
    "Exit_Price",
    "Points",
    "Net_PnL",
    "Exit_Reason",
    "Entry_RSI",
    "Entry_EMA_F",
    "Exit_RSI",
    "Strategy",
]


def format_currency(value):
    try:
        return f"Rs {float(value):,.2f}"
    except Exception:
        return f"Rs {value}"


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_parse_datetime(value):
    if pd.isna(value):
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y %H:%M",
    ):
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
        "Exit_Reason",
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Trade file missing required columns: {', '.join(missing)}")

    df = df.copy()
    df["Entry_Price"] = pd.to_numeric(df["Entry_Price"], errors="coerce").fillna(0.0)
    df["Exit_Price"] = pd.to_numeric(df["Exit_Price"], errors="coerce").fillna(0.0)
    df["Net_PnL"] = pd.to_numeric(df["Net_PnL"], errors="coerce").fillna(0.0)
    if "Points" in df.columns:
        df["Points"] = pd.to_numeric(df["Points"], errors="coerce")
    else:
        df["Points"] = pd.Series([None] * len(df))
    return df


def compute_trade_metrics(trades_df):
    df = validate_trade_frame(trades_df)
    metrics = {}
    metrics["total_pnl"] = float(df["Net_PnL"].sum())
    metrics["num_trades"] = len(df)
    metrics["winning_trades"] = int((df["Net_PnL"] > 0).sum())
    metrics["losing_trades"] = int((df["Net_PnL"] < 0).sum())
    metrics["breakeven_trades"] = int((df["Net_PnL"] == 0).sum())
    metrics["avg_pnl"] = float(df["Net_PnL"].mean()) if metrics["num_trades"] else 0.0
    metrics["median_pnl"] = float(df["Net_PnL"].median()) if metrics["num_trades"] else 0.0
    metrics["std_pnl"] = float(df["Net_PnL"].std(ddof=0)) if metrics["num_trades"] else 0.0
    metrics["max_profit"] = float(df["Net_PnL"].max()) if metrics["num_trades"] else 0.0
    metrics["max_loss"] = float(df["Net_PnL"].min()) if metrics["num_trades"] else 0.0
    metrics["win_rate"] = (
        metrics["winning_trades"] / metrics["num_trades"] * 100 if metrics["num_trades"] else 0.0
    )

    total_profit = float(df.loc[df["Net_PnL"] > 0, "Net_PnL"].sum())
    total_loss = abs(float(df.loc[df["Net_PnL"] < 0, "Net_PnL"].sum()))
    metrics["profit_factor"] = total_profit / total_loss if total_loss > 0 else float("inf")
    metrics["expectancy"] = (
        (total_profit - total_loss) / metrics["num_trades"] if metrics["num_trades"] else 0.0
    )
    metrics["avg_points"] = (
        float(df["Points"].mean()) if "Points" in df.columns and not df["Points"].isna().all() else None
    )
    metrics["long_trades"] = int((df["Type"].str.upper() == "LONG").sum()) if "Type" in df.columns else 0
    metrics["short_trades"] = int((df["Type"].str.upper() == "SHORT").sum()) if "Type" in df.columns else 0

    equity = df["Net_PnL"].cumsum()
    high_watermark = equity.cummax()
    drawdown = equity - high_watermark
    metrics["max_drawdown"] = float(drawdown.min()) if not drawdown.empty else 0.0
    metrics["max_drawdown_pct"] = (
        float(metrics["max_drawdown"] / high_watermark.max() * 100) if high_watermark.max() > 0 else 0.0
    )

    entry_times = df["Entry_Time"].apply(safe_parse_datetime)
    exit_times = df["Exit_Time"].apply(safe_parse_datetime)
    valid_duration = (exit_times - entry_times).dropna().dt.total_seconds() / 60.0
    metrics["avg_duration_min"] = float(valid_duration.mean()) if not valid_duration.empty else 0.0
    metrics["median_duration_min"] = float(valid_duration.median()) if not valid_duration.empty else 0.0
    return metrics


def read_price_history():
    if not os.path.exists(PRICE_HISTORY_PATH):
        return None, {}
    try:
        price_df = pd.read_csv(PRICE_HISTORY_PATH)
        if price_df.empty:
            return None, {}
        summary = {
            "opening": safe_float(price_df["Price"].iloc[0]),
            "closing": safe_float(price_df["Price"].iloc[-1]),
            "high": safe_float(price_df["High"].max()),
            "low": safe_float(price_df["Low"].min()),
            "candles": len(price_df),
        }
        summary["change"] = summary["closing"] - summary["opening"]
        summary["change_pct"] = (
            summary["change"] / summary["opening"] * 100 if summary["opening"] else 0.0
        )
        return price_df, summary
    except Exception as exc:
        print(f"⚠️ Could not read price history: {exc}")
        return None, {}


def read_backtest_strategy_results():
    strategies = {}
    for strategy_name in ("strategy_1", "strategy_2", "strategy_3", "strategy_4"):
        path = f"{strategy_name}_backtest_results.csv"
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path)
            if df.empty:
                continue
            strategies[strategy_name] = {
                "df": validate_trade_frame(df),
                "metrics": compute_trade_metrics(df),
                "file": path,
            }
        except Exception as exc:
            print(f"⚠️ Could not read {path}: {exc}")
    return strategies


def choose_report_source():
    if PAPER_MODE or os.path.exists(TRADE_DATA_PATH):
        try:
            trades_df = pd.read_csv(TRADE_DATA_PATH) if os.path.exists(TRADE_DATA_PATH) else pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
        except pd.errors.EmptyDataError:
            trades_df = pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
        return {
            "source_label": "PAPER TRADE",
            "trade_path": TRADE_DATA_PATH,
            "trades_df": validate_trade_frame(trades_df) if not trades_df.empty else trades_df,
            "strategies_data": {},
            "best_strategy_name": trades_df["Strategy"].iloc[0] if not trades_df.empty and "Strategy" in trades_df.columns else None,
        }

    strategies_data = read_backtest_strategy_results()
    if strategies_data:
        best_strategy_name = max(
            strategies_data.items(),
            key=lambda item: item[1]["metrics"]["total_pnl"],
        )[0]
        best_strategy = strategies_data[best_strategy_name]
        return {
            "source_label": "BACKTEST",
            "trade_path": best_strategy["file"],
            "trades_df": best_strategy["df"],
            "strategies_data": strategies_data,
            "best_strategy_name": best_strategy_name,
        }

    if os.path.exists(BACKTEST_RESULTS_PATH):
        trades_df = pd.read_csv(BACKTEST_RESULTS_PATH)
        if not trades_df.empty:
            return {
                "source_label": "BACKTEST",
                "trade_path": BACKTEST_RESULTS_PATH,
                "trades_df": validate_trade_frame(trades_df),
                "strategies_data": {},
                "best_strategy_name": trades_df["Strategy"].iloc[0] if "Strategy" in trades_df.columns else None,
            }

    return None


def build_report_summary():
    source = choose_report_source()
    if source is None:
        return "Error: Trade results file not found.", None, False, None, None, None

    trades_df = source["trades_df"]
    if trades_df.empty:
        price_df, price_summary = read_price_history()
        today = datetime.now().strftime("%d %b %Y")
        text_body = [
            f"TRADING PERFORMANCE REPORT - {today}",
            "=" * 60,
            "Status: NO TRADES",
            f"Source: {source['source_label']}",
            "",
            "No trades were executed in this session.",
        ]
        if price_summary:
            text_body += [
                "",
                "PRICE ACTION SUMMARY:",
                f"Opening: {format_currency(price_summary['opening'])}",
                f"Closing: {format_currency(price_summary['closing'])}",
                f"Day High: {format_currency(price_summary['high'])}",
                f"Day Low: {format_currency(price_summary['low'])}",
                f"Day Change: {format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)",
                f"Total Candles: {price_summary['candles']}",
            ]
        text_body += [
            "",
            f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}",
        ]

        html_body = [
            "<html><body style='font-family: Arial, sans-serif; color: #333;'>",
            f"<h2>Trading Performance Report - {today}</h2>",
            "<p><strong>Status:</strong> NO TRADES</p>",
            f"<p><strong>Source:</strong> {source['source_label']}</p>",
            "<p>No trades were executed in this session.</p>",
        ]
        if price_summary:
            html_body += [
                "<h3>Price Action Summary</h3>",
                "<table style='border-collapse: collapse; width: 100%;'>",
                f"<tr><td style='border:1px solid #ddd; padding:8px;'>Opening</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['opening'])}</td></tr>",
                f"<tr><td style='border:1px solid #ddd; padding:8px;'>Closing</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['closing'])}</td></tr>",
                f"<tr><td style='border:1px solid #ddd; padding:8px;'>Day High</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['high'])}</td></tr>",
                f"<tr><td style='border:1px solid #ddd; padding:8px;'>Day Low</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['low'])}</td></tr>",
                f"<tr><td style='border:1px solid #ddd; padding:8px;'>Day Change</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</td></tr>",
                f"<tr><td style='border:1px solid #ddd; padding:8px;'>Total Candles</td><td style='border:1px solid #ddd; padding:8px;'>{price_summary['candles']}</td></tr>",
                "</table>",
            ]
        html_body += [
            f"<p style='font-size:12px; color:#666;'>Report generated at {datetime.now().strftime('%H:%M:%S IST')}</p>",
            "</body></html>",
        ]
        return "\n".join(text_body), "\n".join(html_body), True, trades_df, price_df, source["trade_path"]

    metrics = compute_trade_metrics(trades_df)
    price_df, price_summary = read_price_history()
    strategies_data = source["strategies_data"]
    best_strategy_name = source["best_strategy_name"]
    today = datetime.now().strftime("%d %b %Y")
    status = (
        "PROFIT" if metrics["total_pnl"] > 0 else "BREAKEVEN" if metrics["total_pnl"] == 0 else "LOSS"
    )

    text_body = [
        f"TRADING PERFORMANCE REPORT - {today}",
        "=" * 60,
        f"Status: {status}",
        f"Source: {source['source_label']}",
    ]
    if best_strategy_name:
        text_body.append(f"Strategy: {str(best_strategy_name).upper()}")

    text_body += [
        "",
        "PROFIT AND LOSS SUMMARY:",
        f"Total Net PnL: {format_currency(metrics['total_pnl'])}",
        f"Average PnL per Trade: {format_currency(metrics['avg_pnl'])}",
        f"Median PnL per Trade: {format_currency(metrics['median_pnl'])}",
        f"Trade Std Dev: {format_currency(metrics['std_pnl'])}",
        (
            "Profit Factor: Infinite (No losses)"
            if metrics["profit_factor"] == float("inf")
            else f"Profit Factor: {metrics['profit_factor']:.2f}"
        ),
        f"Expectancy: {format_currency(metrics['expectancy'])}",
        "",
        "TRADE STATISTICS:",
        f"Total Trades: {metrics['num_trades']}",
        f"Long Trades: {metrics['long_trades']}",
        f"Short Trades: {metrics['short_trades']}",
        f"Winning Trades: {metrics['winning_trades']}",
        f"Losing Trades: {metrics['losing_trades']}",
        f"Breakeven Trades: {metrics['breakeven_trades']}",
        f"Win Rate: {metrics['win_rate']:.1f}%",
        f"Max Drawdown: {format_currency(metrics['max_drawdown'])} ({metrics['max_drawdown_pct']:.2f}%)",
        "",
        "DURATION METRICS:",
        f"Average Time in Trade: {metrics['avg_duration_min']:.1f} minutes",
        f"Median Time in Trade: {metrics['median_duration_min']:.1f} minutes",
    ]

    if metrics["avg_points"] is not None:
        text_body.append(f"Average Points per Trade: {metrics['avg_points']:.2f}")

    if price_summary:
        text_body += [
            "",
            "PRICE ACTION SUMMARY:",
            f"Opening: {format_currency(price_summary['opening'])}",
            f"Closing: {format_currency(price_summary['closing'])}",
            f"Day High: {format_currency(price_summary['high'])}",
            f"Day Low: {format_currency(price_summary['low'])}",
            f"Day Change: {format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)",
            f"Total Candles: {price_summary['candles']}",
        ]

    if strategies_data:
        text_body += ["", "STRATEGY COMPARISON:"]
        for strategy_name, strategy_data in sorted(
            strategies_data.items(),
            key=lambda item: item[1]["metrics"]["total_pnl"],
            reverse=True,
        ):
            strategy_metrics = strategy_data["metrics"]
            prefix = "* " if strategy_name == best_strategy_name else "- "
            text_body.append(
                f"{prefix}{strategy_name.upper()}: {format_currency(strategy_metrics['total_pnl'])} | "
                f"{strategy_metrics['num_trades']} trades | {strategy_metrics['win_rate']:.1f}% win rate"
            )

    text_body += ["", "TOP 5 TRADES:"]
    for idx, trade in trades_df.nlargest(5, "Net_PnL").iterrows():
        text_body += [
            f"Trade #{idx + 1}: {trade.get('Type', 'N/A')} | PnL: {format_currency(trade.get('Net_PnL', 0))}",
            f"  Entry: {format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}",
            f"  Exit: {format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}",
            f"  Reason: {trade.get('Exit_Reason', '')}",
        ]

    text_body += [
        "",
        "Detailed trade and price history data are attached for review.",
        f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}",
    ]

    html_rows = [
        f"<tr><td>Total Net PnL</td><td>{format_currency(metrics['total_pnl'])}</td></tr>",
        f"<tr><td>Average PnL per Trade</td><td>{format_currency(metrics['avg_pnl'])}</td></tr>",
        f"<tr><td>Median PnL per Trade</td><td>{format_currency(metrics['median_pnl'])}</td></tr>",
        (
            "<tr><td>Profit Factor</td><td>Infinite (No losses)</td></tr>"
            if metrics["profit_factor"] == float("inf")
            else f"<tr><td>Profit Factor</td><td>{metrics['profit_factor']:.2f}</td></tr>"
        ),
        f"<tr><td>Expectancy</td><td>{format_currency(metrics['expectancy'])}</td></tr>",
        f"<tr><td>Win Rate</td><td>{metrics['win_rate']:.1f}%</td></tr>",
        f"<tr><td>Max Drawdown</td><td>{format_currency(metrics['max_drawdown'])} ({metrics['max_drawdown_pct']:.2f}%)</td></tr>",
    ]

    html_body = [
        "<html><body style='font-family: Arial, sans-serif; color: #333;'>",
        f"<h2>Trading Performance Report - {today}</h2>",
        f"<p><strong>Status:</strong> {status}</p>",
        f"<p><strong>Source:</strong> {source['source_label']}</p>",
    ]
    if best_strategy_name:
        html_body.append(f"<p><strong>Strategy:</strong> {str(best_strategy_name).upper()}</p>")

    html_body += [
        "<table style='border-collapse: collapse; width: 100%;'>",
        "<tr><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Metric</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Value</th></tr>",
    ]
    for row in html_rows:
        html_body.append(row.replace("<td>", "<td style='border:1px solid #ddd; padding:8px;'>"))
    html_body.append("</table>")

    if price_summary:
        html_body += [
            "<h3>Price Action Summary</h3>",
            "<table style='border-collapse: collapse; width: 100%;'>",
            f"<tr><td style='border:1px solid #ddd; padding:8px;'>Opening</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['opening'])}</td></tr>",
            f"<tr><td style='border:1px solid #ddd; padding:8px;'>Closing</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['closing'])}</td></tr>",
            f"<tr><td style='border:1px solid #ddd; padding:8px;'>Day High</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['high'])}</td></tr>",
            f"<tr><td style='border:1px solid #ddd; padding:8px;'>Day Low</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['low'])}</td></tr>",
            f"<tr><td style='border:1px solid #ddd; padding:8px;'>Day Change</td><td style='border:1px solid #ddd; padding:8px;'>{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</td></tr>",
            f"<tr><td style='border:1px solid #ddd; padding:8px;'>Total Candles</td><td style='border:1px solid #ddd; padding:8px;'>{price_summary['candles']}</td></tr>",
            "</table>",
        ]

    if strategies_data:
        html_body += [
            "<h3>Strategy Comparison</h3>",
            "<table style='border-collapse: collapse; width: 100%;'>",
            "<tr><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Strategy</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Total PnL</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Trades</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Win Rate</th></tr>",
        ]
        for strategy_name, strategy_data in sorted(
            strategies_data.items(),
            key=lambda item: item[1]["metrics"]["total_pnl"],
            reverse=True,
        ):
            strategy_metrics = strategy_data["metrics"]
            highlight = "background:#e8f5e9;" if strategy_name == best_strategy_name else ""
            html_body.append(
                "<tr>"
                f"<td style='border:1px solid #ddd; padding:8px; {highlight}'>{strategy_name.upper()}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; {highlight}'>{format_currency(strategy_metrics['total_pnl'])}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; {highlight}'>{strategy_metrics['num_trades']}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; {highlight}'>{strategy_metrics['win_rate']:.1f}%</td>"
                "</tr>"
            )
        html_body.append("</table>")

    html_body += [
        "<h3>Top 5 Trades</h3>",
        "<table style='border-collapse: collapse; width: 100%;'>",
        "<tr><th style='text-align:left; border:1px solid #ddd; padding:8px;'>#</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Type</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Net PnL</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Entry</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Exit</th><th style='text-align:left; border:1px solid #ddd; padding:8px;'>Reason</th></tr>",
    ]
    for idx, trade in trades_df.nlargest(5, "Net_PnL").iterrows():
        html_body.append(
            "<tr>"
            f"<td style='border:1px solid #ddd; padding:8px;'>{idx + 1}</td>"
            f"<td style='border:1px solid #ddd; padding:8px;'>{trade.get('Type', 'N/A')}</td>"
            f"<td style='border:1px solid #ddd; padding:8px;'>{format_currency(trade.get('Net_PnL', 0))}</td>"
            f"<td style='border:1px solid #ddd; padding:8px;'>{format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}</td>"
            f"<td style='border:1px solid #ddd; padding:8px;'>{format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}</td>"
            f"<td style='border:1px solid #ddd; padding:8px;'>{trade.get('Exit_Reason', '')}</td>"
            "</tr>"
        )
    html_body += [
        "</table>",
        "<p>Detailed trade and price history data are attached for review.</p>",
        f"<p style='font-size:12px; color:#666;'>Report generated at {datetime.now().strftime('%H:%M:%S IST')}</p>",
        "</body></html>",
    ]

    return "\n".join(text_body), "\n".join(html_body), True, trades_df, price_df, source["trade_path"]


def attach_dataframe(msg, df, filename):
    if df is None:
        return
    part = MIMEBase("application", "octet-stream")
    part.set_payload(df.to_csv(index=False).encode())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(part)


def send_email():
    text_body, html_body, should_attach, trades_df, price_df, trade_path = build_report_summary()

    if not SENDER_EMAIL or not APP_PASSWORD or not RECEIVER_EMAIL:
        print("❌ Email settings are incomplete. Set SENDER_EMAIL, APP_PASSWORD and RECEIVER_EMAIL.")
        return False

    if html_body is None:
        print(f"❌ Could not build email body: {text_body}")
        return False

    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = SENDER_EMAIL
    msg["Bcc"] = ", ".join(RECEIVER_EMAIL)
    msg["Subject"] = f"Trading Report: {datetime.now().strftime('%d %b %Y')} | {datetime.now().strftime('%A')}"

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(text_body, "plain"))
    alternative.attach(MIMEText(html_body, "html"))
    msg.attach(alternative)

    if should_attach and trades_df is not None:
        attach_dataframe(msg, trades_df, os.path.basename(trade_path or "trades_summary.csv"))
    if should_attach and price_df is not None:
        attach_dataframe(msg, price_df, os.path.basename(PRICE_HISTORY_PATH))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print(f"✅ Email sent successfully to {len(RECEIVER_EMAIL)} recipient(s)")
        return True
    except Exception as exc:
        print(f"❌ Failed to send email: {exc}")
        return False


def send_performance_email():
    return send_email()


if __name__ == "__main__":
    send_email()
