#!/bin/bash
# Install playwright browsers
python -m playwright install chromium

# Start the bot
python bot.py
