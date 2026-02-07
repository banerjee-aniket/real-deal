#!/bin/bash
# Start the Discord Bot in the background
python bot.py &

# Start the Web Dashboard using Gunicorn
# Bind to 0.0.0.0 and the PORT environment variable (default 8080)
PORT_TO_USE="${PORT:-8080}"
gunicorn web_dashboard:app --bind 0.0.0.0:$PORT_TO_USE
