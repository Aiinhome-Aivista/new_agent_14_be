import json
import logging
from rag.retriever import RAGRetriever
from agents.chat_agent.prompts import get_chat_system_prompt
from llm.llm_client import llm

logger = logging.getLogger(__name__)

class ChatService:
    @staticmethod
    def stream_chat(query: str):
        """
        Server-Sent Events (SSE) generator streaming tokens directly via llm.stream_generate().
        Retrieves relevant RAG context from ChromaDB before streaming.
        """
        try:
            try:
                retriever = RAGRetriever()
                context_docs = retriever.retrieve(query)
                context = "\n".join([doc.get('content', '') for doc in context_docs if doc.get('content')])
            except Exception as rag_err:
                logger.warning(f"RAG retrieval error in stream_chat: {rag_err}")
                context = ""

            prompt = f"Context:\n{context}\n\nUser Query: {query}\n\nProvide a helpful, precise response based on the context and project data."
            system = get_chat_system_prompt()

            for token in llm.stream_generate(prompt, system=system):
                yield f"data: {json.dumps({'token': token})}\n\n"

        except GeneratorExit:
            return
        except Exception as e:
            logger.error(f"Error in stream_chat: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
        yield "data: [DONE]\n\n"
