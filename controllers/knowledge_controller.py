from flask import Blueprint, jsonify, request
from memory.semantic import semantic_memory
from rag.retriever import RAGRetriever

knowledge_bp = Blueprint('knowledge', __name__)

@knowledge_bp.route('', methods=['GET'])
@knowledge_bp.route('/', methods=['GET'])
def get_knowledge():
    try:
        collection = semantic_memory.get_or_create_collection("program_knowledge")
        data = collection.get()
        
        # Group chunks by document source
        documents_by_source = {}
        ids = data.get("ids", [])
        metadatas = data.get("metadatas", [])
        contents = data.get("documents", [])
        
        for i in range(len(ids)):
            meta = metadatas[i] if metadatas and i < len(metadatas) and metadatas[i] else {}
            source = meta.get("source", "Unknown Document")
            chunk_text = contents[i] if contents and i < len(contents) else ""
            
            if source not in documents_by_source:
                documents_by_source[source] = {
                    "source": source,
                    "project_id": meta.get("project_id", "1"),
                    "chunk_count": 0,
                    "timestamp": meta.get("timestamp"),
                    "preview": chunk_text[:200] if chunk_text else ""
                }
            documents_by_source[source]["chunk_count"] += 1
            
        doc_list = list(documents_by_source.values())
        return jsonify({
            "documents": doc_list,
            "total_documents": len(doc_list),
            "total_chunks": len(ids)
        })
    except Exception as e:
        return jsonify({
            "documents": [],
            "total_documents": 0,
            "total_chunks": 0,
            "error": str(e)
        })

@knowledge_bp.route('/search', methods=['POST'])
def search_knowledge():
    data = request.json or {}
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"results": []})
        
    try:
        retriever = RAGRetriever(collection_name="program_knowledge")
        results = retriever.retrieve(query, top_k=5)
        return jsonify({"results": results, "query": query})
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 500
