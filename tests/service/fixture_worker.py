"""Test process only: real Celery/Redis/DB, explicitly synthetic acquisition.

No fault switches are shipped in the application. A parser barrier lets the
parent test kill only this process group after raw staging, then test recovery.
"""

from pathlib import Path
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from doclens.parse import parse_html
from doclens.service.ingestion import utcnow
from doclens.service.ingestion_io import IngestionError, Snapshot
from doclens.service.models import IngestionJob
from doclens.service.settings import WorkerSettings
from doclens.service.worker import create_worker, start_worker

settings = WorkerSettings()
root = settings.artifact_root.parent
HTML = b'<main><section id="fixture"><h1>Synthetic worker fixture</h1><p>Reference.</p><pre>if True:\n    print("ok")\n</pre></section></main>'


def fetcher(source):
    if source["name"].startswith("retry-"):
        raise IngestionError("http_temporary", retryable=True)
    if source["name"].startswith("crash-"):
        return Snapshot(HTML.replace(b"Reference.", b"pause-after-raw"), source["url"], utcnow())
    return Snapshot(HTML, source["url"], utcnow())


def parser(content, *, source_url):
    barrier = root / "parser-barrier"
    if b"pause-after-raw" in content and not barrier.exists():
        barrier.write_text("synthetic parser paused after raw staging")
        time.sleep(50)  # Parent kills its own worker group, not any user process.
    return parse_html(content, source_url=source_url)


if __name__ == "__main__":
    app = create_worker(settings, fetcher=fetcher, parser=parser)
    raise SystemExit(start_worker(app, settings))
