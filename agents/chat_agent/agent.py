import json
import uuid
from agents.chat_agent.schema import ChatInput, ChatOutput
from agents.chat_agent.prompts import get_chat_system_prompt
from guardrails.validation import validate_input, validate_output
from rag.retriever import RAGRetriever
from llm.llm_client import llm
from memory.episodic import EpisodicMemory

class ChatAgent:
    def __init__(self, agent_id="chat_agent"):
        self.agent_id = agent_id
        self.retriever = RAGRetriever()

    @validate_input(ChatInput)
    @validate_output(ChatOutput)
    def execute(self, inputs: dict) -> dict:
        session_id = str(uuid.uuid4())
        EpisodicMemory.add_event(self.agent_id, session_id, "action", "Started chat query processing")
        
        query = inputs.get("query")
        
        # RAG context
        context_docs = self.retriever.retrieve(query)
        context = "\n".join([doc.get('content', '') for doc in context_docs])
        
        prompt = f"Context:\n{context}\n\nUser Query: {query}\n\nReturn JSON ONLY with a 'response' field."
        
        response = llm.generate(prompt, system=get_chat_system_prompt(), format="json")
        
        try:
            parsed = json.loads(response)
            return parsed
        except Exception:
            return {"response": response}
