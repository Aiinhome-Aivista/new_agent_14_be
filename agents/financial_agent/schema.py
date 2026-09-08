from pydantic import BaseModel

class FinancialInput(BaseModel):
    project_id: int
    period: str
    budget_planned: float
    budget_actual: float

class FinancialOutput(BaseModel):
    variance: float
    variance_percentage: float
    status: str # e.g., "On Track", "Over Budget", "Under Budget"
    analysis: str
