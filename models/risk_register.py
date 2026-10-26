from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime, timezone
from db import Base

class RiskRegister(Base):
    __tablename__ = 'risk_register'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    risk_id = Column(String(50), nullable=False) # e.g. R-102
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String(50), nullable=False) # Critical, High, Medium, Low
    status = Column(String(50), nullable=False) # Open, Mitigated, Closed
    owner = Column(String(100), default='Unassigned', nullable=True)
    mitigation_plan = Column(Text, nullable=True)
    jira_issue_key = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def financial_impact(self):
        """Dynamically parses and extracts dollar financial impact from description, mitigation, or title."""
        import re
        text = f"{self.description or ''} {self.mitigation_plan or ''} {self.title or ''}"
        m = re.search(r'\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|\d+(?:\.\d+)?)\s*([KkMm])?', text)
        if m:
            val_str = m.group(1).replace(',', '')
            try:
                val = float(val_str)
                mult = m.group(2)
                if mult:
                    if mult.lower() == 'k': val *= 1000
                    elif mult.lower() == 'm': val *= 1000000
                return val
            except Exception:
                pass
        return 0.0

    @property
    def financial_exposure(self):
        return self.financial_impact

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'risk_id': self.risk_id,
            'title': self.title,
            'description': self.description,
            'severity': self.severity,
            'status': self.status,
            'owner': self.owner or 'Unassigned',
            'mitigation_plan': self.mitigation_plan,
            'jira_issue_key': self.jira_issue_key,
            'financial_impact': self.financial_impact,
            'financial_exposure': self.financial_exposure,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

