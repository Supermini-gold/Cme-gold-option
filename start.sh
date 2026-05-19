#!/bin/bash
# Install playwright browsers
python -m playwright install chromium

# Start the bot
python qs_standalone_bot.py
