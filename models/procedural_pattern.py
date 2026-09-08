from sqlalchemy import Column, Integer, String, Text, JSON
from db import Base

class ProceduralPattern(Base):
    """
    Procedural memory table for learned workflow patterns.
    """
    __tablename__ = 'procedural_patterns'

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    steps_json = Column(JSON, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'pattern_name': self.pattern_name,
            'description': self.description,
            'steps': self.steps_json
        }
