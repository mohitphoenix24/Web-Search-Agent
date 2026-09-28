"""
The AI side of the project: the model adapter, the tools, and the agent loop.

    llm.py     the brain    — talks to Groq (online) or Ollama (local)
    tools.py   the hands    — web_search(), read_page()
    agent.py   the loop     — think -> act -> observe, memory, citations

server.py (backend API) and db.py (saved chats) sit outside this package —
they're the plumbing around the agent, not the agent itself.
"""
