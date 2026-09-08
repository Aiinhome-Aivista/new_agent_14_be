from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, String
from datetime import datetime, timezone
from db import Base

class Budget(Base):
    __tablename__ = 'budgets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    period = Column(String(50), nullable=False) # e.g., "Q1 2026", "Sprint 5"
    planned_spend = Column(Numeric(12, 2), nullable=False)
    actual_spend = Column(Numeric(12, 2), nullable=False)
    variance = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'period': self.period,
            'planned_spend': float(self.planned_spend),
            'actual_spend': float(self.actual_spend),
            'variance': float(self.variance),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
