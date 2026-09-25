import json
import uuid
from agents.predictive_agent.schema import PredictiveInput, PredictiveOutput
from agents.predictive_agent.prompts import get_predictive_system_prompt
from guardrails.validation import validate_input, validate_output
from llm.llm_client import llm
from memory.episodic import EpisodicMemory

class PredictiveAgent:
    def __init__(self, agent_id="predictive_agent"):
        self.agent_id = agent_id

    @validate_input(PredictiveInput)
    @validate_output(PredictiveOutput)
    def execute(self, inputs: dict) -> dict:
        session_id = str(uuid.uuid4())
        EpisodicMemory.add_event(self.agent_id, session_id, "action", "Started predictive forecasting")
        
        doc_context = (inputs.get('document_context') or '').strip()
        doc_section = f"\n- Grounding Ingested Document Context (SOW, Scope, SLAs, Clauses):\n{doc_context}\n" if doc_context else ""

        reflexion_prompt = f"""[Reflexion Predictive Self-Critique Loop]
Initial State:
- Current Financial Variance: {inputs.get('current_variance')}
- Active Risk Matrix: {json.dumps(inputs.get('risks'))}
- Project Status: {inputs.get('project_status')}{doc_section}

Phase 1 (Initial Projection): Formulate baseline cost variance trajectory based on linear burn rate.
Phase 2 (Self-Critique): Challenge the baseline against active high-severity risks, vendor lead times, and compounding delay risks.
Phase 3 (Refined Convergence): Output final converged forecasted_variance (float), confidence_score (integer 0-100), and forecast_narrative explaining the critique adjustments.
Phase 4 (Predictive Threat Projection): Grounded specifically in the project context and attached documents/SLAs/milestones, identify and generate all realistic EMERGING / POTENTIAL FUTURE RISKS that could materialize in subsequent delivery cycles and exacerbate budget or schedule variance. The count of threats must be entirely organic and flexible based purely on what the documents and project reality warrant (do not enforce any artificial minimum or maximum limit; generate as many genuine threats as exist in the project). Avoid generic textbook risks; strictly tie them to the specific scope, technologies, contractual SLAs, milestones, or vendor dependencies mentioned in the project documents. For each projected risk, specify:
  - "threat_title": clear concise risk description referencing project-specific terms or deliverables
  - "category": e.g. "Vendor / Technical", "Infrastructure", "Staffing", or "Regulatory"
  - "probability_pct": integer 1-100 likelihood of occurrence
  - "severity": "Critical", "High", or "Medium"
  - "financial_exposure": estimated dollar cost impact as a float
  - "preventive_action": actionable recommendation to mitigate this risk before it occurs

Return JSON ONLY matching schema:
{{"forecasted_variance": float, "confidence_score": int, "forecast_narrative": str, "projected_risks": [{{"threat_title": str, "category": str, "probability_pct": int, "severity": str, "financial_exposure": float, "preventive_action": str}}]}}
"""
        
        try:
            response = llm.generate(reflexion_prompt, system=get_predictive_system_prompt(), format="json", tier="high")
            parsed = json.loads(response)
            parsed["ai_processing_status"] = "success"
            if "projected_risks" not in parsed or not isinstance(parsed["projected_risks"], list):
                parsed["projected_risks"] = []
            return parsed
        except Exception as e:
            raise RuntimeError(f"Predictive Reflexion loop failed to converge: {str(e)}")
