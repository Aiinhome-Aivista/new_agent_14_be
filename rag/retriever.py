from typing import Any, Dict, List
from memory.semantic import semantic_memory

class RAGRetriever:
    """
    Retrieves context from ChromaDB based on user queries.
    """
    def __init__(self, collection_name: str = "program_knowledge"):
        self.collection_name = collection_name
        
    def retrieve(self, query: str, top_k: int = 5, project_id: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves the top-k most relevant chunks from semantic memory with cosine similarity scoring
        and optional partition filtering by project_id.
        """
        where = None
        if project_id and str(project_id).lower() not in ("all", "*", "none"):
            where = {"project_id": str(project_id)}

        results = semantic_memory.search(self.collection_name, query, n_results=top_k, where=where)
        
        # Format results for the agent and frontend
        retrieved_context = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            ids = results["ids"][0] if "ids" in results and results["ids"] else []
            metas = results["metadatas"][0] if "metadatas" in results and results["metadatas"] else []
            distances = results.get("distances", [[]])[0] if results.get("distances") else []

            for i in range(len(docs)):
                dist = distances[i] if i < len(distances) else 0.5
                # Industry standard smooth similarity conversion from L2/cosine distance
                sim_pct = round(max(0.0, min(1.0, 1.0 / (1.0 + (float(dist) * 0.6)))) * 100, 1)

                meta = metas[i] if i < len(metas) and metas[i] else {}
                retrieved_context.append({
                    "id": ids[i] if i < len(ids) else f"chunk_{i}",
                    "content": docs[i],
                    "metadata": meta,
                    "similarity": sim_pct,
                    "score": f"{sim_pct}%",
                    "source": meta.get("filename") or meta.get("source") or "Document"
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
