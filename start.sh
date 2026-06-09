#!/bin/bash
# Install playwright browsers
python -m playwright install chromium

# Start bot.py in the background
python bot.py &

# Start qs_standalone_bot.py in the foreground
python qs_standalone_bot.py

