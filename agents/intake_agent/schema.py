from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any

class IntakeInput(BaseModel):
    file_path: Optional[str] = Field(None, description="Path to the document to parse")
    intake: Optional[dict] = None
    project_id: Optional[Any] = 1

    @model_validator(mode='before')
    @classmethod
    def resolve_file_path(cls, data):
        if isinstance(data, dict):
            if not data.get('file_path') and 'intake' in data and isinstance(data['intake'], dict):
                data['file_path'] = data['intake'].get('file_path')
            if not data.get('project_id') and 'intake' in data and isinstance(data['intake'], dict):
                data['project_id'] = data['intake'].get('project_id', 1)
        return data

class ExtractedRisk(BaseModel):
    title: str
    description: Optional[str] = ""
    severity: Optional[str] = "Medium"

class IntakeOutput(BaseModel):
    project_name: str = Field(default="Alpha Migration Program", description="Name of the project")
    jira_key: Optional[str] = Field(default="PRJ-101", description="Jira key if mentioned")
    status: str = Field(default="Active")
    risks: List[ExtractedRisk] = []
    budget_planned: float = 0.0
    budget_actual: float = 0.0

    @model_validator(mode='before')
    @classmethod
    def normalize_output(cls, data):
        if isinstance(data, dict):
            if not data.get('jira_key'):
                data['jira_key'] = 'PRJ-101'
            if not data.get('project_name'):
                data['project_name'] = 'Alpha Migration Program'
            raw_risks = data.get('risks', [])
            normalized = []
            if isinstance(raw_risks, list):
                for r in raw_risks:
                    if isinstance(r, str):
                        normalized.append({"title": r, "description": r, "severity": "Medium"})
                    elif isinstance(r, dict):
                        normalized.append({
                            "title": r.get("title", "Identified Risk"),
                            "description": r.get("description") or r.get("title", "Risk identified"),
                            "severity": r.get("severity") or "Medium"
                        })
            data['risks'] = normalized
        return data

