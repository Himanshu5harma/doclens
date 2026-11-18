"""Python/Sphinx HTML adapter: versioned HTTPS acquisition and article parsing."""

import time
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag, __version__ as bs4_version

from doclens.sources.base import RAW_LIMIT, IngestionError, Snapshot
from doclens.sources.http import PinnedTransport

POLICY = "python-sphinx-service-v1"


def validate_destination(url: str, version: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (len(url) <= 2048 and parsed.scheme == "https" and parsed.hostname == "docs.python.org"
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and version in ("3.12", "3.13")
                 and parsed.path.startswith(f"/{version}/") and parsed.path.endswith(".html")
                 and not any(ord(c) < 33 for c in url) and "%" not in parsed.path
                 and "\\" not in url and all(part not in (".", "..") for part in parsed.path.split("/")))
    except ValueError:
        valid = False
    if not valid:
        raise IngestionError("unsafe_destination")


def validate_source(source: dict) -> None:
    if source["connector_kind"] != "https_html" or source["product"] != "python":
        raise IngestionError("unsupported_source")
    validate_destination(source["url"], source["version"])


def fetch_python(source: dict, *, transport=None, clock=time.monotonic) -> Snapshot:
    validate_source(source)
    current = source["url"]
    deadline = clock() + 30
    try:
        with httpx.Client(transport=transport or PinnedTransport(), timeout=httpx.Timeout(5),
                          follow_redirects=False, trust_env=False,
                          headers={"User-Agent": "DocLens/0.1 (curated documentation ingestion)",
                                   "Accept": "text/html", "Accept-Encoding": "identity"}) as client:
            for redirect in range(3):
                validate_destination(current, source["version"])
                if clock() >= deadline:
                    raise IngestionError("network_error", retryable=True)
                with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect == 2 or "location" not in response.headers:
                            raise IngestionError("unsafe_destination")
                        current = urljoin(current, response.headers["location"])
                        continue  # Validate before connecting or reading a redirect body.
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        raise IngestionError("http_temporary", retryable=True)
                    if response.status_code != 200:
                        raise IngestionError("http_rejected")
                    if (response.headers.get("content-type", "").split(";")[0].strip().lower() not in
                            ("text/html", "application/xhtml+xml")
                            or response.headers.get("content-encoding", "identity").lower() != "identity"):
                        raise IngestionError("invalid_html")
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdecimal() or int(length) > RAW_LIMIT):
                        raise IngestionError("size_limit")
                    content = bytearray()
                    for piece in response.iter_raw(chunk_size=64 * 1024):
                        if clock() >= deadline:
                            raise IngestionError("network_error", retryable=True)
                        if len(content) + len(piece) > RAW_LIMIT:
                            raise IngestionError("size_limit")
                        content.extend(piece)
                    if not content.strip():
                        raise IngestionError("invalid_html")
                    return Snapshot(bytes(content), current, datetime.now(timezone.utc))
    except (httpx.HTTPError, OSError):
        # Never expose request URLs, server bodies, headers or exception reprs.
        raise IngestionError("network_error", retryable=True) from None
    raise IngestionError("unsafe_destination")


HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _prose(element: Tag) -> str:
    # Joining with a separator would split inline API names and punctuation.
    return " ".join(element.get_text().split())


def _anchor(element: Tag) -> str | None:
    """Find the closest real anchor, including a Sphinx API definition's ID."""
    for parent in [element, *element.parents]:
        if parent.get("id"):
            return parent["id"]
        if parent.name == "dd":
            definition = parent.find_previous_sibling("dt")
            if definition is not None and definition.get("id"):
                return definition["id"]
    return None


def _source_url(page_url: str, anchor: str | None) -> str:
    return f"{page_url}#{quote(anchor)}" if anchor else page_url


def parse_html(content: bytes, *, source_url: str) -> dict:
    """Parse the article region only; fail clearly on unsupported layouts."""
    soup = BeautifulSoup(content, "html.parser")
    article = soup.select_one('[role="main"]') or soup.find("main")
    if article is None or article.find("h1") is None:
        raise ValueError("Expected a Python/Sphinx article with a main region and h1 heading.")

    for noise in article.select("nav, aside, footer, script, style, .headerlink, .viewcode-link"):
        noise.decompose()

    sections = []
    heading_stack = []
    section_containers = {}
    for element in article.find_all(HEADINGS + ["p", "pre", "dt", "li", "tr"]):
        if element.name in HEADINGS:
            level = int(element.name[1])
            heading = _prose(element)
            while heading_stack and heading_stack[-1]["level"] >= level:
                heading_stack.pop()
            anchor = _anchor(element)
            section = {
                "heading": heading,
                "level": level,
                "heading_path": [parent["heading"] for parent in heading_stack] + [heading],
                "anchor": anchor,
                "url": _source_url(source_url, anchor),
                "blocks": [],
            }
            sections.append(section)
            heading_stack.append(section)
            container = element.find_parent("section")
            if container is not None:
                section_containers[id(container)] = section
            continue

        if not sections:
            continue
        # These descendants are already included in a signature, code block,
        # or table row. Do not count them a second time as paragraphs.
        if element.name != "tr" and element.find_parent(["pre", "dt", "table"]):
            continue
        if element.name == "li" and element.find(["p", "pre", "dt", "li", "table"]):
            continue

        kind = {
            "p": "paragraph", "pre": "code", "dt": "signature",
            "li": "list_item", "tr": "table_row",
        }[element.name]
        if kind == "code":
            text = element.get_text()  # Retain indentation, newlines, and prompts.
        elif kind == "table_row":
            text = " | ".join(_prose(cell) for cell in element.find_all(["th", "td"], recursive=False))
        else:
            text = _prose(element)
        if not text.strip():
            continue

        section = next(
            (section_containers[id(parent)] for parent in element.parents if id(parent) in section_containers),
            sections[-1],
        )
        anchor = _anchor(element)
        section["blocks"].append({
            "kind": kind, "text": text, "anchor": anchor,
            "url": _source_url(source_url, anchor),
        })

    if not any(section["blocks"] for section in sections):
        raise ValueError("No article content blocks were extracted.")
    return {
        "schema_version": 1,
        "parser": {"name": "python-sphinx", "version": 1, "beautifulsoup_version": bs4_version},
        "title": _prose(article.find("h1")),
        "sections": sections,
    }
