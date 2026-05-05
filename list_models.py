import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("No API key found")
    exit(1)

client = genai.Client(api_key=api_key)
try:
    for m in client.models.list():
        print(f"{m.name}")
except Exception as e:
    print(f"Error: {e}")
