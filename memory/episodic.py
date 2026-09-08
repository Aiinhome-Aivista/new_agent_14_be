from sqlalchemy.orm import Session
from models.agent_episode import AgentEpisode
import db

class EpisodicMemory:
    """
    Manages short-term event history for agents using MySQL.
    Replaces traditional Redis/in-memory approaches.
    """
    
    @staticmethod
    def add_event(agent_id: str, session_id: str, event_type: str, content: str, metadata: dict = None):
        """
        Records an event in the agent's episode timeline.
        """
        episode = AgentEpisode(
            agent_id=agent_id,
            session_id=session_id,
            event_type=event_type,
            content=content,
            metadata_json=metadata
        )
        db.db_session.add(episode)
        db.db_session.commit()
        return episode.to_dict()

    @staticmethod
    def get_session_history(session_id: str, limit: int = 50):
        """
        Retrieves the recent history for a specific session.
        """
        episodes = db.db_session.query(AgentEpisode)\
            .filter(AgentEpisode.session_id == session_id)\
            .order_by(AgentEpisode.timestamp.desc())\
            .limit(limit)\
            .all()
            
        # Reverse to return chronologically
        return [ep.to_dict() for ep in reversed(episodes)]

    @staticmethod
    def clear_session(session_id: str):
        """
        Deletes history for a specific session.
        """
        db.db_session.query(AgentEpisode).filter(AgentEpisode.session_id == session_id).delete()
        db.db_session.commit()
