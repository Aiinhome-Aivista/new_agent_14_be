from flask import Blueprint, jsonify, request
from datetime import datetime, timezone
import re
import os
from memory.semantic import semantic_memory
from rag.retriever import RAGRetriever

knowledge_bp = Blueprint('knowledge', __name__)

def extract_meta_from_text(text: str, source: str):
    """
    Extracts high-fidelity NLP metadata (title, category tags, preview) from raw chunk texts.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    first_line = lines[0] if lines else source
    clean_title = re.sub(r'^[#*\-\d.\s]+', '', first_line).strip()
    if len(clean_title) > 90:
        clean_title = clean_title[:87] + "..."
    if not clean_title or len(clean_title) < 4:
        clean_title = os.path.basename(source)

    # NLP keyword tag extraction
    tags = []
    text_lower = text.lower()
    if any(k in text_lower for k in ["architecture", "microservice", "gateway", "database", "infrastructure", "latency"]):
        tags.append("Architecture")
    if any(k in text_lower for k in ["budget", "planned", "actual", "financial", "variance", "cost"]):
        tags.append("Financials")
    if any(k in text_lower for k in ["iso", "compliance", "security", "jwt", "oauth", "pci", "audit"]):
        tags.append("Security")
    if any(k in text_lower for k in ["mom", "meeting", "status report", "minutes", "sprint"]):
        tags.append("Governance")
    if any(k in text_lower for k in ["risk", "blocker", "mitigation", "outage"]):
        tags.append("Risk Profile")
    if not tags:
        tags.append("Documentation")

    # Clean preview terminating at a word/sentence boundary
    preview_clean = " ".join(text.split())
    if len(preview_clean) > 220:
        cutoff = preview_clean[:220].rfind(" ")
        preview_clean = preview_clean[:cutoff] + "..." if cutoff > 100 else preview_clean[:220] + "..."

    return clean_title, tags, preview_clean

@knowledge_bp.route('', methods=['GET'])
@knowledge_bp.route('/', methods=['GET'])
def get_knowledge():
    try:
        selected_project = request.args.get('project_id')
        if selected_project and selected_project.upper() in ('ALL', '*', 'NONE', ''):
            selected_project = None

        collection = semantic_memory.get_or_create_collection("program_knowledge")
        
        # Partition filter at ChromaDB level if selected
        if selected_project:
            data = collection.get(where={"project_id": str(selected_project)})
        else:
            data = collection.get()
        
        # Compute partition distribution across collection
        full_data = collection.get()
        all_metas = full_data.get("metadatas", []) or []
        
        partition_counts = {}
        for m in all_metas:
            pid = str(m.get("project_id", "1"))
            partition_counts[pid] = partition_counts.get(pid, 0) + 1

        # Query available projects in database
        import db
        from models.project import Project
        db_projects = []
        try:
            projs = db.db_session.query(Project).all()
            for p in projs:
                db_projects.append({
                    "id": str(p.id),
                    "name": p.name,
                    "jira_key": p.jira_key,
                    "chunk_count": partition_counts.get(str(p.id), 0)
                })
        except Exception:
            pass

        documents_by_source = {}
        ids = data.get("ids", [])
        metadatas = data.get("metadatas", [])
        contents = data.get("documents", [])
        
        for i in range(len(ids)):
            meta = metadatas[i] if metadatas and i < len(metadatas) and metadatas[i] else {}
            source = meta.get("filename") or meta.get("source") or "Document"
            chunk_text = contents[i] if contents and i < len(contents) else ""
            
            if source not in documents_by_source:
                title, tags, preview = extract_meta_from_text(chunk_text, source)
                
                # Format timestamp
                raw_ts = meta.get("timestamp")
                formatted_time = "Recent"
                if raw_ts:
                    try:
                        ts_int = int(raw_ts)
                        dt = datetime.fromtimestamp(ts_int, timezone.utc)
                        formatted_time = dt.strftime("%d %b %Y, %I:%M %p")
                    except Exception:
                        formatted_time = "Indexed"

                ext = os.path.splitext(source)[1].upper().replace('.', '') or 'TXT'
                p_id = str(meta.get("project_id", "1"))

                documents_by_source[source] = {
                    "source": source,
                    "filename": source,
                    "title": meta.get("title") or title,
                    "file_ext": ext,
                    "tags": tags,
                    "project_id": p_id,
                    "chunk_count": 0,
                    "timestamp": formatted_time,
                    "preview": preview,
                    "embedding_info": "384-dim (all-MiniLM-L6-v2) | ChromaDB HNSW",
                    "partition_key": f"project_id:{p_id}"
                }
            documents_by_source[source]["chunk_count"] += 1
            
        doc_list = list(documents_by_source.values())
        return jsonify({
            "documents": doc_list,
            "total_documents": len(doc_list),
            "total_chunks": len(ids),
            "selected_partition": selected_project or "ALL",
            "partitions": partition_counts,
            "projects": db_projects,
            "vector_index": "ChromaDB Persistent Vault",
            "embedding_model": "all-MiniLM-L6-v2 (384-dim Dense Vectors)"
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
    project_id = data.get('project_id')
    if not query:
        return jsonify({"results": []})
        
    try:
        retriever = RAGRetriever(collection_name="program_knowledge")
        results = retriever.retrieve(query, top_k=6, project_id=project_id)
        return jsonify({
            "results": results, 
            "query": query,
            "partition": project_id or "ALL",
            "total_matches": len(results)
        })
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 500
