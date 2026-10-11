from dotenv import load_dotenv

load_dotenv()

from app.providers.client import call_model
from app.router.cascade import TIERS

tier = next(t for t in TIERS if t["name"] == "large")
try:
    r = call_model(tier["model"], [{"role": "user", "content": "hi"}], tier)
    print("OK:", r["text"][:100])
except Exception as e:
    print(str(e)[:3000])