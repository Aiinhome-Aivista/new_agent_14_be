from abc import ABC, abstractmethod
from typing import Any, Dict
import logging

from memory.episodic import EpisodicMemory

logger = logging.getLogger(__name__)

class BaseAgent(ABC):
    """
    Shared Observe → Reason → Plan → Act → Evaluate → Update-Memory base class.
    """
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.session_id = None
        self.max_iterations = 5

    def run(self, input_data: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """
        Main control loop execution.
        """
        self.session_id = session_id
        logger.info(f"[{self.agent_id}] Starting run for session {session_id}")
        
        # Initialize memory
        EpisodicMemory.add_event(self.agent_id, self.session_id, "start", "Agent started run", metadata={"input": input_data})
        
        context = self.observe(input_data)
        
        iteration = 0
        final_result = None
        
        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"[{self.agent_id}] Iteration {iteration}")
            
            reasoning = self.reason(context)
            plan = self.plan(reasoning)
            action_result = self.act(plan)
            
            evaluation = self.evaluate(action_result)
            
            if evaluation.get("is_complete", False):
                final_result = action_result
                logger.info(f"[{self.agent_id}] Task complete.")
                break
            else:
                # Update context for next iteration based on evaluation
                context.update({"previous_evaluation": evaluation, "previous_result": action_result})
                
        if final_result is None:
            logger.warning(f"[{self.agent_id}] Reached max iterations ({self.max_iterations}) without completion.")
            final_result = {"error": "Max iterations reached", "partial_result": action_result}
            
        self.update_memory(final_result)
        return final_result

    @abstractmethod
    def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def reason(self, context: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def plan(self, reasoning: Dict[str, Any]) -> Dict[str, Any]:
        pass
        
    @abstractmethod
    def act(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        pass
        
    @abstractmethod
    def evaluate(self, result: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def update_memory(self, final_result: Dict[str, Any]):
        EpisodicMemory.add_event(self.agent_id, self.session_id, "complete", "Agent completed run", metadata={"result": final_result})
