#!/bin/bash
# Start the Discord Bot in the background
python bot.py &

# Debug: Print the PORT environment variable
echo "DEBUG: Raw PORT environment variable is: '$PORT'"

# Determine the port to use
# 1. If PORT is unset or empty, default to 8080.
# 2. If PORT is set but contains non-numeric characters (like literal strings), default to 8080.
if [[ -z "$PORT" ]]; then
    echo "DEBUG: PORT is empty. Defaulting to 8080."
    PORT_TO_USE=8080
elif ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
    echo "DEBUG: PORT '$PORT' is not a valid number. Defaulting to 8080."
    PORT_TO_USE=8080
else
    echo "DEBUG: Using provided PORT: $PORT"
    PORT_TO_USE="$PORT"
fi

# Start the Web Dashboard using Gunicorn
echo "DEBUG: Starting Gunicorn on port $PORT_TO_USE"
gunicorn web_dashboard:app --bind 0.0.0.0:$PORT_TO_USE
