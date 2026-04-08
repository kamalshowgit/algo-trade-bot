#!/bin/bash

# Quick troubleshooting script for the trading bot
# Run: bash troubleshoot.sh

echo "🔧 Trading Bot Troubleshooting"
echo "=============================="
echo ""

# Check market hours
echo "📅 Current Time (IST):"
TZ='Asia/Kolkata' date
echo ""

# Check if it's market hours
HOUR=$(TZ='Asia/Kolkata' date +%H)
MINUTE=$(TZ='Asia/Kolkata' date +%M)
DAY_OF_WEEK=$(date +%u)

if [ $DAY_OF_WEEK -ge 1 ] && [ $DAY_OF_WEEK -le 5 ]; then
    if [ $HOUR -ge 9 ] && [ $HOUR -le 15 ]; then
        if [ $HOUR -eq 9 ] && [ $MINUTE -lt 15 ]; then
            echo "⏰ Market opening soon (9:15 AM IST)"
        elif [ $HOUR -eq 15 ] && [ $MINUTE -ge 15 ]; then
            echo "⏰ Market closed (after 3:15 PM IST)"
        else
            echo "✅ Market is OPEN"
        fi
    else
        echo "⏰ Market is CLOSED (outside 9:15 AM - 3:15 PM IST)"
    fi
else
    echo "⏰ Weekend - Market is CLOSED"
fi

echo ""
echo "========================================"
echo "1️⃣  Python & Dependencies"
echo "========================================"

# Check Python
python3 --version
echo "Python location: $(which python3)"
echo ""

# Check venv
if [ -d "venv" ]; then
    echo "✅ Virtual environment exists"
    source venv/bin/activate
    python3 -c "import sys; print(f'✅ Using: {sys.executable}')"
else
    echo "❌ Virtual environment not found"
fi

echo ""
echo "Installed packages:"
python3 -c "
import pandas as pd
import numpy as np
import yfinance as yf
print('✅ pandas', pd.__version__)
print('✅ numpy', np.__version__)
print('✅ yfinance', yf.__version__)
" 2>/dev/null || echo "❌ Some packages missing"

echo ""
echo "========================================"
echo "2️⃣  PM2 Status"
echo "========================================"

if command -v pm2 &> /dev/null; then
    pm2 status
    echo ""
    echo "Recent logs (last 20 lines):"
    pm2 logs HFT_Bot --lines 20 --nostream 2>/dev/null || echo "No logs yet"
else
    echo "❌ PM2 not installed"
fi

echo ""
echo "========================================"
echo "3️⃣  File Check"
echo "========================================"

FILES=("main.py" "engine.py" "send_email_report.py" ".env" "ecosystem.config.js")
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        SIZE=$(wc -c < "$file")
        echo "✅ $file ($SIZE bytes)"
    else
        echo "❌ $file - NOT FOUND"
    fi
done

echo ""
echo "========================================"
echo "4️⃣  Configuration Check"
echo "========================================"

echo "Environment variables:"
if [ -f ".env" ]; then
    echo "✅ .env file exists"
    if grep -q "SENDER_EMAIL" .env; then
        echo "   ✅ Email configured"
    else
        echo "   ❌ Email not configured"
    fi
    if grep -q "PAPER_MODE" .env; then
        PAPER_MODE=$(grep "PAPER_MODE" .env | cut -d'=' -f2)
        echo "   Paper Mode: $PAPER_MODE"
    fi
    if grep -q "LIVE_MODE" .env; then
        LIVE_MODE=$(grep "LIVE_MODE" .env | cut -d'=' -f2)
        echo "   Live Mode: $LIVE_MODE"
    fi
else
    echo "❌ .env file not found"
fi

echo ""
echo "========================================"
echo "5️⃣  Manual Test"
echo "========================================"

echo "Testing market data fetch..."
python3 << 'PYTHON_TEST'
import sys
try:
    import yfinance as yf
    print("Fetching NIFTY data (last 1 hour)...")
    df = yf.download("^NSEI", period="1d", interval="5m", progress=False)
    if df.empty:
        print("❌ No data received (market may be closed)")
    else:
        print(f"✅ Received {len(df)} candles")
        print(f"   Latest price: ₹{df['Close'].iloc[-1]:.2f}")
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
PYTHON_TEST

echo ""
echo "========================================"
echo "Done! Check the above output for issues."
echo "========================================"
