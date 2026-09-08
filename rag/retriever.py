from typing import Any, Dict, List
from memory.semantic import semantic_memory

class RAGRetriever:
    """
    Retrieves context from ChromaDB based on user queries.
    """
    def __init__(self, collection_name: str = "program_knowledge"):
        self.collection_name = collection_name
        
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieves the top-k most relevant chunks from semantic memory.
        """
        results = semantic_memory.search(self.collection_name, query, n_results=top_k)
        
        # Format results for the agent
        retrieved_context = []
        if results and "documents" in results and results["documents"]:
            for i in range(len(results["documents"][0])):
                retrieved_context.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {}
                })
        return retrieved_context

# Example usage function
def get_program_context(query: str) -> str:
    retriever = RAGRetriever()
    results = retriever.retrieve(query)
    
    context_str = ""
    for r in results:
        context_str += f"- [{r.get('metadata', {}).get('source', 'unknown')}] {r['content']}\n"
        
    return context_str
