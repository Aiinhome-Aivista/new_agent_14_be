from pydantic import BaseModel, model_validator
from typing import List, Any

class KPIInput(BaseModel):
    project_id: int
    variance: float
    risks: List[Any] = []
    forecast_confidence: int = 78

class KPIItem(BaseModel):
    metric_name: str
    metric_value: float
    trend: float = 0.0
    trend_label: str = "stable"

class KPIOutput(BaseModel):
    kpis: List[KPIItem] = []

    @model_validator(mode='before')
    @classmethod
    def normalize_kpis(cls, data):
        if isinstance(data, dict):
            if "kpis" not in data:
                items = []
                for k, v in data.items():
                    if isinstance(v, (int, float)):
                        items.append({"metric_name": str(k), "metric_value": float(v), "trend": 0.0, "trend_label": "stable"})
                data = {"kpis": items if items else [
                    {"metric_name": "Budget Variance", "metric_value": 0.0, "trend": 0.0, "trend_label": "Unknown"},
                    {"metric_name": "Forecast Confidence", "metric_value": 78.0, "trend": 0.0, "trend_label": "Unknown"}
                ]}
            elif isinstance(data.get("kpis"), list):
                normalized = []
                for item in data["kpis"]:
                    if isinstance(item, dict):
                        normalized.append({
                            "metric_name": item.get("metric_name") or item.get("title", "KPI"),
                            "metric_value": float(item.get("metric_value", 0.0) or 0.0),
                            "trend": float(item.get("trend", 0.0) or 0.0),
                            "trend_label": str(item.get("trend_label") or item.get("trendLabel") or "stable")
                        })
                data["kpis"] = normalized
        return data
