import chromadb
from chromadb.config import Settings
import os

# Default to a local persistent directory
CHROMA_DATA_DIR = os.path.join(os.getcwd(), 'chroma_data')

class SemanticMemory:
    """
    Manages semantic memory using ChromaDB for RAG (MOMs, reports, program knowledge embeddings).
    """
    def __init__(self, persist_directory: str = CHROMA_DATA_DIR):
        self.client = chromadb.PersistentClient(path=persist_directory)
        
    def get_or_create_collection(self, collection_name: str):
        """
        Retrieves or creates a ChromaDB collection.
        """
        return self.client.get_or_create_collection(name=collection_name)
        
    def add_documents(self, collection_name: str, documents: list[str], metadatas: list[dict], ids: list[str]):
        """
        Adds text documents to semantic memory.
        Chroma uses an internal embedding function by default (all-MiniLM-L6-v2),
        or we could override it to use the custom LLM if it has an embedding endpoint.
        """
        collection = self.get_or_create_collection(collection_name)
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        
    def search(self, collection_name: str, query: str, n_results: int = 5, where: dict = None):
        """
        Searches semantic memory for relevant context with metadata partition filtering.
        """
        collection = self.get_or_create_collection(collection_name)
        kwargs = {
            "query_texts": [query],
            "n_results": n_results
        }
        if where:
            kwargs["where"] = where
        results = collection.query(**kwargs)
        return results

    def get(self, collection_name: str, where: dict = None):
        """
        Retrieves documents from collection with optional metadata partition filter.
        """
        collection = self.get_or_create_collection(collection_name)
        if where:
            return collection.get(where=where)
        return collection.get()

# Global instance
semantic_memory = SemanticMemory()
