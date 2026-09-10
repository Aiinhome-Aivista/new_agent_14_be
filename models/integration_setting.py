from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime, timezone
from db import Base

class IntegrationSetting(Base):
    __tablename__ = 'integration_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), unique=True, nullable=False) # e.g., 'jira'
    base_url = Column(String(255), nullable=True)
    username_email = Column(String(255), nullable=True)
    api_token = Column(String(255), nullable=True)
    is_connected = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'provider': self.provider,
            'base_url': self.base_url or '',
            'username_email': self.username_email or '',
            'is_connected': bool(self.is_connected),
            'has_token': bool(self.api_token),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
