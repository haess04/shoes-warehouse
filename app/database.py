from contextlib import contextmanager

from flask import current_app
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()


def init_database(app):
    """Explicit initialization, once per application, never on module import."""
    from app import models  # Register models before creating tables.

    root = app.config["DATA_ROOT"]
    root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(app.config["DATABASE_PATH"])),
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shoes)")}
            if "sale_price" not in columns:
                conn.exec_driver_sql("ALTER TABLE shoes ADD COLUMN sale_price FLOAT")
            if "sale_date" not in columns:
                conn.exec_driver_sql("ALTER TABLE shoes ADD COLUMN sale_date DATE")
        app.config["PHOTOS_ROOT"].mkdir(parents=True, exist_ok=True)
    except Exception:
        engine.dispose()
        raise
    app.extensions["inventory_db"] = {
        "engine": engine,
        "session_factory": sessionmaker(bind=engine, autoflush=False),
    }


@contextmanager
def get_session():
    session = current_app.extensions["inventory_db"]["session_factory"]()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

