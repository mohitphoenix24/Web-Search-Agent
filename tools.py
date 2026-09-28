"""
TOOLS — the agent's "hands".

An "agent" = an LLM (the brain) + tools (the hands) + a loop (decide -> act -> observe).

A tool is just a normal Python function that does something in the real world
and returns plain data. The LLM decides WHEN to call it (see agent.py).

Phase 1: web_search  — find pages (short snippets only)
Phase 4: read_page   — open one page and read its full text
Phase 7: web_search can use two different search engines

SEARCH ENGINES
--------------
web_search() can run on either engine, and both return the exact same shape,
so nothing else in the app changes when you switch:

  • Tavily      — built for AI agents. Better snippets, needs a free API key.
  • DuckDuckGo  — free, no key at all. The fallback.

Whichever engine is used, a result is always {"title", "url", "snippet"}.
This is the same trick llm.py uses for models: hide the differences behind
one small function, and the rest of the code never needs to know.
"""

import os
import re
import time

import httpx
import trafilatura
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from dotenv import load_dotenv
from trafilatura.downloads import fetch_response
from trafilatura.settings import use_config

load_dotenv()  # reads TAVILY_API_KEY / GROQ_API_KEY from the .env file

MAX_PAGE_CHARS = 8000  # ~2,000 tokens. Pages can be 100k+ chars — too big for the LLM's context.

DOWNLOAD_CONFIG = use_config()
DOWNLOAD_CONFIG.set("DEFAULT", "DOWNLOAD_TIMEOUT", "10")  # give up on slow sites after 10s

TAVILY_URL = "https://api.tavily.com/search"


def tavily_key() -> str | None:
    """The Tavily key, or None if there isn't one. Read every time, so adding
    it to .env and restarting is enough — no code change needed."""
    return os.environ.get("TAVILY_API_KEY") or None


def default_engine() -> str:
    """Tavily when a key is available, DuckDuckGo otherwise."""
    return "tavily" if tavily_key() else "duckduckgo"


def web_search(query: str, max_results: int = 5, engine: str | None = None) -> tuple[str, list[dict]]:
    """Search the web. Returns (engine_used, results).

    Each result is {"title": ..., "url": ..., "snippet": ...}.

    Tavily is used when a key is set. If it fails for any reason (bad key, no
    credits left, network trouble) we quietly fall back to DuckDuckGo, so the
    agent always gets something instead of an error.
    """
    engine = engine or default_engine()

    if engine == "tavily":
        try:
            return "tavily", search_tavily(query, max_results)
        except Exception:
            engine = "duckduckgo"  # fall back rather than fail the whole turn

    return "duckduckgo", search_duckduckgo(query, max_results)


def search_tavily(query: str, max_results: int = 5) -> list[dict]:
    """Tavily's search API — built for AI agents, so the snippets are longer
    and more relevant than a normal search engine's. Needs an API key."""
    key = tavily_key()
    if not key:
        raise RuntimeError("No TAVILY_API_KEY set.")

    response = httpx.post(
        TAVILY_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "max_results": max_results, "search_depth": "basic"},
        timeout=20,
    )
    response.raise_for_status()

    # Tavily calls the snippet "content"; we rename it so both engines match.
    return [
        {"title": r["title"], "url": r["url"], "snippet": r["content"]}
        for r in response.json().get("results", [])
    ]


def search_duckduckgo(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo through the ddgs library. Free, and needs no API key."""
    # Search engines fail now and then (timeouts, blocked requests).
    # A failure is often temporary, so we try up to 3 times before giving up.
    for attempt in range(3):
        try:
            raw_results = DDGS().text(query, max_results=max_results)
            break
        except DDGSException:
            if attempt == 2:
                raise
            time.sleep(1)

    # Clean up the output into a simple, predictable shape.
    # Tools should return clean data — the LLM reads this.
    return [
        {"title": r["title"], "url": r["href"], "snippet": r["body"]}
        for r in raw_results
    ]


def read_page(url: str) -> dict:
    """Download a web page and extract its main text (no menus, ads or footers).

    Returns {"url": ..., "title": ..., "text": ...}. Raises an error if the page
    can't be downloaded or has no readable text.
    """
    # trafilatura's downloader identifies itself properly (some sites, like
    # Wikipedia, block unknown bots) — we only shorten its timeout.
    response = fetch_response(url, decode=True, config=DOWNLOAD_CONFIG)
    if response is None:
        raise ValueError("Could not connect (site down, blocked or too slow).")
    if response.status != 200 or not response.html:
        raise ValueError(f"The site answered with HTTP {response.status}.")

    text = trafilatura.extract(response.html, url=url)
    if not text:
        raise ValueError("No readable text on this page.")
    metadata = trafilatura.extract_metadata(response.html)
    title = (metadata.title if metadata else None) or url

    # Remove the page's own footnote markers like [1][12] — they would clash
    # with OUR source numbers [1], [2]... that the LLM uses for citations.
    text = re.sub(r"\[\d+\]", "", text).replace("¶", "")

    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\n\n[...page cut off here...]"
    return {"url": url, "title": title, "text": text}


# Run this file directly to test the tools without any UI:
#   python tools.py
if __name__ == "__main__":
    print(f"Search engine: {default_engine()}"
          f"{'' if tavily_key() else '  (set TAVILY_API_KEY to use Tavily)'}\n")
    engine, results = web_search("what is agentic ai", max_results=3)
    for i, r in enumerate(results, start=1):
        print(f"{i}. [{engine}] {r['title']}\n   {r['url']}\n   {r['snippet'][:160]}\n")

    page = read_page("https://en.wikipedia.org/wiki/AI_agent")
    print(f"read_page -> {page['title']!r}, {len(page['text'])} chars\n{page['text'][:300]}...")
