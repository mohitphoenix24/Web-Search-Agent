"""
TOOLS — the agent's "hands".

An "agent" = an LLM (the brain) + tools (the hands) + a loop (decide -> act -> observe).

A tool is just a normal Python function that does something in the real world
and returns plain data. The LLM decides WHEN to call it (see agent.py).

Phase 1: web_search  — find pages (short snippets only)
Phase 4: read_page   — open one page and read its full text
"""

import re
import time

import trafilatura
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from trafilatura.downloads import fetch_response
from trafilatura.settings import use_config

MAX_PAGE_CHARS = 8000  # ~2,000 tokens. Pages can be 100k+ chars — too big for the LLM's context.

DOWNLOAD_CONFIG = use_config()
DOWNLOAD_CONFIG.set("DEFAULT", "DOWNLOAD_TIMEOUT", "10")  # give up on slow sites after 10s


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web with DuckDuckGo (free, no API key needed).

    Returns a list of results, each like:
        {"title": "...", "url": "...", "snippet": "..."}
    """
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
    results = []
    for r in raw_results:
        results.append({
            "title": r["title"],
            "url": r["href"],
            "snippet": r["body"],
        })
    return results


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
    for i, r in enumerate(web_search("what is agentic ai", max_results=3), start=1):
        print(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}\n")

    page = read_page("https://en.wikipedia.org/wiki/AI_agent")
    print(f"read_page -> {page['title']!r}, {len(page['text'])} chars\n{page['text'][:300]}...")
