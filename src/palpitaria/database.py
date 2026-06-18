from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from palpitaria.config import settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _ensure_engine() -> Engine:
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    if settings.database_config_error:
        raise RuntimeError(settings.database_config_error)
    _engine = create_engine(
        settings.db_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    _session_factory = sessionmaker(bind=_engine, autocommit=False, autoflush=True)
    return _engine


class _EngineProxy:
    """Lazy engine — import do app não exige DATABASE_URL (Cloud Run lê env no runtime)."""

    def __getattr__(self, name: str):
        return getattr(_ensure_engine(), name)


engine = _EngineProxy()


class _SessionLocalFactory:
    def __call__(self) -> Session:
        _ensure_engine()
        assert _session_factory is not None
        return _session_factory()

    def __getattr__(self, name: str):
        _ensure_engine()
        assert _session_factory is not None
        return getattr(_session_factory, name)


SessionLocal = _SessionLocalFactory()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def apply_schema_migrations() -> None:
    """Migrações incrementais — preserva dados existentes (ADD COLUMN + defaults)."""
    if settings.database_config_error:
        return
    engine = _ensure_engine()
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text("ALTER TABLE branches ADD COLUMN IF NOT EXISTS side VARCHAR(10) DEFAULT 'BACK'")
            )
            conn.execute(
                text(
                    "UPDATE branches SET side = 'LAY' WHERE "
                    "lower(name) LIKE '%correct score%' OR lower(slug) LIKE '%correct%score%' "
                    "OR lower(coalesce(description, '')) LIKE '%correct score%' "
                    "OR lower(name) LIKE '%placar exato%'"
                )
            )
            conn.execute(text("UPDATE branches SET side = 'BACK' WHERE side IS NULL"))
        elif dialect == "sqlite":
            branch_cols = {c["name"] for c in inspect(engine).get_columns("branches")}
            if "side" not in branch_cols:
                conn.execute(text("ALTER TABLE branches ADD COLUMN side VARCHAR(10) DEFAULT 'BACK'"))
                conn.execute(
                    text(
                        "UPDATE branches SET side = 'LAY' WHERE "
                        "lower(name) LIKE '%correct score%' OR lower(slug) LIKE '%correct%score%' "
                        "OR lower(coalesce(description, '')) LIKE '%correct score%' "
                        "OR lower(name) LIKE '%placar exato%'"
                    )
                )
                conn.execute(text("UPDATE branches SET side = 'BACK' WHERE side IS NULL"))


def init_db() -> None:
    if settings.database_config_error:
        return
    from palpitaria import models  # noqa: F401

    Base.metadata.create_all(bind=_ensure_engine())
    apply_schema_migrations()
