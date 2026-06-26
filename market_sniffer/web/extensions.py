from __future__ import annotations

from flask import g
from market_sniffer.db.engine import create_db_engine, session_factory
from market_sniffer.settings import get_settings

_engine = None
_session_class = None


def get_db_session():
    """Returns the current database session for the request context."""
    global _engine, _session_class
    if "db_session" not in g:
        if _engine is None:
            settings = get_settings()
            _engine = create_db_engine(settings.db_path)
            _session_class = session_factory(_engine)
        g.db_session = _session_class()
    return g.db_session


def close_db_session(exception=None):
    """Closes the current database session at the end of the request context."""
    db_session = g.pop("db_session", None)
    if db_session is not None:
        db_session.close()
