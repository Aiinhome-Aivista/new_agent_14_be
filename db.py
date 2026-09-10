from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

engine = None
db_session = None
Base = declarative_base()

import logging
logging.getLogger('sqlalchemy.pool').setLevel(logging.ERROR)

def init_db(app):
    global engine, db_session
    engine = create_engine(
        app.config['SQLALCHEMY_DATABASE_URI'],
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=60,
        pool_timeout=30,
        connect_args={'connect_timeout': 10}
    )
    db_session = scoped_session(sessionmaker(autocommit=False,
                                             autoflush=False,
                                             bind=engine))
    Base.query = db_session.query_property()

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session:
            try:
                db_session.remove()
            except Exception:
                pass
