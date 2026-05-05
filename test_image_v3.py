import google.generativeai as genai
import os
from dotenv import load_dotenv
import PIL.Image

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

model = genai.GenerativeModel('gemini-3-flash-preview')
try:
    img = PIL.Image.open('scratch_test_thai.png')
    response = model.generate_content(["Describe this image in Thai", img])
    print(response.text)
except Exception as e:
    print(f"Error: {e}")
