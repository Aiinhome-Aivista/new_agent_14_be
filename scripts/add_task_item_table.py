import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from db import Base
import db
import models

def migrate():
    print("Creating TaskItem table...")
    app = create_app()
    with app.app_context():
        # This will only create tables that don't exist yet, it won't drop existing ones.
        Base.metadata.create_all(bind=db.engine)
    print("Done!")

if __name__ == '__main__':
    migrate()
