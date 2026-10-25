# Corpus scope and ingestion review

## Selection

The first corpus contains 20 official Python documentation pages: 10 for the 3.12 release line and 10 for 3.13. Each release has the same nine reference topics and its own What’s New page. The explicit list is in [the source manifest](../corpus/sources.json).

Matching reference topics let retrieval experiments compare the same subject across versions. The selection covers files, text, data conversion, and command-line utilities, with both short references and long pages to exercise parsing and later chunking. Release notes provide explicit descriptions of changes that can be checked alongside reference material.

| Topic | Reason for inclusion | Python 3.12 | Python 3.13 |
| --- | --- | --- | --- |
| `pathlib` | Path objects and documented API changes | [Reference](https://docs.python.org/3.12/library/pathlib.html) | [Reference](https://docs.python.org/3.13/library/pathlib.html) |
| `os.path` | Related path functions and terminology | [Reference](https://docs.python.org/3.12/library/os.path.html) | [Reference](https://docs.python.org/3.13/library/os.path.html) |
| `glob` | File matching, flags, and examples | [Reference](https://docs.python.org/3.12/library/glob.html) | [Reference](https://docs.python.org/3.13/library/glob.html) |
| `shutil` | File operations and recipes | [Reference](https://docs.python.org/3.12/library/shutil.html) | [Reference](https://docs.python.org/3.13/library/shutil.html) |
| `tempfile` | File lifecycle and parameter behavior | [Reference](https://docs.python.org/3.12/library/tempfile.html) | [Reference](https://docs.python.org/3.13/library/tempfile.html) |
| `json` | Serialization, conversion tables, and examples | [Reference](https://docs.python.org/3.12/library/json.html) | [Reference](https://docs.python.org/3.13/library/json.html) |
| `re` | Exact syntax, escaping, and pattern examples | [Reference](https://docs.python.org/3.12/library/re.html) | [Reference](https://docs.python.org/3.13/library/re.html) |
| `datetime` | Longer API descriptions, tables, and examples | [Reference](https://docs.python.org/3.12/library/datetime.html) | [Reference](https://docs.python.org/3.13/library/datetime.html) |
| `argparse` | Parameter explanations and nested sections | [Reference](https://docs.python.org/3.12/library/argparse.html) | [Reference](https://docs.python.org/3.13/library/argparse.html) |
| What’s New | Release changes and migration context | [Release notes](https://docs.python.org/3.12/whatsnew/3.12.html) | [Release notes](https://docs.python.org/3.13/whatsnew/3.13.html) |

The corpus does not cover all of Python. Linked PEPs, tutorials, source code, and other library pages are not fetched automatically. A linked page is not indexed evidence. A release note can discuss earlier releases; the metadata identifies the document's release line, not the version of every API mentioned in its text.

The labels `3.12` and `3.13` describe release lines, not immutable initial-release snapshots. The official pages can receive updates. Fetch timestamps and SHA-256 hashes identify the downloaded bytes; later ingestion refreshes those files rather than archiving every previous snapshot. Source terms are linked separately in each manifest record.

## Repeatable ingestion

From the repository root:

```bash
uv run python -m doclens ingest
```

The CLI validates the entire manifest, then downloads and parses each source in order using the existing components. It writes raw HTML, a provenance sidecar, and structured JSON under ignored `data/`. `--manifest PATH` selects another curated list. Separate `fetch` and offline `parse` commands remain available for debugging.

The command stops on failure with a nonzero exit code. Sources already completed remain available. It does not promise a transaction across the corpus or across the HTML/metadata pair; parsing checks hashes and metadata before producing output. Running the command again refreshes the same paths.

## Verification on 2026-10-25

One live `ingest` run successfully fetched and parsed all 20 manifest entries. Every final URL passed the HTTPS host and version-prefix policy. All responses were HTTP 200, and page titles identified the requested Python release line.

| Release line | Pages | Reference / release notes | Sections | Content blocks | Code blocks |
| --- | ---: | --- | ---: | ---: | ---: |
| 3.12 | 10 | 9 / 1 | 226 | 3,429 | 326 |
| 3.13 | 10 | 9 / 1 | 245 | 3,670 | 324 |
| Total | 20 | 18 / 2 | 471 | 7,099 | 650 |

These are ingestion counts, not retrieval or answer-quality scores. Verification compared each saved raw file's hash and size with its sidecar, all manifest fields with its provenance, and parsed provenance with that same sidecar. It checked heading counts, paragraph text coverage outside tables/signatures/navigation, all 650 code blocks including whitespace and duplicate occurrences, and that every extracted anchor exists in the original article. All source links retain the manifest's explicit version URL.

Manifest SHA-256 for this run:

```text
25f48fd84536b623d9efc056ac8d5f775d71217aae48c4c37bb30ec1d9b3daa8
```

Detailed per-page hashes and counts from this review are saved locally in ignored `data/reports/corpus-review.json`. That file records this verification run and is not automatically generated by `ingest`.

## Manual sample inspection

The following extracted samples were inspected against their saved original HTML. This is a sample review, not a claim that every passage was manually checked.

| Source | Sample inspected | Result |
| --- | --- | --- |
| Python 3.12 `tempfile` | `NamedTemporaryFile` signature and parameter descriptions | Defaults and API anchor retained; permalink symbol removed |
| Python 3.13 `glob` | `glob.translate` signature, description, and example | Keyword-only arguments and code preserved under the API anchor |
| Python 3.12 `json` | `json.loads` signature and change notes | Signature, encoding discussion, and version notes retained |
| Python 3.13 `re` | `re.sub` description and multiline example | Backslashes, prompts, and code line breaks retained |
| Python 3.12 `datetime` | `datetime.fromisoformat` description and exception list | Parent API context and list paragraphs retained |
| Python 3.13 `argparse` | `deprecated` subsection and warning example | Heading path, example indentation, and version note retained |
| Python 3.12 What’s New | `pathlib` subsection | Release-note context and section anchor retained |
| Python 3.13 What’s New | Improved and removed `pathlib` subsections | Same heading text has distinct original anchors; the sections remain separate |

The parser still targets the observed Python/Sphinx layout. Images are not interpreted and complex table relationships are not modeled. These checks establish usable inputs for the next milestone, not support for every documentation layout or proof that future retrieval will find the right evidence.

The offline suite has 22 passing checks, including the downloader's redirect/protocol cases, parser provenance checks, and complete-ingestion success and failure cases:

```bash
uv run python -m unittest discover -s tests -v
```
