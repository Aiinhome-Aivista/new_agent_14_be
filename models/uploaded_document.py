from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class UploadedDocument(Base):
    __tablename__ = 'uploaded_documents'

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size_bytes = Column(Integer, nullable=False, default=0)
    file_size_formatted = Column(String(50), default="0 KB")
    uploaded_by = Column(String(255), nullable=False, default="pm@example.com")
    uploaded_by_role = Column(String(50), default="Project Manager")
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    status = Column(String(50), default="Indexed in Vector Memory")
    risks_detected = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'file_type': self.file_type,
            'size': self.file_size_formatted,
            'size_bytes': self.file_size_bytes,
            'uploaded_by': self.uploaded_by,
            'uploaded_by_role': self.uploaded_by_role,
            'project_id': self.project_id,
            'status': self.status,
            'risks_detected': self.risks_detected,
            'uploaded_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'indexed': True
        }
