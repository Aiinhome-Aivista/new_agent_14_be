import time
import logging
import pymysql
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

engine = None
db_session = None
Base = declarative_base()

logger = logging.getLogger(__name__)
logging.getLogger('sqlalchemy.pool').setLevel(logging.ERROR)

def init_db(app):
    global engine, db_session
    
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    db_host = app.config.get('DB_HOST', '72.61.226.68')
    db_port = int(app.config.get('DB_PORT', 3306))
    db_user = app.config.get('DB_USER', 'aiinhome')
    db_pass = app.config.get('DB_PASSWORD', 'Aiin@2026')
    db_name = app.config.get('DB_NAME', 'vpm_db')

    def resilient_connection_creator():
        """Creates a PyMySQL connection with automatic retry logic against transient packet sequence drops."""
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                conn = pymysql.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_pass,
                    database=db_name,
                    connect_timeout=25,
                    read_timeout=30,
                    write_timeout=30,
                    charset='utf8mb4',
                    autocommit=False
                )
                return conn
            except Exception as e:
                logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    raise
                time.sleep(0.4 * attempt)

    engine = create_engine(
        db_uri,
        creator=resilient_connection_creator,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=280,
        pool_timeout=30
    )
    db_session = scoped_session(sessionmaker(autocommit=False,
                                             autoflush=False,
                                             bind=engine))
    Base.query = db_session.query_property()

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session:
            try:
                if exception:
                    db_session.rollback()
                db_session.remove()
            except Exception:
                pass

