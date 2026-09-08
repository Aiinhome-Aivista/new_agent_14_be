from pydantic import BaseModel

class ReportingInput(BaseModel):
    project_id: int
    kpis: list
    financials: dict
    risks: list
    predictive: dict

class ReportingOutput(BaseModel):
    dashboard_data: dict
    narrative_summary: str
    report_file_path: str
