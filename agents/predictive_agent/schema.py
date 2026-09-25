from pydantic import BaseModel
from typing import List

class PredictiveInput(BaseModel):
    current_variance: float
    risks: List[dict]
    project_status: str
    document_context: str = ""

class PredictiveOutput(BaseModel):
    forecasted_variance: float
    confidence_score: int # 0-100
    forecast_narrative: str
    projected_risks: List[dict] = []
