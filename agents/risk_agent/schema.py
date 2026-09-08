from pydantic import BaseModel, Field
from typing import List, Optional

class RiskIssue(BaseModel):
    id: str = Field(..., description="Unique identifier for the risk/issue")
    title: str = Field(..., description="Short title of the risk/issue")
    description: str = Field(..., description="Detailed description of the risk/issue")
    severity: str = Field(..., description="Severity level: Low, Medium, High, Critical")
    status: str = Field(..., description="Current status: Open, Mitigated, Closed")
    mitigation_plan: Optional[str] = Field(None, description="Proposed or active mitigation steps")

class RiskAgentInput(BaseModel):
    project_id: str = Field(..., description="The project identifier")
    context_data: str = Field(..., description="Raw text data from MOMs, reports, etc.")
    current_risks: List[RiskIssue] = Field(default_factory=list, description="Existing known risks")

class RiskAgentOutput(BaseModel):
    detected_risks: List[RiskIssue] = Field(..., description="Newly detected or updated risks")
    escalations: List[str] = Field(..., description="Items requiring immediate management escalation")
    blockers: List[str] = Field(..., description="Critical blockers stopping progress")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in the assessment (0-1)")
