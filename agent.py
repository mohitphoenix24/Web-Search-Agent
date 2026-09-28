"""
THE AGENT LOOP  (Phase 3: ReAct loop · 4: memory + a second tool · 5: streaming · 6: any model)

The loop (from Phase 3):

    ┌──────────────────────────────────────────────────────────┐
    │  THINK   LLM reads the conversation so far               │
    │    │                                                     │
    │    ├── wants a tool? ──> ACT: we run the tool            │
    │    │                     OBSERVE: add the result to the  │
    │    │                     conversation, then loop again ──┘
    │    │
    │    └── no tool call? ──> it's the FINAL ANSWER. Stop.
    └──────────────────────────────────────────────────────────

The LLM never runs code itself. It only *asks* for a tool call (a name +
arguments). OUR code runs the tool and sends back the result.

New in Phase 4:
  1. MEMORY. An LLM is stateless — every call starts from zero. "Memory" just
     means we send the earlier conversation again with each new question.
     The server loads the earlier turns (Phase 5: from the database, db.py)
     and build_messages() adds them.
     We keep only the last few turns, because the context window is limited.
  2. A SECOND TOOL: read_page(url). Search snippets are short; now the agent
     can open a page and read it in full when it needs details.
     Adding a tool = write a Python function + describe it in TOOLS.

New in Phase 5:
  3. STREAMING. Every LLM call is streamed: we forward each piece of text
     ("token" events) the moment the model writes it, so the answer appears
     word by word. If the step ends in a tool call instead, the UI knows the
     streamed text wasn't the final answer.

New in Phase 6:
  4. ANY MODEL. run_agent() takes a model id. The loop barely changes:
     llm.py makes every model look the same (see its docstring).
"""

import json
import re
from datetime import date

from openai import APIError

from llm import DEFAULT_MODEL, chat_stream
from tools import read_page, web_search

MAX_STEPS = 8          # safety limit so the agent can't loop forever
MAX_HISTORY_TURNS = 5  # how many earlier Q&A turns we send as memory

# The tool "menu" we show the LLM. It never sees our Python code — only these
# descriptions. A clear description = the LLM uses the tool well.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns numbered results with title, URL and a short snippet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A short, specific search query (like you'd type into Google).",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_page",
            "description": "Open a web page and read its main text. Use it when search snippets "
                           "are not detailed enough, or when the user gives you a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL of the page to read."}
                },
                "required": ["url"],
            },
        },
    },
]


def system_prompt() -> str:
    return f"""You are a web research agent. Today's date is {date.today()}.

You have two tools:
- web_search(query): find pages. You get short snippets.
- read_page(url): read one page in full. Use it when snippets aren't enough.

Decide for yourself:
- Recent, specific or factual info you're unsure about -> search.
- Simple things (math, greetings, well-known facts) -> answer directly, no tools.
- Write short, specific search queries, not the user's full sentence.
- If the snippets don't contain the answer (e.g. they only link to a results
  page), use read_page on the most promising result. Don't give up early.
- If a tool fails, try a different query or another page.
- As soon as you have enough to answer, stop and answer. Usually 1-3 tool
  calls are enough; don't keep searching to double-check.
- Never tell the user to look it up themselves, and never blame their internet.

This is a chat. Earlier questions and answers are included above.
For follow-ups like "and who came second?", work out what they refer to and
write a complete search query (e.g. "2026 Spanish Grand Prix results").
You only remember earlier ANSWERS, not the pages behind them: if a follow-up
asks for a fact that isn't in an earlier answer, use the tools again.

When you answer:
- Cite sources with their number in square brackets, like [1] or [3].
- Only cite numbers from tool results in THIS turn.
- Be clear and concise. Use markdown (short paragraphs, bullet points)."""


def strip_citations(text: str) -> str:
    # Old answers cite old sources. New sources restart at [1], so we remove
    # old [n] markers from memory to avoid confusing the model.
    return re.sub(r"\s?\[\d+(?:\s*,\s*\d+)*\]", "", text)


def build_messages(question: str, history: list[dict]) -> list[dict]:
    """System prompt + MEMORY (earlier turns) + the new question."""
    messages = [{"role": "system", "content": system_prompt()}]
    for turn in history:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": strip_citations(turn["answer"])})
    messages.append({"role": "user", "content": question})
    return messages


class SourceList:
    """Every page the agent has seen in this turn. Each URL keeps one [number]."""

    def __init__(self):
        self.items = []
        self.ids = {}

    def add(self, title: str, url: str, snippet: str, read: bool = False) -> int:
        if url not in self.ids:
            self.ids[url] = len(self.items) + 1
            self.items.append({"id": self.ids[url], "title": title, "url": url, "snippet": snippet, "read": False})
        item = self.items[self.ids[url] - 1]
        if read:
            item["read"] = True
        return item["id"]


# ---- Tool runners: run the real tool, return (data for the UI, text for the LLM) ----

def run_web_search(args: dict, sources: SourceList) -> tuple[dict, str]:
    query = args["query"]
    try:
        # web_search picks the engine (Tavily if a key is set, else DuckDuckGo)
        # and tells us which one it actually used, so the UI can show it.
        engine, results = web_search(query)
    except Exception as e:  # tools can fail — the agent should see that too
        return {"query": query, "results": [], "error": str(e)[:200]}, f"Search failed: {e}"
    if not results:
        return {"query": query, "results": [], "engine": engine}, "No results found. Try a different query."

    numbered = [{**r, "id": sources.add(r["title"], r["url"], r["snippet"])} for r in results]
    text = "\n\n".join(f"[{r['id']}] {r['title']}\nURL: {r['url']}\n{r['snippet']}" for r in numbered)
    return {"query": query, "results": numbered, "engine": engine}, text


def run_read_page(args: dict, sources: SourceList) -> tuple[dict, str]:
    url = args["url"]
    try:
        page = read_page(url)
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)[:200]}, f"Could not read {url}: {e}. Try another page."

    sid = sources.add(page["title"], url, page["text"][:240], read=True)
    ui = {"url": url, "ok": True, "id": sid, "title": page["title"], "chars": len(page["text"])}
    return ui, f"[{sid}] {page['title']}\nURL: {url}\n\n{page['text']}"


# The registry: tool name -> the code that runs it.
TOOL_RUNNERS = {"web_search": run_web_search, "read_page": run_read_page}
REQUIRED_ARGS = {t["function"]["name"]: t["function"]["parameters"]["required"] for t in TOOLS}

INVALID_TOOL_CALL_HINT = (
    "Your last tool call was invalid. Use exactly web_search({\"query\": \"...\"}) "
    "or read_page({\"url\": \"...\"}). Try again, or write your final answer."
)


def is_bad_tool_call(error: Exception) -> bool:
    """Did the model write a tool call the provider couldn't parse?

    Groq validates tool calls and rejects broken ones. The error looks
    different depending on how we asked:
      - normal request:  BadRequestError "... tool_use_failed ..."
      - streamed request: APIError "Failed to call a function..." (mid-stream)
    Both mean the same thing: the model made a mistake and should try again.
    """
    message = str(error).lower()
    return "tool_use_failed" in message or "failed to call a function" in message


def think(model_id: str, messages: list, step: int, tools: list | None):
    """One streamed LLM call. Yields a "token" event for every piece of text,
    and returns (full_text, tool_calls) when the model is done."""
    content, thinking, tool_calls = "", "", []
    for kind, data in chat_stream(model_id, messages, tools):
        if kind == "token":
            content += data
            yield {"type": "token", "step": step, "text": data}
        elif kind == "thinking":
            thinking += data
        elif kind == "tool_calls":
            tool_calls = data

    # Some models occasionally write their reasoning into the answer, ending it
    # with a stray </think> tag. Everything before that tag is a thought.
    if "</think>" in content:
        leaked, content = content.rsplit("</think>", 1)
        thinking += leaked.replace("<think>", "")
    if thinking.strip():
        yield {"type": "thought", "step": step, "text": thinking.strip()}
    return content.strip(), tool_calls


def run_agent(question: str, history: list[dict] | None = None, model_id: str = DEFAULT_MODEL):
    """Run the agent loop. This is a *generator*: it `yield`s an event at every
    step so the UI can show the agent's work live.

    Event types: memory, token, thought, tool_call, tool_result, retry, answer, done
    """
    def done(steps):
        return {"type": "done", "steps": steps, "searches": counts["web_search"], "reads": counts["read_page"], "model": model_id}

    history = (history or [])[-MAX_HISTORY_TURNS:]
    messages = build_messages(question, history)
    yield {"type": "memory", "turns": len(history)}

    sources = SourceList()
    counts = {"web_search": 0, "read_page": 0}

    for step in range(1, MAX_STEPS + 1):
        # ---- THINK: ask the LLM what to do next (streamed) ----
        # `yield from` passes think()'s token events straight on to the UI,
        # then gives us think()'s return value when the LLM is finished.
        try:
            content, tool_calls = yield from think(model_id, messages, step, tools=TOOLS)
        except APIError as e:
            # Don't crash on a broken tool call: tell the LLM its mistake and
            # let it try again. Anything else (rate limit, no internet, bad
            # key) is a real problem, so we pass it on to the server.
            if not is_bad_tool_call(e):
                raise
            yield {"type": "retry", "step": step, "message": "The LLM wrote a tool call it couldn't finish. Asked it to try again."}
            messages.append({"role": "user", "content": INVALID_TOOL_CALL_HINT})
            continue

        # ---- No tool call = the LLM is done. That's the final answer. ----
        if not tool_calls:
            yield {"type": "answer", "text": content, "sources": sources.items}
            yield done(step)
            return

        if content:  # text written before a tool call was a thought, not the answer
            yield {"type": "thought", "step": step, "text": content}
        # record the LLM's tool request in the conversation (OpenAI format)
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            # ---- ACT: run the tool the LLM asked for ----
            name = tc["name"]
            try:
                args = json.loads(tc["arguments"] or "{}")  # arguments arrive as a JSON string
            except json.JSONDecodeError:
                args = {}
            valid = name in TOOL_RUNNERS and all(args.get(a) for a in REQUIRED_ARGS[name])

            if not valid:
                # LLMs sometimes make bad tool calls. Don't crash: tell it the mistake.
                yield {"type": "retry", "step": step, "message": f"Invalid tool call: {name}({args}). Told the LLM to fix it."}
                result_text = "Error: invalid tool call. Use web_search(query) or read_page(url)."
            else:
                counts[name] += 1
                yield {"type": "tool_call", "step": step, "tool": name, "args": args}
                ui_data, result_text = TOOL_RUNNERS[name](args, sources)
                yield {"type": "tool_result", "step": step, "tool": name, **ui_data}

            # ---- OBSERVE: put the result back into the conversation ----
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_text})

    # Out of steps: offer NO tools this time, so the LLM has to answer.
    messages.append({"role": "user", "content": "Stop using tools now. Write your final answer from what you already found."})
    content, _ = yield from think(model_id, messages, MAX_STEPS + 1, tools=None)
    yield {"type": "answer", "text": content, "sources": sources.items}
    yield done(MAX_STEPS + 1)


# Test without any UI (a 2-turn chat, to show memory):
#   python agent.py                    (default online model)
#   python agent.py qwen3:14b          (any model id from llm.MODELS)
if __name__ == "__main__":
    import sys

    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

    def show(question, history):
        print(f"\n🧑 {question}")
        for event in run_agent(question, history, model):
            t = event["type"]
            if t == "token":
                continue  # (the answer is printed in full below)
            if t == "memory":
                print(f"🧠 MEMORY: {event['turns']} earlier turn(s) sent")
            elif t == "thought":
                print(f"💭 THINK: {event['text'][:150]}")
            elif t == "tool_call":
                print(f"🔧 ACT: {event['tool']}({event['args']})")
            elif t == "tool_result":
                got = f"{len(event['results'])} results" if event["tool"] == "web_search" else \
                      (f"{event['chars']} chars" if event["ok"] else f"failed: {event['error']}")
                print(f"📄 OBSERVE: {got}")
            elif t == "retry":
                print(f"⚠️  RETRY: {event['message']}")
            elif t == "answer":
                print(f"🤖 {event['text']}")
                answer_text = event["text"]
            elif t == "done":
                print(f"   (steps: {event['steps']}, searches: {event['searches']}, pages read: {event['reads']})")
        return answer_text

    print(f"Model: {model}")
    q1 = "Who won the latest Formula 1 race?"
    a1 = show(q1, [])
    show("And who came second?", [{"question": q1, "answer": a1}])
