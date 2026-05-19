import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine


def get_database_path():
    """Return a writable SQLite path for the app database."""
    db_dir = Path(tempfile.gettempdir()) / "regulatory_app"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "regulatory_app.db"


def get_database_url():
    db_path = get_database_path()
    return f"sqlite:///{db_path.as_posix()}"


def get_engine():
    return create_engine(get_database_url())
