from telegram.ext import ApplicationBuilder
try:
    app = ApplicationBuilder().token("dummy").build()
    print(f"Job queue: {app.job_queue}")
except Exception as e:
    print(f"Error: {e}")
