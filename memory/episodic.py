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
        from sqlalchemy.exc import OperationalError, DBAPIError

        for attempt in range(2):
            try:
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
            except (OperationalError, DBAPIError):
                try:
                    db.db_session.rollback()
                except Exception:
                    pass
                try:
                    db.db_session.remove()
                except Exception:
                    pass
                if attempt == 0:
                    continue
                return None
            except Exception:
                try:
                    db.db_session.rollback()
                except Exception:
                    pass
                return None

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
