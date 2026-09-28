"""
THE BRAIN (LLM) — Phase 6: pick your model, online or local (+ OpenAI later).

The rest of the app only calls chat_stream(model_id, messages, tools).
It doesn't know or care which company runs the model. This file hides the
differences between providers behind one small interface — an "adapter".

  • Online (OpenAI and Groq): both speak the OpenAI API — the request format
    OpenAI invented and most providers now copy. So ONE function talks to
    both: the `openai` library, pointed at a different URL for Groq.
    Adding OpenAI itself took one client and three lines in MODELS.
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

load_dotenv()  # reads OPENAI_API_KEY / GROQ_API_KEY from the .env file (created by setup.sh)

# Every model you can pick in the UI.
# "params" overrides request settings for one model. None removes a setting:
# GPT-5.5 is a reasoning model and rejects `temperature`.
# (The newest gpt-6 / gpt-5.6 models are left out on purpose: in this API they
# only allow tools with their reasoning switched off.)
MODELS = [
    {"id": "gpt-5.4-mini", "provider": "openai", "name": "GPT-5.4 mini", "note": "Fast, cheap and accurate · recommended"},
    {"id": "gpt-5.5", "provider": "openai", "name": "GPT-5.5", "note": "Strongest · thinks before answering · costs more",
     "params": {"temperature": None}},
    {"id": "gpt-4.1-mini", "provider": "openai", "name": "GPT-4.1 mini", "note": "Fastest to respond"},
    {"id": "qwen/qwen3.8-27b", "provider": "groq", "name": "Qwen 3.8 27B", "note": "Free tier · fast"},
    {"id": "openai/gpt-oss-120b", "provider": "groq", "name": "GPT-OSS 120B", "note": "Most careful · shows its reasoning · slower"},
    {"id": "openai/gpt-oss-20b", "provider": "groq", "name": "GPT-OSS 20B", "note": "Lighter version of GPT-OSS"},
    {"id": "qwen3:14b", "provider": "ollama", "name": "Qwen3 14B", "note": "Runs on your GPU · private · no limits"},
]
# OpenAI when there's a key for it, otherwise Groq's free tier
DEFAULT_MODEL = "gpt-5.4-mini" if os.environ.get("OPENAI_API_KEY") else "qwen/qwen3.8-27b"

PROVIDERS = {
    "openai": {"label": "Online · OpenAI", "url": None, "key": "OPENAI_API_KEY"},  # None = OpenAI's own URL
    "groq": {"label": "Online · Groq", "url": "https://api.groq.com/openai/v1", "key": "GROQ_API_KEY"},
    "ollama": {"label": "Local · Ollama", "url": "http://localhost:11434"},
}

THINK_LOCAL = False  # Qwen3 can "think" before answering. Off = much faster.
NUM_CTX = 16384      # context window for local models, in tokens

# Keys come from environment variables / .env — never write them in code.
# max_retries: when we hit a rate limit, wait and retry instead of failing.
online_clients = {
    name: OpenAI(base_url=p["url"], api_key=os.environ.get(p["key"], "missing"), max_retries=5)
    for name, p in PROVIDERS.items() if name != "ollama"
}
groq_client = online_clients["groq"]  # used by setup.sh to test the Groq key
ollama_client = ollama.Client(host=PROVIDERS["ollama"]["url"])


def get_model(model_id: str) -> dict:
    return next((m for m in MODELS if m["id"] == model_id), None)


def available_models() -> list[dict]:
    """MODELS, plus whether each one can be used right now (and why not)."""
    status = {}
    for name, client in online_clients.items():
        key = PROVIDERS[name]["key"]
        if not os.environ.get(key):
            status[name] = (set(), f"{key} is not set")
            continue
        try:
            status[name] = ({m.id for m in client.with_options(timeout=5).models.list().data}, "")
        except Exception:
            status[name] = (set(), f"Can't reach {PROVIDERS[name]['label'].split('· ')[1]} (or the key was rejected)")
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
    if model["provider"] == "ollama":
        yield from _stream_ollama(model_id, messages, tools)
    else:
        yield from _stream_openai_style(online_clients[model["provider"]], model, messages, tools)


def _stream_openai_style(client: OpenAI, model: dict, messages: list, tools: list | None):
    # Default settings, then the model's own overrides; None means "don't send it"
    params = {"temperature": 0.2, **model.get("params", {})}
    if tools:
        params["tools"] = tools
    params = {k: v for k, v in params.items() if v is not None}
    stream = client.chat.completions.create(model=model["id"], messages=messages, stream=True, **params)

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
