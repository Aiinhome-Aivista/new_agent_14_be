from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from datetime import datetime, timezone
from db import Base

class IntegrationSetting(Base):
    __tablename__ = 'integration_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    provider = Column(String(50), nullable=False) # e.g., 'jira', 'azure_devops'
    base_url = Column(String(500), nullable=True)
    username_email = Column(String(255), nullable=True)
    api_token = Column(Text, nullable=True)
    is_connected = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('project_id', 'provider', name='uq_project_provider'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'provider': self.provider,
            'base_url': self.base_url or '',
            'username_email': self.username_email or '',
            'api_token': self.api_token or '',
            'is_connected': bool(self.is_connected),
            'has_token': bool(self.api_token),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

