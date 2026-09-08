from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime, timezone
from db import Base

class AgentEpisode(Base):
    """
    Episodic memory table (short-term event history) for agents.
    Replaces Redis.
    """
    __tablename__ = 'agent_episodes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), nullable=False)
    session_id = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    event_type = Column(String(50), nullable=False) # e.g., 'observation', 'thought', 'action', 'result'
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'session_id': self.session_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'event_type': self.event_type,
            'content': self.content,
            'metadata': self.metadata_json
        }
