"""Test fixtures and path bootstrap."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from agent.config import Config  # noqa: E402
from storage.database import Database  # noqa: E402


@pytest.fixture
def config():
    cfg = Config()
    return cfg.validated()


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "agent.db"))
    database.connect()
    yield database
    database.close()
