from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class GuardrailPolicy(Base):
    """
    Persistent active guardrail and compliance policies.
    """
    __tablename__ = 'guardrail_policies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=True)
    policy_id = Column(String(50), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default='Active')
    level = Column(String(50), default='Medium') # Strict, High, Warning, Medium, Low
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.policy_id,
            'numeric_id': self.id,
            'project_id': self.project_id,
            'is_global': self.project_id is None,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'status': self.status,
            'level': self.level,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
