from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, JSON
from datetime import datetime, timezone
from db import Base

class ProjectMilestone(Base):
    __tablename__ = 'project_milestones'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    milestone_code = Column(String(50), nullable=False)  # e.g., 'M-01', 'PH-01', 'M1'
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_date = Column(String(100), default='TBD')
    status = Column(String(50), default='Scheduled')  # 'Completed', 'In Progress', 'Scheduled', 'On Hold', 'Released', 'Authorized'
    completion_pct = Column(Integer, default=0)
    days_left = Column(Integer, default=0)
    tranche_amount = Column(Float, default=0.0)
    sla_score = Column(Float, nullable=True)
    sla_status = Column(String(50), default='Scheduled')
    meta_data = Column(JSON, nullable=True)  # Dynamic milestone data (deliverables, signoff criteria, custom tags, etc.)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.milestone_code,
            'numeric_id': self.id,
            'project_id': self.project_id,
            'milestone_code': self.milestone_code,
            'name': self.name,
            'description': self.description,
            'target_date': self.target_date,
            'status': self.status,
            'completion_pct': self.completion_pct,
            'days_left': self.days_left,
            'tranche_amount': self.tranche_amount,
            'sla_score': self.sla_score,
            'sla_status': self.sla_status,
            'meta_data': self.meta_data or {},
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
