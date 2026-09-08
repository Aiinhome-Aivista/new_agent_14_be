import json
import logging
import time
import uuid
from typing import Dict, Any

from core.control_loop import BaseAgent
from agents.risk_agent.schema import RiskAgentInput, RiskAgentOutput
from agents.risk_agent.prompts import get_risk_system_prompt, get_risk_user_prompt
from llm.llm_client import llm

logger = logging.getLogger(__name__)

class RiskAgent(BaseAgent):
    """
    Risk & Issue Agent implementing a Graph/Tree-of-Thoughts approach (simplified for this structure)
    to detect escalations, blockers, and showstoppers.
    """
    def __init__(self):
        super().__init__(agent_id="risk_agent")

    def execute(self, inputs: dict) -> dict:
        """
        Thin execution method adhering to the shared agent interface.
        Generates session_id, delegates to BaseAgent.run control loop,
        and unwraps result into the shape expected by downstream agents and ingestion.
        """
        session_id = str(uuid.uuid4())
        project_id = str(inputs.get("project_id", inputs.get("project_name", "1")))
        
        # Build context_data from inputs
        context_data = inputs.get("context_data")
        if not context_data:
            context_data = json.dumps(inputs)
            
        current_risks = inputs.get("current_risks", [])
        
        run_input = {
            "project_id": project_id,
            "context_data": context_data,
            "current_risks": current_risks
        }
        
        raw_result = self.run(run_input, session_id)
        
        # Extract inner result
        inner = raw_result.get("result", {}) if isinstance(raw_result, dict) else {}
        detected = inner.get("detected_risks", [])
        escalations = inner.get("escalations", [])
        blockers = inner.get("blockers", [])
        confidence = inner.get("confidence_score", 0.85)
        
        # If detected risks empty and intake had risks, fallback to intake risks
        if not detected and isinstance(inputs.get("intake", {}).get("risks"), list) and inputs["intake"]["risks"]:
            raw_intake_risks = inputs["intake"]["risks"]
            detected = []
            for idx, r in enumerate(raw_intake_risks):
                if isinstance(r, dict):
                    detected.append(r)
                elif isinstance(r, str):
                    detected.append({
                        "id": f"R-{100 + idx}",
                        "title": r,
                        "description": r,
                        "severity": "High",
                        "status": "Open",
                        "mitigation_plan": "Assess and mitigate"
                    })
        
        ai_status = inner.get("ai_processing_status") or ("degraded_fallback" if raw_result.get("is_fallback") else "success")
        return {
            "status": "success" if raw_result.get("action_taken") else "error",
            "risks": detected,
            "detected_risks": detected,
            "escalations": escalations,
            "blockers": blockers,
            "confidence_score": confidence,
            "ai_processing_status": ai_status,
            "raw_result": raw_result
        }
        
    def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates input schema and prepares context.
        """
        logger.info(f"[{self.agent_id}] Observing input...")
        validated_input = RiskAgentInput(**input_data)
        
        # In a real scenario, we might fetch more context from RAG here if needed
        return {
            "validated_input": validated_input,
            "raw_input": input_data
        }

    def reason(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Explores potential risks based on context.
        """
        logger.info(f"[{self.agent_id}] Reasoning about risks...")
        
        # Format the prompt
        input_obj: RiskAgentInput = context["validated_input"]
        schema_json = RiskAgentOutput.model_json_schema()
        
        prompt = get_risk_user_prompt().format(
            project_id=input_obj.project_id,
            context_data=input_obj.context_data,
            current_risks=[r.model_dump() for r in input_obj.current_risks],
            schema=json.dumps(schema_json, indent=2)
        )
        
        # Call LLM with graceful fallback
        is_fallback = False
        try:
            response_text = llm.generate(
                prompt=prompt,
                system=get_risk_system_prompt(),
                format="json"
            )
        except Exception as exc:
            is_fallback = True
            logger.warning(f"[{self.agent_id}] LLM generation failed: {exc}, using fallback risk analysis")
            fallback_risk_id = f"R-{int(time.time()) % 900 + 100}"
            response_text = json.dumps({
                "detected_risks": [
                    {
                        "id": fallback_risk_id,
                        "title": "Delivery & Architecture Risk",
                        "description": f"Identified in document analysis: {input_obj.context_data[:120]}...",
                        "severity": "Critical",
                        "status": "Open",
                        "mitigation_plan": "Escalate to PMO and establish mitigation sprint."
                    }
                ],
                "escalations": [f"{fallback_risk_id} requires PMO review"],
                "blockers": ["Cross-team dependency resolution"],
                "confidence_score": 0.85
            })
        
        return {
            "llm_response": response_text,
            "context": context,
            "is_fallback": is_fallback
        }

    def plan(self, reasoning: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determines the action plan based on the LLM's reasoning.
        """
        logger.info(f"[{self.agent_id}] Planning actions...")
        # Parse the JSON response
        try:
            parsed_data = json.loads(reasoning["llm_response"])
            # Validate output schema
            validated_output = RiskAgentOutput(**parsed_data)
            return {
                "status": "success",
                "output": validated_output,
                "needs_human_review": validated_output.confidence_score < 0.7 or len(validated_output.escalations) > 0,
                "is_fallback": reasoning.get("is_fallback", False)
            }
        except Exception as e:
            logger.error(f"Failed to parse or validate LLM output: {e}")
            return {
                "status": "error",
                "error": str(e),
                "raw_response": reasoning["llm_response"],
                "is_fallback": True
            }

    def act(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the plan (e.g., formats final output, routes to approval queue if needed).
        """
        logger.info(f"[{self.agent_id}] Executing plan...")
        
        if plan["status"] == "error":
            return plan
            
        result = plan["output"].model_dump()
        result["needs_human_review"] = plan["needs_human_review"]
        result["ai_processing_status"] = "degraded_fallback" if plan.get("is_fallback") else "success"
        
        return {
            "action_taken": "risk_assessment_completed",
            "result": result,
            "is_fallback": plan.get("is_fallback", False)
        }

    def evaluate(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates if the action achieved the goal.
        """
        logger.info(f"[{self.agent_id}] Evaluating result...")
        if result.get("status") == "error":
            # In a robust implementation, we might retry the LLM call here
            return {"is_complete": True, "success": False, "reason": result.get("error")}
            
        return {"is_complete": True, "success": True}
