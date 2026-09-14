from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from db import Base

class GeneratedReport(Base):
    __tablename__ = 'generated_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # 'pdf' or 'docx'
    report_type = Column(String(100), default='Executive Briefing')
    file_size = Column(String(50), nullable=True)
    file_path = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    generated_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship('Project', backref='reports')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'filename': self.filename,
            'file_type': self.file_type,
            'type': self.report_type or 'Executive Briefing',
            'date': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'size': self.file_size or 'Unknown',
            'summary': self.summary or '',
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else None,
            'url': f"/api/reports/download/{self.id}"
        }
