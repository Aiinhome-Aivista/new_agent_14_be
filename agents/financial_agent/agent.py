import json
import uuid
from agents.financial_agent.schema import FinancialInput, FinancialOutput
from agents.financial_agent.prompts import get_financial_system_prompt
from guardrails.validation import validate_input, validate_output
from llm.llm_client import llm
from memory.episodic import EpisodicMemory

class FinancialAgent:
    def __init__(self, agent_id="financial_agent"):
        self.agent_id = agent_id

    @validate_input(FinancialInput)
    @validate_output(FinancialOutput)
    def execute(self, inputs: dict) -> dict:
        session_id = str(uuid.uuid4())
        EpisodicMemory.add_event(self.agent_id, session_id, "action", "Started financial calculation")
        
        planned = inputs.get("budget_planned", 0.0)
        actual = inputs.get("budget_actual", 0.0)
        
        variance = planned - actual
        variance_percentage = (variance / planned * 100) if planned > 0 else 0
        
        status = "On Track"
        if variance < 0:
            status = "Over Budget"
        elif variance > 0:
            status = "Under Budget"

        prompt = f"""
        Planned: {planned}
        Actual: {actual}
        Variance: {variance} ({variance_percentage}%)
        Status: {status}
        
        Provide the 'analysis' field in JSON format along with the exact variance, variance_percentage, and status.
        """
        
        response = llm.generate(prompt, system=get_financial_system_prompt(), format="json")
        
        try:
            parsed = json.loads(response)
            # Ensure calculations are correct regardless of LLM
            parsed['variance'] = variance
            parsed['variance_percentage'] = variance_percentage
            parsed['status'] = status
            return parsed
        except Exception:
            return {
                "variance": variance,
                "variance_percentage": variance_percentage,
                "status": status,
                "analysis": f"Budget is {status.lower()} with a variance of {variance}."
            }
