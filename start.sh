#!/bin/bash
# Start the Discord Bot in the background
python bot.py &

# Start the Web Dashboard using Gunicorn
# Bind to 0.0.0.0 and the PORT environment variable (default 5000)
gunicorn web_dashboard:app --bind 0.0.0.0:${PORT:-5000}
