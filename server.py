"""
Backend API — connects the Python agent to the React UI.

Run with:
    uvicorn server:app --reload --port 8000

The agent yields events one by one. We *stream* them to the browser as
NDJSON (one JSON object per line), so the UI can show each step live.

Chats are saved in SQLite (db.py). The server owns the memory: it loads the
earlier turns of the chat from the database for every question.
"""

import json
import time

import ollama
import openai
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import db
from ai.agent import MAX_HISTORY_TURNS, MAX_STEPS, is_bad_tool_call, run_agent
from ai.llm import DEFAULT_MODEL, available_models, get_model

app = FastAPI(title="Web Search Agent")
db.init()


class AskRequest(BaseModel):
    question: str
    chat_id: int | None = None  # None = start a new chat
    model: str = DEFAULT_MODEL  # which LLM answers this question


@app.get("/api/info")
def info():
    return {
        "models": available_models(),
        "default_model": DEFAULT_MODEL,
        "max_steps": MAX_STEPS,
        "memory_turns": MAX_HISTORY_TURNS,
    }


@app.get("/api/chats")
def list_chats():
    return db.list_chats()


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int):
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    return chat


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int):
    db.delete_chat(chat_id)
    return {"ok": True}


def friendly_error(e: Exception) -> str:
    """Turn provider errors into messages a person can act on."""
    if isinstance(e, openai.RateLimitError):
        return "Groq's free-tier limit was reached (tokens per minute). Wait a minute, or pick another model."
    if isinstance(e, openai.AuthenticationError):
        return "Groq rejected the API key. Check GROQ_API_KEY in your .env file."
    if isinstance(e, openai.APIConnectionError):
        return "Can't reach Groq. Check your internet connection."
    if is_bad_tool_call(e):
        return "The model kept writing tool calls it couldn't finish. Try asking again, or pick another model."
    if isinstance(e, ConnectionError):
        return "Can't reach Ollama. Is it running? (ollama serve)"
    if isinstance(e, ollama.ResponseError):
        return f"Ollama error: {e.error}"
    return str(e)


@app.post("/api/ask")
def ask(req: AskRequest):
    if get_model(req.model) is None:
        raise HTTPException(400, f"Unknown model: {req.model}")
    chat_id = req.chat_id if req.chat_id and db.chat_exists(req.chat_id) else None
    history = db.history(chat_id, MAX_HISTORY_TURNS) if chat_id else []  # MEMORY

    def stream():
        started = time.time()
        saved_events, answer = [], ""
        try:
            for event in run_agent(req.question, history, req.model):
                if event["type"] != "token":  # tokens are only for the live view
                    saved_events.append(event)
                if event["type"] == "answer":
                    answer = event["text"]
                if event["type"] == "done":
                    # Save the finished turn BEFORE telling the UI we're done
                    saved = db.save_turn(chat_id, req.question, answer, saved_events, time.time() - started)
                    yield json.dumps(event) + "\n"
                    yield json.dumps({"type": "saved", **saved}) + "\n"
                    continue
                yield json.dumps(event) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": friendly_error(e)}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
