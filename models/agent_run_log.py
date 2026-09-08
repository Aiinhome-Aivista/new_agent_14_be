from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from datetime import datetime, timezone
from db import Base

class AgentRunLog(Base):
    """
    Observability table for tracking agent executions.
    """
    __tablename__ = 'agent_run_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), nullable=False)
    session_id = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False) # Success, Error
    latency_ms = Column(Float, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'session_id': self.session_id,
            'status': self.status,
            'latency_ms': self.latency_ms,
            'tokens_used': self.tokens_used,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
