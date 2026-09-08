import json
import uuid
from agents.kpi_agent.schema import KPIInput, KPIOutput
from agents.kpi_agent.prompts import get_kpi_system_prompt
from guardrails.validation import validate_input, validate_output
from llm.llm_client import llm
from memory.episodic import EpisodicMemory

class KPIAgent:
    def __init__(self, agent_id="kpi_agent"):
        self.agent_id = agent_id

    @validate_input(KPIInput)
    @validate_output(KPIOutput)
    def execute(self, inputs: dict) -> dict:
        session_id = str(uuid.uuid4())
        EpisodicMemory.add_event(self.agent_id, session_id, "action", "Started KPI mapping")
        
        prompt = f"""
        Map the following to KPIs:
        Variance: {inputs.get('variance')}
        Risks: {len(inputs.get('risks', []))} total
        Forecast Confidence: {inputs.get('forecast_confidence')}
        
        Return JSON ONLY.
        """
        
        try:
            response = llm.generate(prompt, system=get_kpi_system_prompt(), format="json")
            parsed = json.loads(response)
            return parsed
        except Exception:
            return {
                "kpis": [
                    {"metric_name": "Budget Variance", "metric_value": float(inputs.get("variance", 0.0) or 0.0), "trend": 0.0, "trend_label": "stable"},
                    {"metric_name": "Forecast Confidence", "metric_value": float(inputs.get("forecast_confidence", 78) or 78), "trend": 0.0, "trend_label": "stable"}
                ]
            }
