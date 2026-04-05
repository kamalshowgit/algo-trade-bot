# AWS Deployment Guide

## Prerequisites
- AWS Account with appropriate IAM permissions
- Python 3.11+
- Git for repository management

---

## Option 1: Deploy on AWS Lambda (Recommended for Cost)

### Step 1: Prepare Code for Lambda
```bash
# Create deployment package
mkdir lambda-package
cp engine.py send_email_report.py system_check.py lambda-package/
cp requirements.txt lambda-package/

# Install dependencies locally
cd lambda-package
pip install -r requirements.txt -t .

# Create zip file for upload
zip -r lambda-function.zip .
```

### Step 2: Upload to Lambda
1. Go to AWS Lambda Console
2. Create new function: `algo-trade-bot`
3. Runtime: Python 3.11
4. Upload `lambda-function.zip`
5. Handler: `main.lambda_handler`

### Step 3: Set Environment Variables
In Lambda Console → Configuration → Environment Variables:
```
ANGEL_API_KEY = <value>
ANGEL_CLIENT_ID = <value>
ANGEL_PASSWORD = <value>
ANGEL_TOTP_SECRET = <value>
EMAIL_SENDER = <value>
EMAIL_PASSWORD = <value>
RECIPIENT_EMAIL = <value>
```

### Step 4: Schedule with EventBridge
1. Go to EventBridge
2. Create rule: `algo-trade-daily`
3. Schedule: `cron(0 5 ? * MON-FRI *)` (9:15 AM IST = 3:45 AM UTC)
4. Target: Lambda function `algo-trade-bot`

---

## Option 2: Deploy on AWS EC2 (Recommended for Control)

### Step 1: Launch EC2 Instance
- AMI: Ubuntu 22.04 LTS
- Instance Type: t3.micro (eligible for free tier)
- Storage: 20 GB EBS

### Step 2: Connect & Setup SSH
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

### Step 3: Install Dependencies
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python & pip
sudo apt install python3.11 python3-pip git -y

# Install PM2 for process management
sudo npm install -g pm2
```

### Step 4: Clone Repository
```bash
cd /home/ubuntu
git clone https://github.com/your-repo/algo-trade-bot.git
cd algo-trade-bot

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 5: Set Up Environment Variables
```bash
# Copy .env template
cp .env.example .env

# Edit with your credentials
nano .env
# Add:
# ANGEL_API_KEY=xxx
# ANGEL_CLIENT_ID=xxx
# ... etc
```

### Step 6: Test Before Deployment
```bash
# Run system check
python system_check.py

# Run backtest
python main.py
```

### Step 7: Schedule with Cron
```bash
# Edit crontab
crontab -e

# Add daily execution (9:15 AM IST = 3:45 AM UTC)
45 3 * * 1-5 cd /home/ubuntu/algo-trade-bot && source venv/bin/activate && python main.py >> logs/trading-$(date +\%Y-\%m-\%d).log 2>&1
```

### Step 8: Set Up PM2 for Auto-Restart
```bash
# Create PM2 ecosystem config
pm2 start ecosystem.config.js

# Make PM2 startup on reboot
pm2 startup
pm2 save
```

---

## Step 9: Security Best Practices

### Store Secrets in AWS Secrets Manager
```bash
# Create secret
aws secretsmanager create-secret \
  --name algo-trade-secrets \
  --secret-string '{
    "ANGEL_API_KEY":"xxx",
    "ANGEL_CLIENT_ID":"xxx",
    "ANGEL_PASSWORD":"xxx",
    "ANGEL_TOTP_SECRET":"xxx",
    "EMAIL_SENDER":"xxx",
    "EMAIL_PASSWORD":"xxx",
    "RECIPIENT_EMAIL":"xxx"
  }'
```

### Modify main.py to Read from Secrets Manager
```python
import boto3
import json

def get_secrets():
    client = boto3.client('secretsmanager', region_name='ap-south-1')
    response = client.get_secret_value(SecretId='algo-trade-secrets')
    return json.loads(response['SecretString'])

secrets = get_secrets()
os.environ.update(secrets)
```

### IAM Role for EC2/Lambda
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:algo-trade-secrets*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

---

## Monitoring & Logging

### CloudWatch Setup
1. Go to CloudWatch
2. Create Log Group: `/aws/lambda/algo-trade-bot` (Lambda) or `/aws/ec2/algo-trade` (EC2)
3. Set up alarms for failures

### Log File Locations

**Lambda:**
- Logs in CloudWatch Logs

**EC2:**
- `/home/ubuntu/algo-trade-bot/logs/trading-YYYY-MM-DD.log`

---

## Testing Checklist

```bash
# 1. Verify all dependencies installed
pip list | grep -E "yfinance|pandas|numpy|smartapi"

# 2. Test data fetching
python -c "from engine import *; print('✅ Engine imports OK')"

# 3. Test Angel One connection (if applicable)
python test_connection.py

# 4. Run system check
python system_check.py

# 5. Do backtest run
python main.py

# 6. Check CSV output
head -5 angel_backtest_results.csv
```

---

## Cost Estimation (AWS)

| Service | Free Tier | Estimated Cost |
|---------|-----------|-----------------|
| Lambda | 1M requests/month | $0.20-1.00/month |
| EC2 (t3.micro) | 750 hrs/month | $0 (free tier) or $10-15/month |
| CloudWatch | 5GB logs | $0-5/month |
| Secrets Manager | - | $0.40/secret |
| Data Transfer | 1GB out/month | $0-1/month |
| **Total** | | **$0-25/month** |

---

## Troubleshooting

### Lambda Timeout
- Increase timeout to 60 seconds
- Reduce data window from 60 days to 30 days

### Connection Errors
- Check security group allows outbound HTTPS
- Verify Angel One credentials in Secrets Manager
- Test with: `python test_connection.py`

### Missing Data
- yfinance sometimes fails; add retry logic
- Use `--no-ssl-verify` flag if SSL errors occur

### Logs Not Appearing
- Ensure IAM role has CloudWatch permissions
- Check that print statements are in logs

---

## Rollback Plan

```bash
# If something breaks, rollback to known good state
git log --oneline
git revert <commit-id>

# Or deploy previous version
git checkout <branch-name>
```

---

## Next Steps After Deployment

1. ✅ Deploy code to AWS
2. ✅ Set up scheduling
3. ⏳ Monitor first week of trades
4. ⏳ Validate profitability metrics
5. ⏳ Enable live trading (if positive backtest results)
6. ⏳ Implement circuit breaker for risk management
