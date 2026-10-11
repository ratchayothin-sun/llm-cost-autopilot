from dotenv import load_dotenv

load_dotenv()

from app.providers.client import call_model
from app.router.cascade import TIERS
from eval.run_eval import load_items

IDS = ["r3", "r4", "k6", "k7", "t2", "j4"]
tier = next(t for t in TIERS if t["name"] == "small")
items = {i["id"]: i for i in load_items()}

same = 0
for item_id in IDS:
    msgs = [{"role": "user", "content": items[item_id]["prompt"]}]
    a = call_model(tier["model"], msgs, tier)["text"]
    b = call_model(tier["model"], msgs, tier)["text"]
    ok = a == b
    same += ok
    print(f"{item_id}: {'identical' if ok else 'DIFFERENT'}")
print(f"{same}/{len(IDS)} identical")