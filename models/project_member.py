from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON
from datetime import datetime, timezone
from db import Base

class ProjectMember(Base):
    __tablename__ = 'project_members'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(255), nullable=False)
    contact = Column(String(255), nullable=True)
    member_type = Column(String(50), default='Internal FTE')  # 'Internal FTE' or 'Vendor Contractor'
    allocation_pct = Column(Float, default=100.0)
    is_active_today = Column(Boolean, default=True)
    meta_data = Column(JSON, nullable=True)  # Arbitrary project-specific attributes (skills, rate card, location, vendor, etc.)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'role': self.role,
            'contact': self.contact,
            'member_type': self.member_type,
            'allocation_pct': self.allocation_pct,
            'is_active_today': self.is_active_today,
            'meta_data': self.meta_data or {},
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
