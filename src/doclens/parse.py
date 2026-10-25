"""Extract inspectable sections and evidence blocks from Python/Sphinx HTML."""

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag, __version__ as bs4_version

from doclens.files import write_atomic


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


def parse_source(source: dict, *, root: Path) -> dict:
    """Verify a downloaded snapshot, then save its structured representation."""
    root = root.resolve()
    raw_path = (root / source["local_path"]).resolve()
    if not raw_path.is_relative_to(root / "data" / "raw"):
        raise ValueError(f"Source {source['source_id']}: raw file must stay under data/raw/.")
    content = raw_path.read_bytes()
    metadata_path = raw_path.with_name(raw_path.name + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError(f"Source {source['source_id']}: metadata must be an object.")
    if any(metadata.get(field) != value for field, value in source.items()):
        raise ValueError(f"Source {source['source_id']}: metadata differs from the manifest; run fetch again.")
    if (
        metadata.get("sha256") != hashlib.sha256(content).hexdigest()
        or metadata.get("size_bytes") != len(content)
    ):
        raise ValueError(f"Source {source['source_id']}: raw content does not match metadata; run fetch again.")

    document = parse_html(content, source_url=source["url"])
    document["source"] = metadata
    relative_path = raw_path.relative_to(root / "data" / "raw")
    destination = (root / "data" / "parsed" / relative_path).with_name(
        relative_path.name + ".json"
    ).resolve()
    if not destination.is_relative_to(root / "data" / "parsed"):
        raise ValueError("Parsed files must stay under data/parsed/.")
    write_atomic(destination, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return document
