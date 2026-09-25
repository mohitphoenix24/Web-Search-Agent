# Web Search Agent

A small AI agent that searches the web, reads pages and answers your questions with sources. You can watch every step it takes while it works.

I built this while learning agentic AI, one phase at a time. There is no agent framework here (no LangChain, no CrewAI). The whole agent loop is plain Python that you can read in one sitting, so you can see exactly what an "agent" really is.

![Web Search Agent answering a question, with the live agent trace on the right](docs/screenshot.png)

## What it can do

- **Decides by itself** whether it needs to search at all. Ask "what is 17 × 23" and it just answers. Ask about yesterday's news and it goes to the web.
- **Two tools:** `web_search` finds pages (DuckDuckGo, no key needed) and `read_page` opens a page and reads the full text when the search snippets are not enough.
- **Answers with sources.** Every claim gets a number like [1], and clicking it takes you to that source.
- **Live agent trace.** You see every search query it writes, every page it reads and every mistake it fixes, while it is happening.
- **Streams the answer** word by word, like ChatGPT.
- **Remembers the chat.** Follow-ups like "and who came second?" work. Chats are saved in SQLite, so they are still there after a refresh or restart.
- **Pick your model** from the top bar: fast online models on Groq (free API key), or a local model through Ollama if you already have it running.

<img src="docs/model-picker.png" alt="Model picker with online Groq models and a local Ollama model" width="420">

## How it works

An agent is basically three things: an LLM (the brain), some tools (the hands) and a loop.

```
          ┌───────────────────────────────────────────────────┐
          │  THINK   the LLM reads the whole conversation     │
          │    │                                              │
          │    ├── wants a tool? ─> ACT: our code runs it     │
          │    │                    OBSERVE: result is added  │
          │    │                    to the conversation ──────┘
          │    │
          │    └── no tool call? ─> that's the final answer, stop
```

This is called the **ReAct** loop (Reason + Act). One important thing that confused me in the beginning: **the LLM never runs any code**. It only *asks* for a tool, by giving a tool name and some JSON arguments. Our Python code runs the tool and puts the result back into the conversation. The LLM only knows about the tools from a short description we send with every request.

The full flow of one question:

```
React UI  ──question──>  FastAPI server  ──>  agent loop  ──>  LLM (Groq / Ollama)
    ^                        │                    │
    │                        │                    └──>  tools: web_search, read_page
    └──── live events ───────┘
          (one JSON per line: thought, tool_call, tool_result, token, answer...)
```

The server streams every step to the browser as it happens (NDJSON), that's how the trace and the answer update live. When a turn finishes, its events are saved in SQLite. Opening an old chat just replays those events, so you get back the full trace and not only the answer.

## Tech stack

| Part | What I used |
|---|---|
| Agent loop | Plain Python, no framework ([agent.py](agent.py)) |
| LLMs | Groq (OpenAI-compatible API) and Ollama, behind one small adapter ([llm.py](llm.py)) |
| Tools | `ddgs` for DuckDuckGo search, `trafilatura` for pulling the main text out of a page |
| Backend | FastAPI + Uvicorn, SQLite for saved chats |
| Frontend | React 19 + Vite, plain CSS (light and dark mode), `react-markdown` |

## Getting started

You will need:

- **Python 3.10+**
- **Node.js 18+**
- A free **Groq API key**: sign up at [console.groq.com](https://console.groq.com/keys) and create one. It takes a minute.

Then:

```bash
git clone https://github.com/mohitphoenix24/Web-Search-Agent.git
cd Web-Search-Agent
./setup.sh
./start.sh
```

Open **http://localhost:5180** and ask something.

`setup.sh` checks your Python and Node versions, installs everything (Python packages go into a local `.venv`), asks you to paste your Groq key and then tests the key with Groq. The key is saved in a `.env` file, which is git-ignored, so it never gets pushed by mistake. If you prefer, you can also copy `.env.example` to `.env` and put your key there yourself.

`start.sh` starts the backend on port 8000 and the UI on port 5180. Press `Ctrl+C` to stop both.

> **On Windows?** The scripts are bash, so please run them inside WSL.

## Things to try

- `Who won the latest Formula 1 race?` and then `And who came second?` (memory)
- `What is 17 × 23?` (it should answer without any tools)
- `Read https://docs.python.org/3/whatsnew/3.14.html and list the 3 biggest features` (read_page)
- Ask the same question with two different models and compare the traces

## Project structure

```
Web-Search-Agent/
├── agent.py          # the ReAct agent loop, tools menu, memory, citations
├── llm.py            # model list + one adapter for Groq and one for Ollama
├── tools.py          # web_search() and read_page()
├── db.py             # SQLite storage for saved chats
├── server.py         # FastAPI: streams agent events, chat endpoints
├── setup.sh          # one-time setup
├── start.sh          # runs backend + frontend
├── requirements.txt
└── frontend/
    └── src/
        ├── App.jsx           # chat state, turns events into UI steps
        ├── api.js            # reads the NDJSON stream
        └── components/       # Trace, Answer, Sources, Sidebar, ModelPicker
```

The main Python files also run on their own from the terminal, which is handy while learning:

```bash
.venv/bin/python tools.py                          # try the two tools
.venv/bin/python llm.py                            # every model says hi
.venv/bin/python agent.py                          # a 2-question chat in the terminal
.venv/bin/python agent.py openai/gpt-oss-120b      # same, with another model
```

## How I built it (the phases)

I did not write this in one go. Each phase added one idea on top of the last one, and the comments in the code still say which phase added what.

| Phase | What I added | What I learned |
|---|---|---|
| 1 | A search tool and a basic UI | A tool is just a normal function that returns clean data |
| 2 | LLM reads the search results and answers with sources | RAG: giving the LLM fresh information inside the prompt |
| 3 | The LLM decides itself when and what to search | Tool calling and the ReAct loop, this is where it became an agent |
| 4 | Chat memory + `read_page` tool | Memory is just sending the old conversation again. Adding a tool = a function + a description |
| 5 | Streaming answers + saved chats in SQLite | Tokens, streaming, and moving memory to the server |
| 6 | Model picker (online and local) | Most providers speak the same OpenAI-style API, so one adapter can hide the differences |

## Things to know

- **Groq's free tier allows 8,000 tokens per minute per model.** A normal question is fine, but a question that needs many searches can hit the limit. The app waits and retries by itself, so the answer just comes slower. You can also switch to another model from the menu, because each model has its own limit.
- **Search can fail sometimes.** DuckDuckGo occasionally refuses a request, so `web_search` retries up to 3 times.
- **Some websites block bots** (formula1.com, reuters.com for example). When a page can't be read, the agent sees the error and tries another one.
- **Answers can still be wrong.** Smaller models especially can misread a page. That's why every answer shows its sources, so please check them for anything important.
- The **local model** (Qwen3 14B) only shows up as available if you already have [Ollama](https://ollama.com) running with `qwen3:14b` pulled. It's optional, the online models work without it.

## Running things separately (while developing)

```bash
# backend, restarts when you change a .py file
.venv/bin/uvicorn server:app --reload --port 8000

# frontend, in another terminal
cd frontend && npm run dev
```

## What's next

The next thing I want to add is **evals**: a small set of test questions, run automatically against each model, so I can actually measure if a prompt change makes the agent better or worse instead of just guessing.

---

Made by Mohit ([@mohitphoenix24](https://github.com/mohitphoenix24)) while learning agentic AI. If this helped you understand agents a little better, do give it a ⭐. Suggestions and PRs are most welcome.
