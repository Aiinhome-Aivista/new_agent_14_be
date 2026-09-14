from sqlalchemy import Column, Integer, JSON, DateTime
from datetime import datetime, timezone
from db import Base

class DashboardSnapshot(Base):
    __tablename__ = 'dashboard_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(JSON, nullable=False) # Aggregated JSON of KPIs, Budgets, Risks for fast frontend serving
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'data': self.data,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
