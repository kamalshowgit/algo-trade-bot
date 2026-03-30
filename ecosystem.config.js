module.exports = {
  apps : [{
    name: "HFT_Bot",
    script: "./main.py",
    interpreter: "./venv/bin/python3",
    // Starts the bot at 9:00 AM IST, Monday to Friday
    cron_restart: "0 9 * * 1-5",
    // Prevents the "Infinite Restart" loop after 3:25 PM
    autorestart: true,
    exp_backoff_restart_delay: 100, 
    // If the bot exits gracefully (Code 0), don't restart until the cron says so
    stop_exit_codes: [0], 
    watch: false,
    env: {
      NODE_ENV: "production",
      TZ: "Asia/Kolkata" // Double-checking the timezone for PM2 internal logs
    }
  }]
}