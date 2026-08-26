"""AgenticOS web-search capability. No Discord or bot.py dependency."""

from __future__ import annotations

from ddgs import DDGS


def web_search(query: str = "") -> str:
    """Search the web and return runtime search evidence."""
    query = (query or "").strip()

    if not query:
        return "No web search query supplied."

    print(f"🌐 [Web] Searching: {query}")

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))

        if not results:
            return "No search results found."

        return "".join(
            f"Title: {result.get('title')}\n"
            f"Snippet: {result.get('body')}\n"
            f"URL: {result.get('href') or result.get('url') or ''}\n\n"
            for result in results
        )
    except Exception as exc:
        return f"Web Search Error: {exc}"
