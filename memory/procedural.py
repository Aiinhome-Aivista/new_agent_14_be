from models.procedural_pattern import ProceduralPattern
import db

class ProceduralMemory:
    """
    Manages learned workflow patterns for agents using MySQL.
    """
    
    @staticmethod
    def get_pattern(pattern_name: str):
        """
        Retrieves a learned workflow pattern by name.
        """
        pattern = db.db_session.query(ProceduralPattern).filter_by(pattern_name=pattern_name).first()
        if pattern:
            return pattern.to_dict()
        return None

    @staticmethod
    def save_pattern(pattern_name: str, description: str, steps: list):
        """
        Saves or updates a workflow pattern.
        """
        pattern = db.db_session.query(ProceduralPattern).filter_by(pattern_name=pattern_name).first()
        if not pattern:
            pattern = ProceduralPattern(pattern_name=pattern_name)
            db.db_session.add(pattern)
            
        pattern.description = description
        pattern.steps_json = steps
        db.db_session.commit()
        return pattern.to_dict()
