#!/bin/bash

# Trading Bot Deployment & Startup Script
# Usage: bash deploy_and_start.sh

set -e

echo "🚀 Trading Bot Deployment & Startup"
echo "===================================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    OS="unknown"
fi

echo -e "${YELLOW}Detected OS: $OS${NC}"

# ===== STEP 1: Check Python & Virtual Environment =====
echo ""
echo "1️⃣  Checking Python environment..."

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✅ $PYTHON_VERSION${NC}"

if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✅ Virtual environment created${NC}"
else
    echo -e "${GREEN}✅ Virtual environment exists${NC}"
fi

# Activate venv
source venv/bin/activate
echo -e "${GREEN}✅ Virtual environment activated${NC}"

# ===== STEP 2: Check & Install Dependencies =====
echo ""
echo "2️⃣  Checking Python dependencies..."

REQUIRED_PACKAGES=("pandas" "numpy" "yfinance" "python-dotenv" "SmartApi" "pyotp")
MISSING_PACKAGES=()

for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if ! python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        MISSING_PACKAGES+=("$pkg")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo -e "${YELLOW}Installing missing packages: ${MISSING_PACKAGES[*]}${NC}"
    pip install --upgrade pip > /dev/null
    pip install "${MISSING_PACKAGES[@]}"
    echo -e "${GREEN}✅ Packages installed${NC}"
else
    echo -e "${GREEN}✅ All dependencies installed${NC}"
fi

# ===== STEP 3: Verify Core Files =====
echo ""
echo "3️⃣  Verifying core files..."

REQUIRED_FILES=("main.py" "engine.py" "send_email_report.py" ".env" "ecosystem.config.js" "requirements.txt")

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✅ $file${NC}"
    else
        echo -e "${RED}❌ $file not found${NC}"
        exit 1
    fi
done

# ===== STEP 4: Validate Python Syntax =====
echo ""
echo "4️⃣  Validating Python syntax..."

for pyfile in main.py engine.py send_email_report.py; do
    if python3 -m py_compile "$pyfile" 2>/dev/null; then
        echo -e "${GREEN}✅ $pyfile${NC}"
    else
        echo -e "${RED}❌ $pyfile has syntax errors${NC}"
        python3 -m py_compile "$pyfile"
        exit 1
    fi
done

# ===== STEP 5: Check PM2 =====
echo ""
echo "5️⃣  Checking PM2..."

if command -v pm2 &> /dev/null; then
    echo -e "${GREEN}✅ PM2 installed${NC}"
    PM2_VERSION=$(pm2 --version)
    echo "   Version: $PM2_VERSION"
else
    echo -e "${YELLOW}⚠️  PM2 not found. Installing...${NC}"
    npm install -g pm2
    pm2 install pm2-auto-pull
    echo -e "${GREEN}✅ PM2 installed${NC}"
fi

# ===== STEP 6: Create Logs Directory =====
echo ""
echo "6️⃣  Setting up logs..."

if [ ! -d "logs" ]; then
    mkdir -p logs
    echo -e "${GREEN}✅ Created logs directory${NC}"
else
    echo -e "${GREEN}✅ Logs directory exists${NC}"
fi

# ===== STEP 7: Deploy with PM2 =====
echo ""
echo "7️⃣  Deploying with PM2..."

# Stop existing process if running
if pm2 list | grep -q "HFT_Bot"; then
    echo -e "${YELLOW}Stopping existing HFT_Bot process...${NC}"
    pm2 delete HFT_Bot 2>/dev/null || true
fi

# Start new process
pm2 start ecosystem.config.js
echo -e "${GREEN}✅ Process started with PM2${NC}"

# Save PM2 config to survive reboots
pm2 save
pm2 startup

# ===== STEP 8: Display Status =====
echo ""
echo "8️⃣  Process Status:"
echo "========================================"
pm2 status

echo ""
echo "========================================"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo ""
echo "📊 Next Steps:"
echo "   • Check logs: pm2 logs HFT_Bot"
echo "   • Stop bot: pm2 stop HFT_Bot"
echo "   • Restart bot: pm2 restart HFT_Bot"
echo "   • View config: pm2 describe HFT_Bot"
echo ""
echo "🕐 Bot will start automatically at 9:15 AM IST (market open)"
echo "🕐 Bot will stop automatically at 3:20 PM IST (after market close)"
echo ""
echo "Happy Trading! 📈"
