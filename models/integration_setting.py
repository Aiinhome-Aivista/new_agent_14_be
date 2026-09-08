from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timezone
from db import Base

class IntegrationSetting(Base):
    __tablename__ = 'integration_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), unique=True, nullable=False) # e.g., 'jira'
    base_url = Column(String(255), nullable=True)
    username_email = Column(String(255), nullable=True)
    api_token = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'provider': self.provider,
            'base_url': self.base_url,
            'username_email': self.username_email,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
            # Do not serialize api_token for security
        }
