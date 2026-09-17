from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db import Base

class TaskItem(Base):
    __tablename__ = 'task_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    jira_key = Column(String(50), nullable=True, index=True)
    summary = Column(Text, nullable=False)
    status = Column(String(50), default="Open")
    priority = Column(String(50), default="Medium")
    assignee = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    project = relationship("Project", backref="tasks")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "jira_key": self.jira_key,
            "summary": self.summary,
            "status": self.status,
            "priority": self.priority,
            "assignee": self.assignee,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
