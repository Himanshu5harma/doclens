"""Offline schema, location, frozen-input and historical-scope checks."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from doclens.service import issue_export as issue
from doclens.service.ingestion_io import ArtifactStore, IngestionError
from doclens.service.schemas import SourceCreate

ROOT = Path(__file__).resolve().parents[2]
CONTENT = (ROOT / issue.CURATION_PATH).read_bytes()


def value():
    return json.loads(CONTENT)


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()


def stage(tmp_path, content=CONTENT):
    return ArtifactStore(tmp_path).put("reviewed", content, "raw")


def test_catalog_curation_and_typed_historical_scope_agree():
    assert hashlib.sha256(CONTENT).hexdigest() == issue.EXPECTED_SHA256
    catalog = json.loads((ROOT / "corpus/expanded/sources.json").read_text())
    entry = next(s for s in catalog["sources"] if s["catalog_id"] == "cpython-88221-curated-v1")
    assert entry.pop("registration") == issue.REGISTRATION
    assert entry == issue.issue_source_metadata(CONTENT)
    assert SourceCreate(**issue.REGISTRATION).version == "3.8"
    metadata = issue.issue_source_metadata(CONTENT)
    assert metadata["applicability"] == "historical_context_only"
    assert metadata["current_release_guidance"] is False and metadata["independent_review"] is False
    assert metadata["issue_state_at_observation"] == "open"
    assert metadata["comment_timestamps_complete"] is False


@pytest.mark.parametrize("change", [
    {"version": "3.13"}, {"product": "other"}, {"url": issue.SOURCE_URL.replace("88221", "88222")},
    {"document_type": "reference"}, {"source_terms_url": "https://example.test/terms"},
])
def test_uncurated_registration_is_rejected_before_filesystem_access(change, tmp_path):
    with pytest.raises(ValidationError):
        SourceCreate(**(issue.REGISTRATION | change))
    with pytest.raises(IngestionError) as error:
        issue.fetch_issue_export(issue.REGISTRATION | change, export_root=tmp_path)
    assert error.value.code == "unsupported_source"


@pytest.mark.parametrize("field,new", [
    ("schema_version", "other"), ("repository", "other/repo"), ("issue_number", 88222),
    ("version", "3.13"), ("reported_versions", ["3.13"]), ("applicability", "current_guidance"),
    ("synthetic", "false"), ("independent_review", True), ("workspace_id", "fixture-secret"),
    ("observed_at", "2020-01-01T00:00:00Z"), ("observed_at", "2026-11-09T00:00:00"),
])
def test_invalid_scope_and_metadata_fail_with_fixed_safe_error(field, new):
    data = value(); data[field] = new
    with pytest.raises(IngestionError) as error:
        issue.load_export(encoded(data))
    assert error.value.code == "issue_export_invalid" and "fixture-secret" not in str(error.value)


@pytest.mark.parametrize("case", ["duplicate_comment", "unknown_comment", "timestamp_status", "date_order", "future_date",
                                  "comment_first", "open_closed_date", "closure_before_creation", "unknown_entry_field", "empty_blocks", "code_language"])
def test_entry_identities_dates_and_structure_are_validated(case):
    data = value()
    if case == "duplicate_comment": data["entries"][2]["comment_id"] = data["entries"][1]["comment_id"]
    if case == "unknown_comment": data["entries"][1]["comment_id"] = 123
    if case == "timestamp_status": data["entries"][1]["timestamp_status"] = "supplied"
    if case == "date_order": data["entries"][0]["updated_at"] = "2020-01-01T00:00:00Z"
    if case == "future_date": data["entries"][0]["updated_at"] = "2030-01-01T00:00:00Z"
    if case == "comment_first": data["entries"] = list(reversed(data["entries"]))
    if case == "open_closed_date": data["closed_at"] = "2022-01-01T00:00:00Z"
    if case == "closure_before_creation": data.update(issue_state="closed", closed_at="2020-01-01T00:00:00Z")
    if case == "unknown_entry_field": data["entries"][1]["url"] = "https://evil.test/fixture-secret"
    if case == "empty_blocks": data["entries"][1]["blocks"] = []
    if case == "code_language": data["entries"][1]["blocks"][0]["language"] = "python"
    with pytest.raises(IngestionError, match="reviewed"):
        issue.load_export(encoded(data))


@pytest.mark.parametrize("content", [b"", b"{", b'{}{}', b'{"synthetic":false,"synthetic":true}', b'{"a":NaN}', b'\xff', b'x' * (issue.EXPORT_LIMIT + 1)])
def test_malformed_duplicate_nonfinite_and_oversized_json_is_rejected(content):
    with pytest.raises(IngestionError):
        issue.load_export(content)


def test_locations_metadata_unknown_dates_hashes_and_repeatability():
    document = issue.parse_issue_export(CONTENT, source_url=issue.SOURCE_URL)
    assert document == issue.parse_issue_export(CONTENT, source_url=issue.SOURCE_URL)
    assert len(document["sections"]) == 4
    assert document["sections"][0]["url"] == issue.SOURCE_URL
    for entry, section in zip(value()["entries"], document["sections"]):
        location = section["location"]
        assert location["comment_id"] == entry["comment_id"]
        assert location["upstream_body_sha256"] == entry["upstream_body_sha256"]
        if entry["kind"] == "comment":
            assert section["url"] == issue.SOURCE_URL + f'#issuecomment-{entry["comment_id"]}'
            assert location["created_at"] is None and location["updated_at"] is None
        for old, block in zip(entry["blocks"], section["blocks"]):
            assert block["text"] == old["text"] and block["authorship"] == "curator_summary"
            assert block["content_sha256"] == hashlib.sha256(old["text"].encode()).hexdigest()


def test_synthetic_structured_code_keeps_whitespace_and_never_executes(tmp_path):
    data = value(); data["synthetic"] = True
    marker = tmp_path / "should-not-exist"
    code = f"from pathlib import Path\n\nif True:\n    Path({str(marker)!r}).write_text('executed')\n"
    data["entries"][1]["blocks"].append({"kind": "code", "text": code, "language": "python", "authorship": "synthetic_fixture"})
    raw = encoded(data)
    block = issue.parse_issue_export(raw, source_url=issue.SOURCE_URL)["sections"][1]["blocks"][1]
    assert block["text"] == code and block["language"] == "python"
    assert not marker.exists()
    metadata = issue.issue_source_metadata(raw)
    assert metadata["synthetic"] is True and metadata["authority"] == "synthetic_test_fixture"


def test_closed_state_does_not_generate_a_fix_or_current_release_claim():
    data = value(); data["synthetic"] = True; data["issue_state"] = "closed"; data["closed_at"] = "2023-01-01T00:00:00Z"
    for entry in data["entries"]:
        entry["blocks"] = [{"kind": "paragraph", "text": "Synthetic closure fixture; no verified fix is recorded.", "authorship": "synthetic_fixture"}]
    raw = encoded(data)
    metadata = issue.issue_source_metadata(raw)
    assert metadata["issue_state_at_observation"] == "closed" and metadata["current_release_guidance"] is False
    document = issue.parse_issue_export(raw, source_url=issue.SOURCE_URL)
    assert all(b["text"] == "Synthetic closure fixture; no verified fix is recorded." for s in document["sections"] for b in s["blocks"])


def test_frozen_local_export_acquisition_is_repeatable_and_hash_checked(tmp_path):
    key, digest = stage(tmp_path)
    assert digest == issue.EXPECTED_SHA256
    snapshot = issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path)
    assert snapshot.content == CONTENT and snapshot.final_url == issue.SOURCE_URL
    assert issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path).content == CONTENT
    (tmp_path / key).write_bytes(CONTENT.replace(b'3.8', b'3.9'))
    with pytest.raises(IngestionError) as error:
        issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path)
    assert error.value.code == "issue_export_invalid"


def test_missing_symlink_and_nonregular_input_fail_safely(tmp_path):
    with pytest.raises(IngestionError) as error:
        issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path)
    assert error.value.code == "issue_export_unavailable" and str(tmp_path) not in str(error.value)
    folder = tmp_path / "reviewed"; folder.mkdir()
    link = folder / (issue.EXPECTED_SHA256 + ".raw")
    target = tmp_path / "other"; target.write_bytes(CONTENT);link.symlink_to(target)
    with pytest.raises(IngestionError): issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path)
    link.unlink();link.mkdir()
    with pytest.raises(IngestionError): issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path)


def test_exact_export_size_limit_accepts_complete_reviewed_json(tmp_path, monkeypatch):
    content = CONTENT + b" " * (issue.EXPORT_LIMIT - len(CONTENT))
    monkeypatch.setattr(issue, "EXPECTED_SHA256", hashlib.sha256(content).hexdigest())
    stage(tmp_path, content)
    assert issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path).content == content
    with pytest.raises(IngestionError): issue.load_export(content + b" ")


def test_nonregular_input_does_not_leak_an_open_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "reviewed" / (issue.EXPECTED_SHA256 + ".raw")
    path.mkdir(parents=True)
    opened = []; original = os.open
    def capture(*args, **kwargs):
        fd = original(*args, **kwargs); opened.append(fd); return fd
    monkeypatch.setattr(issue.os, "open", capture)
    try:
        with pytest.raises(IngestionError): issue.fetch_issue_export(issue.REGISTRATION, export_root=tmp_path)
        assert len(opened) == 1
        with pytest.raises(OSError): os.fstat(opened[0])
    finally:
        for fd in opened:
            try: os.close(fd)
            except OSError: pass
