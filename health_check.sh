#!/bin/bash

# Pre-Market Health Check
# Run this before 9:15 AM IST to ensure bot is ready

echo "🏥 Bot Health Check - Pre-Market"
echo "=================================="
echo ""

ERRORS=0
WARNINGS=0

# Color codes
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

check_pass() { echo -e "${GREEN}✅ $1${NC}"; }
check_fail() { echo -e "${RED}❌ $1${NC}"; ((ERRORS++)); }
check_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; ((WARNINGS++)); }

# 1. Check Python
if command -v python3 &> /dev/null; then
    VERSION=$(python3 --version | awk '{print $2}')
    check_pass "Python $VERSION found"
else
    check_fail "Python3 not found"
fi

# 2. Check Virtual Environment
if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    check_pass "Virtual environment exists"
else
    check_fail "Virtual environment not found"
fi

# 3. Check Core Python Files
for file in main.py engine.py send_email_report.py; do
    if [ -f "$file" ]; then
        if python3 -m py_compile "$file" 2>/dev/null; then
            check_pass "$file (syntax valid)"
        else
            check_fail "$file (syntax error)"
        fi
    else
        check_fail "$file not found"
    fi
done

# 4. Check .env file
if [ -f ".env" ]; then
    check_pass ".env file exists"
    
    # Check required env vars
    if grep -q "SENDER_EMAIL" .env; then
        check_pass "SENDER_EMAIL configured"
    else
        check_warn "SENDER_EMAIL not configured"
    fi
    
    if grep -q "RECEIVER_EMAIL" .env; then
        check_pass "RECEIVER_EMAIL configured"
    else
        check_warn "RECEIVER_EMAIL not configured"
    fi
    
    if grep -qE "APP_PASSWORD|EMAIL_PASSWORD|GMAIL_APP_PASSWORD" .env; then
        check_pass "APP_PASSWORD configured"
    else
        check_fail "APP_PASSWORD not configured (email won't work)"
    fi
else
    check_fail ".env file not found"
fi

# 5. Check Dependencies
echo ""
echo "Checking dependencies..."

source venv/bin/activate 2>/dev/null

DEPS=("pandas" "numpy" "yfinance" "python-dotenv")
ALL_DEPS_OK=true

for dep in "${DEPS[@]}"; do
    if python3 -c "import ${dep//-/_}" 2>/dev/null; then
        check_pass "$dep installed"
    else
        check_warn "$dep not installed"
        ALL_DEPS_OK=false
    fi
done

# 6. Check PM2
echo ""
if command -v pm2 &> /dev/null; then
    check_pass "PM2 installed"
    
    if pm2 list | grep -q "HFT_Bot"; then
        STATUS=$(pm2 status | grep "HFT_Bot" | awk '{print $10}')
        if [ "$STATUS" = "stopped" ]; then
            check_pass "HFT_Bot registered with PM2 (currently stopped - normal)"
        elif [ "$STATUS" = "online" ]; then
            check_warn "HFT_Bot is running (should be stopped outside market hours)"
        else
            check_pass "HFT_Bot registered with PM2"
        fi
    else
        check_fail "HFT_Bot not registered with PM2"
    fi
else
    check_fail "PM2 not installed"
fi

# 7. Check Market Hours
echo ""
HOUR=$(TZ='Asia/Kolkata' date +%H)
MINUTE=$(TZ='Asia/Kolkata' date +%M)
DAY_OF_WEEK=$(date +%u)

echo "Current Time (IST): $(TZ='Asia/Kolkata' date '+%H:%M:%S')"

if [ $DAY_OF_WEEK -ge 1 ] && [ $DAY_OF_WEEK -le 5 ]; then
    if [ $HOUR -ge 9 ] && [ $HOUR -le 15 ]; then
        if [ $HOUR -eq 9 ] && [ $MINUTE -lt 15 ]; then
            check_warn "Market opening soon (9:15 AM IST) - bot will start automatically"
        elif [ $HOUR -eq 15 ] && [ $MINUTE -ge 15 ]; then
            check_warn "Market closed - bot will stop automatically at 3:20 PM"
        else
            check_pass "Market is OPEN - bot should be running"
        fi
    else
        check_pass "Outside market hours - bot will start at 9:15 AM IST"
    fi
else
    check_pass "Weekend - bot will start Monday at 9:15 AM IST"
fi

# 8. Check Disk Space
echo ""
DISK_USAGE=$(df . | awk 'NR==2 {print $5}' | cut -d'%' -f1)
if [ "$DISK_USAGE" -lt 80 ]; then
    check_pass "Disk space OK ($DISK_USAGE% used)"
else
    check_warn "Low disk space ($DISK_USAGE% used)"
fi

# 9. Check Logs Directory
if [ -d "logs" ]; then
    check_pass "Logs directory exists"
    LOG_SIZE=$(du -sh logs 2>/dev/null | cut -f1)
    echo "   Current size: $LOG_SIZE"
else
    check_warn "Logs directory not found (will be created at startup)"
fi

# 10. Check Recent Results
echo ""
if ls strategy_*.csv &>/dev/null; then
    LATEST=$(ls -t strategy_*.csv | head -1)
    TIMESTAMP=$(stat -f%m "$LATEST" 2>/dev/null || stat -c%Y "$LATEST" 2>/dev/null)
    check_pass "Strategy results found (latest: $(basename $LATEST))"
else
    check_pass "No results yet (normal for new bot)"
fi

# Summary
echo ""
echo "=================================="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! Bot is ready.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  $WARNINGS warnings (bot should still work)${NC}"
    exit 0
else
    echo -e "${RED}❌ $ERRORS errors found (bot may not work)${NC}"
    exit 1
fi
