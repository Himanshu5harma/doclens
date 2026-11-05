"""Request byte budgets and compatibility of previously stored source records."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
import pytest

from doclens.service.schemas import SourceCreate, SourceRead

BODY = {"name": "Synthetic URL boundary fixture", "product": "python", "version": "3.13",
        "url": "https://docs.python.org/3.13/library/pathlib.html",
        "source_terms_url": "https://docs.python.org/3.13/license.html"}


@pytest.mark.parametrize("field", ["url", "source_terms_url"])
def test_new_source_urls_obey_utf8_bytes_at_the_boundary(field):
    prefix = "https://docs.python.org/3.13/"
    value = prefix + "\u00e9" * ((2048 - len(prefix)) // 2)
    value += "x" * (2048 - len(value.encode()))
    assert len(value.encode()) == 2048
    assert getattr(SourceCreate(**{**BODY, field: value}), field) == value
    with pytest.raises(ValidationError): SourceCreate(**{**BODY, field: value + "x"})


def test_legacy_source_response_does_not_adopt_new_input_byte_limit():
    value = "https://docs.python.org/3.13/" + "\u00e9" * 1200
    response = SourceRead(**{**BODY, "url": value, "id": uuid4(), "workspace_id": uuid4(),
                             "created_by": uuid4(), "created_at": datetime.now(timezone.utc)})
    assert response.url == value
