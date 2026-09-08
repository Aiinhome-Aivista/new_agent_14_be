from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class KPI(Base):
    __tablename__ = 'kpis'

    id = Column(Integer, primary_key=True, autoincrement=True)
    program_id = Column(Integer, ForeignKey('programs.id'), nullable=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    metric_name = Column(String(100), nullable=False) # e.g. SPI, CPI, Budget Variance
    metric_value = Column(Float, nullable=False)
    trend = Column(Float, nullable=True) # e.g. -2.4
    trend_label = Column(String(100), nullable=True) # e.g. "vs last month"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'program_id': self.program_id,
            'project_id': self.project_id,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'trend': self.trend,
            'trend_label': self.trend_label,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
