import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

model = genai.GenerativeModel('gemini-2.5-flash')
try:
    response = model.generate_content("Hello, who are you and what is your version?")
    print(response.text)
except Exception as e:
    print(f"Error: {e}")
