from sqlalchemy import Column, Integer, JSON, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class DashboardSnapshot(Base):
    __tablename__ = 'dashboard_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)
    program_id = Column(Integer, ForeignKey('programs.id'), nullable=True)
    data = Column(JSON, nullable=False) # Aggregated JSON of KPIs, Budgets, Risks for fast frontend serving
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'program_id': self.program_id,
            'data': self.data,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
