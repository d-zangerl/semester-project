import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
api_key=os.getenv("OPENAI_API_KEY")
base_url=os.getenv("OPENAI_BASE_URL")
client = OpenAI(base_url=base_url, api_key=api_key)
resp = client.chat.completions.create(
    model="Qwen/Qwen3.6-35B-A3B",
    messages=[{"role": "user", "content": "What is life? Answer in 10 keywords"}]
)
print(resp.choices[0].message.content)