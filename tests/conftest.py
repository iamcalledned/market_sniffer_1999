from __future__ import annotations

from pathlib import Path

import pytest

from market_sniffer.db.engine import create_db_engine, session_factory
from market_sniffer.db.models import Base
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.registry_service import load_registry


@pytest.fixture()
def session(tmp_path: Path):
    engine = create_db_engine(tmp_path / "test.sqlite3")
    Base.metadata.create_all(engine)
    Session = session_factory(engine)
    with Session() as session:
        WarehouseRepository(session).bootstrap_registry(load_registry())
        yield session
