import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-secret-key')

    # Database
    DB_HOST = os.getenv('DB_HOST', '72.61.226.68')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_USER = os.getenv('DB_USER', 'aiinhome')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'Aiin@2026')
    DB_NAME = os.getenv('DB_NAME', 'vpm_db')

    # SQLAlchemy config
    import urllib.parse
    encoded_password = urllib.parse.quote_plus(DB_PASSWORD)
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # LLM Tiering
    LLM_API_URL = os.getenv('LLM_API_URL', 'http://122.163.121.176:3041/api/generate')
    LLM_MODEL = os.getenv('LLM_MODEL', 'mistral-small:24b')
    LLM_MODEL_HIGH_TIER = os.getenv('LLM_MODEL_HIGH_TIER', 'mistral-small:24b')
    LLM_MODEL_MID_TIER = os.getenv('LLM_MODEL_MID_TIER', 'mistral:latest')

    # Jira
    JIRA_URL = os.getenv('JIRA_URL')
    JIRA_EMAIL = os.getenv('JIRA_EMAIL')
    JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
