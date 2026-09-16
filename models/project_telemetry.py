from sqlalchemy import Column, Integer, JSON, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class ProjectTelemetry(Base):
    __tablename__ = 'project_telemetries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False, unique=True)
    telemetry_data = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'telemetry_data': self.telemetry_data,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
