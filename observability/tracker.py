import db
from models.agent_run_log import AgentRunLog
from observability.logger import app_logger

class AgentTracker:
    @staticmethod
    def log_run(agent_id: str, session_id: str, status: str, latency_ms: float = None, tokens_used: int = None, error_message: str = None):
        """
        Records agent execution metrics to MySQL.
        """
        try:
            log_entry = AgentRunLog(
                agent_id=agent_id,
                session_id=session_id,
                status=status,
                latency_ms=latency_ms,
                tokens_used=tokens_used,
                error_message=error_message
            )
            db.db_session.add(log_entry)
            db.db_session.commit()
            app_logger.info(f"Agent run logged for {agent_id} (status: {status})")
        except Exception as e:
            app_logger.error(f"Failed to log agent run: {str(e)}")
            db.db_session.rollback()
