FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries
RUN python -m playwright install chromium

# Copy the rest of the application code
COPY . .

# Set environment variable to ensure output isn't buffered
ENV PYTHONUNBUFFERED=1

# Command to run the bot
CMD ["python", "qs_standalone_bot.py"]
