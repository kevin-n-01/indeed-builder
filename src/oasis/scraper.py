from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_CULTURE_PATTERNS = re.compile(
    r"about|mission|values?|culture|team|who-we-are|our-story|careers?", re.I
)
_BOILERPLATE_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "iframe"}
_MIN_CONTENT_CHARS = 200
_MAX_CONTENT_CHARS = 4000


def scrape_company(company_url: str) -> str:
    """Scrape mission/values/culture text from a company website."""
    if not company_url:
        return ""

    base = _base_url(company_url)
    pages_text: list[str] = []

    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
        # Always fetch homepage
        home_text, home_links = _fetch_page(client, base)
        if home_text:
            pages_text.append(home_text)

        # Find culture/about subpages from homepage links
        culture_links = [
            urljoin(base, href)
            for href in home_links
            if _CULTURE_PATTERNS.search(href) and _same_domain(base, urljoin(base, href))
        ][:3]  # fetch at most 3 sub-pages

        for url in culture_links:
            text, _ = _fetch_page(client, url)
            if text:
                pages_text.append(text)

    combined = "\n\n".join(pages_text)
    return combined[:_MAX_CONTENT_CHARS] if combined else ""


def _fetch_page(client: httpx.Client, url: str) -> tuple[str, list[str]]:
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except Exception:
        return "", []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect links before stripping tags
    links = [a.get("href", "") for a in soup.find_all("a", href=True)]

    for tag in soup.find_all(_BOILERPLATE_TAGS):
        tag.decompose()

    text = " ".join(soup.get_text(separator=" ").split())
    if len(text) < _MIN_CONTENT_CHARS:
        return "", links
    return text, links


def _base_url(url: str) -> str:
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _same_domain(base: str, url: str) -> bool:
    return urlparse(base).netloc == urlparse(url).netloc
