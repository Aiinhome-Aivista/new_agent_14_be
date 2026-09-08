from sqlalchemy import Column, Integer, String, Text, JSON, DateTime
from datetime import datetime, timezone
from db import Base

class ApprovalQueue(Base):
    """
    Human-in-the-loop items (escalations, report publishing).
    """
    __tablename__ = 'approval_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_type = Column(String(100), nullable=False) # e.g., 'publish_report', 'escalate_risk'
    payload = Column(JSON, nullable=False)
    status = Column(String(50), default='Pending') # Pending, Approved, Rejected
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'action_type': self.action_type,
            'payload': self.payload,
            'status': self.status,
            'reasoning': self.reasoning,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }
