from google import genai
import os
from dotenv import load_dotenv
import PIL.Image

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

try:
    img = PIL.Image.open('scratch_test_thai.png')
    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=["Describe this image in Thai", img]
    )
    print(response.text)
except Exception as e:
    print(f"Error: {e}")
