from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime, timezone
from db import Base

class Project(Base):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True, autoincrement=True)
    jira_key = Column(String(50), nullable=True, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default='Active')
    project_manager_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'jira_key': self.jira_key,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'project_manager_id': self.project_manager_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
