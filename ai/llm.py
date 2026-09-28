"""
THE BRAIN (LLM) — Phase 6: pick your model, online or local.

The rest of the app only calls chat_stream(model_id, messages, tools).
It doesn't know or care which company runs the model. This file hides the
differences between providers behind one small interface — an "adapter".

  • Online (Groq): speaks the OpenAI-compatible API — the request format
    OpenAI invented and most providers now copy. We use the `openai` library
    and just point it at Groq's URL.
  • Local (Ollama): we use Ollama's own library, because only that one lets
    us raise the context window (Ollama's default of 4,096 tokens is too
    small for full web pages).

Both adapters yield the same three kinds of events:
    ("token", text)       a piece of the reply, as it's generated
    ("thinking", text)    a piece of the model's reasoning (if it shows any)
    ("tool_calls", list)  at the end, if the model wants to use tools:
                          [{"id": ..., "name": ..., "arguments": "<json>"}]

The conversation (`messages`) is always kept in the OpenAI format.
"""

import json
import os

import ollama
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads GROQ_API_KEY from the .env file (created by setup.sh)

# Every model you can pick in the UI.
# (Groq's free tier allows 8,000 tokens per minute per model.)
MODELS = [
    {"id": "qwen/qwen3.8-27b", "provider": "groq", "name": "Qwen 3.8 27B", "note": "Fast and accurate · recommended"},
    {"id": "openai/gpt-oss-120b", "provider": "groq", "name": "GPT-OSS 120B", "note": "Most careful · shows its reasoning · slower"},
    {"id": "openai/gpt-oss-20b", "provider": "groq", "name": "GPT-OSS 20B", "note": "Lighter version of GPT-OSS"},
    {"id": "qwen3:14b", "provider": "ollama", "name": "Qwen3 14B", "note": "Runs on your GPU · private · no limits"},
]
DEFAULT_MODEL = "qwen/qwen3.8-27b"

PROVIDERS = {
    "groq": {"label": "Online · Groq", "url": "https://api.groq.com/openai/v1"},
    "ollama": {"label": "Local · Ollama", "url": "http://localhost:11434"},
}

THINK_LOCAL = False  # Qwen3 can "think" before answering. Off = much faster.
NUM_CTX = 16384      # context window for local models, in tokens

# Groq: the key comes from the GROQ_API_KEY environment variable (never write it in code).
# max_retries: the free tier has a tokens-per-minute limit; wait and retry when we hit it.
groq_client = OpenAI(base_url=PROVIDERS["groq"]["url"], api_key=os.environ.get("GROQ_API_KEY", "missing"), max_retries=5)
ollama_client = ollama.Client(host=PROVIDERS["ollama"]["url"])


def get_model(model_id: str) -> dict:
    return next((m for m in MODELS if m["id"] == model_id), None)


def available_models() -> list[dict]:
    """MODELS, plus whether each one can be used right now (and why not)."""
    status = {}
    if not os.environ.get("GROQ_API_KEY"):
        status["groq"] = (set(), "GROQ_API_KEY is not set")
    else:
        try:
            status["groq"] = ({m.id for m in groq_client.with_options(timeout=5).models.list().data}, "")
        except Exception:
            status["groq"] = (set(), "Can't reach Groq")
    try:
        status["ollama"] = ({m.model for m in ollama_client.list().models}, "")
    except Exception:
        status["ollama"] = (set(), "Ollama isn't running")

    result = []
    for m in MODELS:
        ids, problem = status[m["provider"]]
        if not problem and m["id"] not in ids:
            problem = "Not installed" if m["provider"] == "ollama" else "Not available"
        result.append({**m, "provider_label": PROVIDERS[m["provider"]]["label"], "available": not problem, "problem": problem})
    return result


def chat_stream(model_id: str, messages: list, tools: list | None = None):
    """One streamed LLM call to any model. Yields ("token" | "thinking" | "tool_calls", data)."""
    model = get_model(model_id)
    if model["provider"] == "groq":
        yield from _stream_openai_style(groq_client, model_id, messages, tools)
    else:
        yield from _stream_ollama(model_id, messages, tools)


def _stream_openai_style(client: OpenAI, model_id: str, messages: list, tools: list | None):
    extra = {"tools": tools} if tools else {}
    stream = client.chat.completions.create(model=model_id, messages=messages, stream=True, temperature=0.2, **extra)

    calls = {}  # tool calls arrive in fragments: the name first, then the JSON arguments bit by bit
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "reasoning", None):  # Groq's gpt-oss models share their reasoning
            yield "thinking", delta.reasoning
        if delta.content:
            yield "token", delta.content
        for tc in delta.tool_calls or []:
            call = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            call["id"] = tc.id or call["id"]
            if tc.function:
                call["name"] = tc.function.name or call["name"]
                call["arguments"] += tc.function.arguments or ""
    if calls:
        yield "tool_calls", list(calls.values())


def _stream_ollama(model_id: str, messages: list, tools: list | None):
    calls = []
    for chunk in ollama_client.chat(
        model=model_id,
        messages=_to_ollama_format(messages),
        tools=tools,
        think=THINK_LOCAL,
        stream=True,
        options={"temperature": 0.2, "num_ctx": NUM_CTX},
    ):
        part = chunk.message
        if part.thinking:
            yield "thinking", part.thinking
        if part.content:
            yield "token", part.content
        for tc in part.tool_calls or []:
            calls.append({"id": f"call_{len(calls) + 1}", "name": tc.function.name,
                          "arguments": json.dumps(tc.function.arguments or {})})
    if calls:
        yield "tool_calls", calls


def _to_ollama_format(messages: list) -> list:
    """OpenAI-format conversation -> Ollama format (arguments as dicts, tools answered by name)."""
    names = {}  # tool_call_id -> tool name
    converted = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                names[tc["id"]] = tc["function"]["name"]
                calls.append({"function": {"name": tc["function"]["name"], "arguments": json.loads(tc["function"]["arguments"] or "{}")}})
            converted.append({"role": "assistant", "content": m["content"], "tool_calls": calls})
        elif m["role"] == "tool":
            converted.append({"role": "tool", "content": m["content"], "tool_name": names.get(m["tool_call_id"], "")})
        else:
            converted.append(m)
    return converted


# Test without any UI:  python llm.py   (every model says hi, streamed)
if __name__ == "__main__":
    for m in available_models():
        print(f"{m['name']:14} ", end="")
        if not m["available"]:
            print(f"(unavailable: {m['problem']})")
            continue
        for kind, data in chat_stream(m["id"], [{"role": "user", "content": "Say hi in 5 words."}]):
            if kind == "token":
                print(data, end="", flush=True)
        print()
