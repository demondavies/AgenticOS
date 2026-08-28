"""
ARNIE Agentic OS
Web research capability.

Owns deep web research and page extraction previously embedded in bot.py.
The canonical web_search tool remains in capabilities.web.search.
"""

from __future__ import annotations

import asyncio
import random
import re

from bs4 import BeautifulSoup
from ddgs import DDGS
from playwright.async_api import async_playwright


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
    "Gecko/20100101 Firefox/123.0",
]


async def scrape_web_page_stealth(
    url: str,
    max_chars: int = 4000,
) -> str:
    """Fetch and extract readable page text using Playwright."""

    print(f"🕷️ [Web Research] Scraping: {url}")
    selected_user_agent = random.choice(USER_AGENTS)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )

            try:
                context = await browser.new_context(
                    user_agent=selected_user_agent,
                    viewport={
                        "width": random.randint(1366, 1920),
                        "height": random.randint(768, 1080),
                    },
                    locale="en-US",
                    timezone_id="America/New_York",
                )

                page = await context.new_page()

                await page.add_init_script(
                    """
                    Object.defineProperty(
                        navigator,
                        'webdriver',
                        {get: () => undefined}
                    );
                    window.navigator.chrome = {runtime: {}};
                    Object.defineProperty(
                        navigator,
                        'languages',
                        {get: () => ['en-US', 'en']}
                    );
                    """
                )

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=12000,
                )
                await page.wait_for_timeout(1200)

                html_content = await page.content()

            finally:
                await browser.close()

        soup = BeautifulSoup(html_content, "html.parser")

        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "svg",
                "iframe",
                "noscript",
            ]
        ):
            tag.decompose()

        text = soup.get_text(separator="\n").strip()
        clean_text = re.sub(r"\n{3,}", "\n\n", text)

        return clean_text[:max_chars]

    except Exception as exc:
        return f"Web scrape failure ({url}): {exc}"


async def deep_research_web(
    query: str,
    crawl_top_n: int = 2,
) -> str:
    """
    Search the web and optionally crawl the top results.

    This preserves the existing swarm research contract:
    five search results, with the first `crawl_top_n` pages extracted.
    """

    print(f"🔍 [Deep Researcher] Executing web search: {query}")

    try:
        with DDGS() as ddgs:
            results = [
                result
                for result in ddgs.text(
                    query,
                    max_results=5,
                )
            ]

        if not results:
            return "No search results found."

        research_report = (
            f"# SEARCH RESULTS FOR: '{query}'\n\n"
        )

        urls_to_scrape = []

        for index, result in enumerate(results, start=1):
            title = result.get("title")
            url = result.get("href")
            snippet = result.get("body")

            research_report += (
                f"### {index}. {title}\n"
                f"**URL:** {url}\n"
                f"**Snippet:** {snippet}\n\n"
            )

            if index <= crawl_top_n and url:
                urls_to_scrape.append(url)

        if urls_to_scrape:
            research_report += (
                "## DEEP PAGE CONTENT EXTRACTS\n\n"
            )

            scraped_pages = await asyncio.gather(
                *(
                    scrape_web_page_stealth(url)
                    for url in urls_to_scrape
                )
            )

            for url, content in zip(
                urls_to_scrape,
                scraped_pages,
            ):
                research_report += (
                    f"--- PAGE EXTRACT FROM: {url} ---\n"
                    f"{content}\n\n"
                )

        return research_report

    except Exception as exc:
        return f"Deep research failed: {exc}"


__all__ = [
    "deep_research_web",
    "scrape_web_page_stealth",
]
