"""The actual CLI must signal a failed worker startup to its caller."""

import os
import signal
import subprocess
import sys

import pytest

pytest.importorskip("celery", reason="Optional worker extra.")


def test_unavailable_broker_startup_exits_nonzero(tmp_path):
    config = tmp_path / "dummy.env"
    config.write_text("DOCLENS_DATABASE_URL=postgresql+psycopg://unused:dummy@127.0.0.1:1/test\n"
                      "DOCLENS_BROKER_URL=redis://:dummy@127.0.0.1:1/0\n"
                      "DOCLENS_QUEUE=doclens-cli-failure-fixture\n")
    config.chmod(0o600)
    env = {name: value for name, value in os.environ.items() if not name.startswith("DOCLENS_")}
    log = tmp_path / "worker.log"
    with log.open("wb") as stream:
        process = subprocess.Popen([sys.executable, "-m", "doclens.service.worker", "worker", "--env-file", str(config)],
            env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=18)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
    assert process.returncode != 0
    assert "CRITICAL" in log.read_text() and "Shutting down" in log.read_text()
