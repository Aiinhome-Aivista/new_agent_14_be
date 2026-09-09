from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class RiskRegister(Base):
    __tablename__ = 'risk_register'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    risk_id = Column(String(50), nullable=False) # e.g. R-102
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String(50), nullable=False) # Critical, High, Medium, Low
    status = Column(String(50), nullable=False) # Open, Mitigated, Closed
    owner = Column(String(100), default='Unassigned', nullable=True)
    mitigation_plan = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'risk_id': self.risk_id,
            'title': self.title,
            'description': self.description,
            'severity': self.severity,
            'status': self.status,
            'owner': self.owner or 'Unassigned',
            'mitigation_plan': self.mitigation_plan,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
