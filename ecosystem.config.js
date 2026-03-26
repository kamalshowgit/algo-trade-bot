module.exports = {
  apps : [{
    name: "HFT_Bot",
    script: "./main.py",
    interpreter: "./venv/bin/python3",
    // Starts the bot at 9:00 AM IST, Monday to Friday
    cron_restart: "0 9 * * 1-5",
    // Stops the bot from constantly restarting once it exits at 3:35 PM
    autorestart: true, 
    watch: false,
  }]
}
