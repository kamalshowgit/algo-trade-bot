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
    today = datetime.now().strftime("%d %b %Y")

    def get_color(val, reverse=False):
        if val > 0: return "#e74c3c" if reverse else "#2ecc71"
        if val < 0: return "#2ecc71" if reverse else "#e74c3c"
        return "#7f8c8d"

    if trades_df.empty:
        price_df, price_summary = read_price_history()
        
        # Text Body - NO TRADES
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
        text_body += ["", f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}"]

        generated_at = datetime.now().strftime("%H:%M:%S IST")
        html = f'''
        <html>
        <body style="margin:0; padding:0; background-color:#eef2f6; font-family:Arial, Helvetica, sans-serif; color:#18212f;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#eef2f6; padding:24px 10px;">
                <tr>
                    <td align="center">
                        <table width="760" cellpadding="0" cellspacing="0" role="presentation" style="width:100%; max-width:760px; background-color:#ffffff; border:1px solid #dbe3ee; border-radius:8px; overflow:hidden;">
                            <tr>
                                <td style="background-color:#0f172a; padding:24px 28px 20px 28px; color:#ffffff;">
                                    <div style="font-size:12px; color:#9fb2cc; text-transform:uppercase; font-weight:700;">Trading Bot Report</div>
                                    <div style="font-size:28px; line-height:34px; font-weight:800; margin-top:10px;">Session Dashboard</div>
                                    <div style="font-size:13px; line-height:20px; color:#c8d3e3; margin-top:4px;">{today} | {source['source_label']}</div>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding:22px 24px 10px 24px;">
                                    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#f8fafc; border:1px solid #dbe3ee; border-radius:8px;">
                                        <tr>
                                            <td style="padding:18px;">
                                                <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Session Status</div>
                                                <div style="font-size:24px; line-height:30px; color:#475569; font-weight:800;">NO TRADES</div>
                                                <div style="font-size:13px; color:#64748b; margin-top:5px;">The bot did not execute any trades during this session.</div>
                                            </td>
                                            <td align="right" style="padding:18px; color:#64748b; font-size:12px; line-height:18px;">
                                                Generated<br><strong style="color:#18212f;">{generated_at}</strong>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
        '''
        if price_summary:
            chg_color = get_color(price_summary['change'])
            html += f'''
                            <tr>
                                <td style="padding:8px 24px 24px 24px;">
                                    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border:1px solid #dbe3ee; border-radius:8px;">
                                        <tr>
                                            <td colspan="4" style="padding:16px 18px 4px 18px; font-size:15px; font-weight:800; color:#0f172a;">Price Action</td>
                                        </tr>
                                        <tr>
                                            <td style="padding:12px 18px; color:#64748b; font-size:12px;">Open<br><strong style="font-size:16px; color:#0f172a;">{format_currency(price_summary['opening'])}</strong></td>
                                            <td style="padding:12px 18px; color:#64748b; font-size:12px;">Close<br><strong style="font-size:16px; color:#0f172a;">{format_currency(price_summary['closing'])}</strong></td>
                                            <td style="padding:12px 18px; color:#64748b; font-size:12px;">High / Low<br><strong style="font-size:16px; color:#0f172a;">{format_currency(price_summary['high'])} / {format_currency(price_summary['low'])}</strong></td>
                                            <td style="padding:12px 18px; color:#64748b; font-size:12px;">Change<br><strong style="font-size:16px; color:{chg_color};">{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</strong></td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
            '''
        html += f'''
                            <tr>
                                <td style="background-color:#f8fafc; padding:16px 24px; color:#64748b; font-size:12px; text-align:center; border-top:1px solid #e5eaf1;">
                                    Price history CSV is attached when available. Report generated at {generated_at}.
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        '''
        return "\n".join(text_body), html, True, trades_df, price_df, source["trade_path"]

    # --- IF TRADES EXIST ---
    metrics = compute_trade_metrics(trades_df)
    price_df, price_summary = read_price_history()
    strategies_data = source["strategies_data"]
    best_strategy_name = source["best_strategy_name"]

    status = "PROFIT" if metrics["total_pnl"] > 0 else "BREAKEVEN" if metrics["total_pnl"] == 0 else "LOSS"
    status_bg = "#2ecc71" if status == "PROFIT" else "#f1c40f" if status == "BREAKEVEN" else "#e74c3c"
    pnl_color = get_color(metrics["total_pnl"])
    win_color = get_color(metrics["win_rate"] - 50) # >50 is green

    # Text Body
    text_body = [
        f"TRADING PERFORMANCE REPORT - {today}",
        "=" * 60,
        f"Status: {status}",
        f"Source: {source['source_label']}",
    ]
    if best_strategy_name: text_body.append(f"Strategy: {str(best_strategy_name).upper()}")
    text_body += [
        "",
        "PROFIT AND LOSS SUMMARY:",
        f"Total Net PnL: {format_currency(metrics['total_pnl'])}",
        f"Average PnL per Trade: {format_currency(metrics['avg_pnl'])}",
        f"Median PnL per Trade: {format_currency(metrics['median_pnl'])}",
        f"Trade Std Dev: {format_currency(metrics['std_pnl'])}",
        "Profit Factor: Infinite (No losses)" if metrics["profit_factor"] == float("inf") else f"Profit Factor: {metrics['profit_factor']:.2f}",
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
    if metrics["avg_points"] is not None: text_body.append(f"Average Points per Trade: {metrics['avg_points']:.2f}")

    if price_summary:
        text_body += [
            "", "PRICE ACTION SUMMARY:",
            f"Opening: {format_currency(price_summary['opening'])}",
            f"Closing: {format_currency(price_summary['closing'])}",
            f"Day High: {format_currency(price_summary['high'])}",
            f"Day Low: {format_currency(price_summary['low'])}",
            f"Day Change: {format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)",
            f"Total Candles: {price_summary['candles']}",
        ]

    if strategies_data:
        text_body += ["", "STRATEGY COMPARISON:"]
        for strategy_name, strategy_data in sorted(strategies_data.items(), key=lambda item: item[1]["metrics"]["total_pnl"], reverse=True):
            strategy_metrics = strategy_data["metrics"]
            prefix = "* " if strategy_name == best_strategy_name else "- "
            text_body.append(f"{prefix}{strategy_name.upper()}: {format_currency(strategy_metrics['total_pnl'])} | {strategy_metrics['num_trades']} trades | {strategy_metrics['win_rate']:.1f}% win rate")

    text_body += ["", "TOP 5 TRADES:"]
    for idx, trade in trades_df.nlargest(5, "Net_PnL").iterrows():
        text_body += [
            f"Trade #{idx + 1}: {trade.get('Type', 'N/A')} | PnL: {format_currency(trade.get('Net_PnL', 0))}",
            f"  Entry: {format_currency(trade.get('Entry_Price', 0))} @ {trade.get('Entry_Time', '')}",
            f"  Exit: {format_currency(trade.get('Exit_Price', 0))} @ {trade.get('Exit_Time', '')}",
            f"  Reason: {trade.get('Exit_Reason', '')}",
        ]
    text_body += ["", "Detailed trade and price history data are attached for review.", f"Report generated at {datetime.now().strftime('%H:%M:%S IST')}"]

    # HTML Body - Email dashboard
    strat_text = f" | Strategy: {str(best_strategy_name).upper()}" if best_strategy_name else ""
    pf_text = "Infinite" if metrics['profit_factor'] == float('inf') else f"{metrics['profit_factor']:.2f}"
    status_color = "#16a34a" if status == "PROFIT" else "#ca8a04" if status == "BREAKEVEN" else "#dc2626"
    status_soft = "#ecfdf3" if status == "PROFIT" else "#fffbeb" if status == "BREAKEVEN" else "#fef2f2"
    status_border = "#bbf7d0" if status == "PROFIT" else "#fde68a" if status == "BREAKEVEN" else "#fecaca"
    win_bar = max(0, min(100, metrics["win_rate"]))
    loss_bar = 100 - win_bar
    avg_points_text = f"{metrics['avg_points']:.2f}" if metrics["avg_points"] is not None else "N/A"
    generated_at = datetime.now().strftime("%H:%M:%S IST")

    html = f'''
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f6; font-family:Arial, Helvetica, sans-serif; color:#18212f;">
        <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#eef2f6; padding:24px 10px;">
            <tr>
                <td align="center">
                    <table width="760" cellpadding="0" cellspacing="0" role="presentation" style="width:100%; max-width:760px; background-color:#ffffff; border:1px solid #dbe3ee; border-radius:8px; overflow:hidden;">
                        <tr>
                            <td style="background-color:#0f172a; padding:24px 28px 20px 28px; color:#ffffff;">
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                    <tr>
                                        <td style="font-size:12px; color:#9fb2cc; text-transform:uppercase; font-weight:700;">Trading Bot Report</td>
                                        <td align="right" style="font-size:12px; color:#c8d3e3;">{today}</td>
                                    </tr>
                                    <tr>
                                        <td colspan="2" style="padding-top:10px;">
                                            <div style="font-size:28px; line-height:34px; font-weight:800;">Session Dashboard</div>
                                            <div style="font-size:13px; line-height:20px; color:#c8d3e3; margin-top:4px;">{source['source_label']}{strat_text}</div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:22px 24px 8px 24px;">
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:{status_soft}; border:1px solid {status_border}; border-radius:8px;">
                                    <tr>
                                        <td style="padding:15px 18px;">
                                            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Session Status</div>
                                            <div style="font-size:22px; line-height:28px; color:{status_color}; font-weight:800;">{status}</div>
                                        </td>
                                        <td align="right" style="padding:15px 18px; color:#64748b; font-size:12px; line-height:18px;">
                                            Generated<br><strong style="color:#18212f;">{generated_at}</strong>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:14px 24px 8px 24px;">
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                    <tr>
                                        <td width="49%" style="background-color:#111827; border-radius:8px; padding:18px; color:#ffffff;">
                                            <div style="font-size:11px; color:#9ca3af; text-transform:uppercase; font-weight:700;">Total Net PnL</div>
                                            <div style="font-size:30px; line-height:38px; font-weight:800; color:{pnl_color};">{format_currency(metrics['total_pnl'])}</div>
                                            <div style="font-size:12px; color:#cbd5e1;">Avg {format_currency(metrics['avg_pnl'])} per trade</div>
                                        </td>
                                        <td width="2%"></td>
                                        <td width="49%" style="background-color:#f8fafc; border:1px solid #dbe3ee; border-radius:8px; padding:18px;">
                                            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Win Rate</div>
                                            <div style="font-size:30px; line-height:38px; font-weight:800; color:{win_color};">{metrics['win_rate']:.1f}%</div>
                                            <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="height:9px; margin-top:8px; background-color:#fee2e2; border-radius:8px; overflow:hidden;">
                                                <tr>
                                                    <td width="{win_bar:.0f}%" style="background-color:#16a34a; height:9px;"></td>
                                                    <td width="{loss_bar:.0f}%" style="background-color:#dc2626; height:9px;"></td>
                                                </tr>
                                            </table>
                                            <div style="font-size:12px; color:#64748b; margin-top:8px;">{metrics['winning_trades']} wins, {metrics['losing_trades']} losses, {metrics['breakeven_trades']} flat</div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:8px 24px 16px 24px;">
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                    <tr>
                                        <td width="24%" style="background-color:#ffffff; border:1px solid #dbe3ee; border-radius:8px; padding:14px;">
                                            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Trades</div>
                                            <div style="font-size:22px; font-weight:800; color:#0f172a;">{metrics['num_trades']}</div>
                                        </td>
                                        <td width="1%"></td>
                                        <td width="24%" style="background-color:#ffffff; border:1px solid #dbe3ee; border-radius:8px; padding:14px;">
                                            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Profit Factor</div>
                                            <div style="font-size:22px; font-weight:800; color:#0f172a;">{pf_text}</div>
                                        </td>
                                        <td width="1%"></td>
                                        <td width="24%" style="background-color:#ffffff; border:1px solid #dbe3ee; border-radius:8px; padding:14px;">
                                            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Drawdown</div>
                                            <div style="font-size:22px; font-weight:800; color:#dc2626;">{metrics['max_drawdown_pct']:.2f}%</div>
                                        </td>
                                        <td width="1%"></td>
                                        <td width="24%" style="background-color:#ffffff; border:1px solid #dbe3ee; border-radius:8px; padding:14px;">
                                            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700;">Avg Points</div>
                                            <div style="font-size:22px; font-weight:800; color:#0f172a;">{avg_points_text}</div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:0 24px 20px 24px;">
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                    <tr>
                                        <td width="49%" valign="top" style="border:1px solid #dbe3ee; border-radius:8px; padding:18px;">
                                            <div style="font-size:15px; font-weight:800; color:#0f172a; margin-bottom:12px;">Performance</div>
                                            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px;">Expectancy</td><td align="right" style="padding:8px 0; font-weight:700; color:{get_color(metrics['expectancy'])};">{format_currency(metrics['expectancy'])}</td></tr>
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px; border-top:1px solid #e5eaf1;">Median PnL</td><td align="right" style="padding:8px 0; border-top:1px solid #e5eaf1; font-weight:700; color:{get_color(metrics['median_pnl'])};">{format_currency(metrics['median_pnl'])}</td></tr>
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px; border-top:1px solid #e5eaf1;">Best Trade</td><td align="right" style="padding:8px 0; border-top:1px solid #e5eaf1; font-weight:700; color:#16a34a;">{format_currency(metrics['max_profit'])}</td></tr>
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px; border-top:1px solid #e5eaf1;">Worst Trade</td><td align="right" style="padding:8px 0; border-top:1px solid #e5eaf1; font-weight:700; color:#dc2626;">{format_currency(metrics['max_loss'])}</td></tr>
                                            </table>
                                        </td>
                                        <td width="2%"></td>
                                        <td width="49%" valign="top" style="border:1px solid #dbe3ee; border-radius:8px; padding:18px;">
                                            <div style="font-size:15px; font-weight:800; color:#0f172a; margin-bottom:12px;">Trade Mix</div>
                                            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px;">Long Trades</td><td align="right" style="padding:8px 0; font-weight:700;">{metrics['long_trades']}</td></tr>
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px; border-top:1px solid #e5eaf1;">Short Trades</td><td align="right" style="padding:8px 0; border-top:1px solid #e5eaf1; font-weight:700;">{metrics['short_trades']}</td></tr>
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px; border-top:1px solid #e5eaf1;">Avg Duration</td><td align="right" style="padding:8px 0; border-top:1px solid #e5eaf1; font-weight:700;">{metrics['avg_duration_min']:.1f} min</td></tr>
                                                <tr><td style="padding:8px 0; color:#64748b; font-size:13px; border-top:1px solid #e5eaf1;">Median Duration</td><td align="right" style="padding:8px 0; border-top:1px solid #e5eaf1; font-weight:700;">{metrics['median_duration_min']:.1f} min</td></tr>
                                            </table>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
    '''

    if price_summary:
        chg_color = get_color(price_summary['change'])
        html += f'''
                        <tr>
                            <td style="padding:0 24px 20px 24px;">
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border:1px solid #dbe3ee; border-radius:8px;">
                                    <tr>
                                        <td colspan="4" style="padding:16px 18px 4px 18px; font-size:15px; font-weight:800; color:#0f172a;">Price Action</td>
                                    </tr>
                                    <tr>
                                        <td style="padding:12px 18px; color:#64748b; font-size:12px;">Open<br><strong style="font-size:16px; color:#0f172a;">{format_currency(price_summary['opening'])}</strong></td>
                                        <td style="padding:12px 18px; color:#64748b; font-size:12px;">Close<br><strong style="font-size:16px; color:#0f172a;">{format_currency(price_summary['closing'])}</strong></td>
                                        <td style="padding:12px 18px; color:#64748b; font-size:12px;">High / Low<br><strong style="font-size:16px; color:#0f172a;">{format_currency(price_summary['high'])} / {format_currency(price_summary['low'])}</strong></td>
                                        <td style="padding:12px 18px; color:#64748b; font-size:12px;">Change<br><strong style="font-size:16px; color:{chg_color};">{format_currency(price_summary['change'])} ({price_summary['change_pct']:+.2f}%)</strong></td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
        '''

    if strategies_data:
        html += '''
                        <tr>
                            <td style="padding:0 24px 20px 24px;">
                                <div style="font-size:15px; font-weight:800; color:#0f172a; margin-bottom:10px;">Strategy Comparison</div>
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:separate; border-spacing:0; border:1px solid #dbe3ee; border-radius:8px; overflow:hidden;">
                                    <tr style="background-color:#f8fafc;">
                                        <th align="left" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Strategy</th>
                                        <th align="right" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Total PnL</th>
                                        <th align="right" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Trades</th>
                                        <th align="right" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Win Rate</th>
                                    </tr>
        '''
        for strategy_name, strategy_data in sorted(strategies_data.items(), key=lambda item: item[1]["metrics"]["total_pnl"], reverse=True):
            s_metrics = strategy_data["metrics"]
            bg = "#ecfdf3" if strategy_name == best_strategy_name else "#ffffff"
            badge = "Best" if strategy_name == best_strategy_name else ""
            html += f'''
                                    <tr style="background-color:{bg};">
                                        <td style="padding:12px; border-top:1px solid #e5eaf1; font-weight:700; color:#0f172a;">{strategy_name.upper()} <span style="font-size:11px; color:#16a34a;">{badge}</span></td>
                                        <td align="right" style="padding:12px; border-top:1px solid #e5eaf1; font-weight:700; color:{get_color(s_metrics['total_pnl'])};">{format_currency(s_metrics['total_pnl'])}</td>
                                        <td align="right" style="padding:12px; border-top:1px solid #e5eaf1;">{s_metrics['num_trades']}</td>
                                        <td align="right" style="padding:12px; border-top:1px solid #e5eaf1; font-weight:700; color:{get_color(s_metrics['win_rate'] - 50)};">{s_metrics['win_rate']:.1f}%</td>
                                    </tr>
            '''
        html += '''
                                </table>
                            </td>
                        </tr>
        '''

    html += '''
                        <tr>
                            <td style="padding:0 24px 24px 24px;">
                                <div style="font-size:15px; font-weight:800; color:#0f172a; margin-bottom:10px;">Top Trades</div>
                                <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:separate; border-spacing:0; border:1px solid #dbe3ee; border-radius:8px; overflow:hidden;">
                                    <tr style="background-color:#f8fafc;">
                                        <th align="left" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Type</th>
                                        <th align="right" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">PnL</th>
                                        <th align="left" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Entry</th>
                                        <th align="left" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Exit</th>
                                        <th align="left" style="padding:12px; color:#64748b; font-size:12px; text-transform:uppercase;">Reason</th>
                                    </tr>
    '''
    for _, trade in trades_df.nlargest(5, "Net_PnL").iterrows():
        pnl = trade.get('Net_PnL', 0)
        trade_type = str(trade.get('Type', 'N/A')).upper()
        type_color = "#2563eb" if trade_type == "LONG" else "#7c3aed" if trade_type == "SHORT" else "#64748b"
        html += f'''
                                    <tr>
                                        <td style="padding:12px; border-top:1px solid #e5eaf1;"><span style="background-color:#eef2ff; color:{type_color}; border-radius:12px; padding:4px 9px; font-size:12px; font-weight:700;">{trade_type}</span></td>
                                        <td align="right" style="padding:12px; border-top:1px solid #e5eaf1; font-weight:800; color:{get_color(pnl)};">{format_currency(pnl)}</td>
                                        <td style="padding:12px; border-top:1px solid #e5eaf1; font-size:12px; color:#64748b;"><strong style="color:#0f172a;">{format_currency(trade.get('Entry_Price', 0))}</strong><br>{trade.get('Entry_Time', '')}</td>
                                        <td style="padding:12px; border-top:1px solid #e5eaf1; font-size:12px; color:#64748b;"><strong style="color:#0f172a;">{format_currency(trade.get('Exit_Price', 0))}</strong><br>{trade.get('Exit_Time', '')}</td>
                                        <td style="padding:12px; border-top:1px solid #e5eaf1; font-size:12px; color:#475569;">{trade.get('Exit_Reason', '')}</td>
                                    </tr>
        '''
    html += f'''
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="background-color:#f8fafc; padding:16px 24px; color:#64748b; font-size:12px; text-align:center; border-top:1px solid #e5eaf1;">
                                Detailed trade and price history CSV files are attached. Report generated at {generated_at}.
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    '''
    
    return "\n".join(text_body), html, True, trades_df, price_df, source["trade_path"]

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
