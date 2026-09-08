from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

engine = None
db_session = None
Base = declarative_base()

def init_db(app):
    global engine, db_session
    engine = create_engine(
        app.config['SQLALCHEMY_DATABASE_URI'],
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=180,
    )
    db_session = scoped_session(sessionmaker(autocommit=False,
                                             autoflush=False,
                                             bind=engine))
    Base.query = db_session.query_property()

    # Import all modules here that might define models so that
    # they will be registered properly on the metadata.
    # from models import ...
    
    # Normally we might call Base.metadata.create_all(bind=engine) here,
    # but in a real app migrations (like Alembic) are preferred.
    # Base.metadata.create_all(bind=engine)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session:
            db_session.remove()
