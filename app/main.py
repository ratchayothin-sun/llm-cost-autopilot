from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from pydantic import BaseModel
from app.router.cascade import run_cascade

app = FastAPI(title="LLM Cost Autopilot")

class ChatRequest(BaseModel):
    messages: list[dict]
    task_type: str | None = None   # เผื่อใช้ใน Phase 2-3

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    return run_cascade(req.messages, req.task_type)

@app.get("/health")
def health():
    return {"status": "ok"}