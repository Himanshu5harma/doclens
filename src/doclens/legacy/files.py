"""Small shared helpers for generated corpus files."""

from pathlib import Path
from tempfile import NamedTemporaryFile


def write_atomic(path: Path, content: bytes) -> None:
    """Replace a file only after its complete contents have been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
