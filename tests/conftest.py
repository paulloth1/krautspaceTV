import importlib
import os

import pytest


@pytest.fixture
def db_module(tmp_path, monkeypatch):
    """Import backend.db pointed at a fresh temp sqlite file.

    backend.db reads SIGNAGE_DB_PATH once at import time (DB_PATH is a
    module-level constant), so we set the env var and then (re)import /
    reload the module to pick it up. Each test gets its own temp file so
    tests never share state.
    """
    db_path = tmp_path / "signage-test.db"
    monkeypatch.setenv("SIGNAGE_DB_PATH", str(db_path))

    import backend.db as db

    importlib.reload(db)
    assert db.DB_PATH == db_path

    yield db
