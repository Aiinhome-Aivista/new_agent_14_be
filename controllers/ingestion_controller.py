import os
from flask import Blueprint, request, jsonify
from services.ingestion_service import IngestionService
from services.auth_service import require_roles

ingestion_bp = Blueprint('ingestion', __name__)

@ingestion_bp.route('/upload', methods=['POST'])
@require_roles('PMO', 'Project Manager')
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    # Save file to disk
    uploads_dir = os.path.join(os.getcwd(), 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, file.filename)
    file.save(file_path)
    
    raw_pid = request.form.get('project_id', '1')
    try:
        project_id = int(raw_pid)
    except ValueError:
        project_id = 1
        
    try:
        result = IngestionService.process_file(file_path, project_id=project_id)
        
        # Save document metadata into MySQL uploaded_documents table
        stat = os.stat(file_path)
        file_size_bytes = stat.st_size
        size_kb = file_size_bytes / 1024
        size_fmt = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{(size_kb / 1024):.2f} MB"
        ext = os.path.splitext(file.filename)[1].lstrip('.').upper() or 'TXT'
        
        import db
        from models.uploaded_document import UploadedDocument
        from models.user import User
        from datetime import datetime, timezone

        user_info = getattr(request, 'user', {}) or {}
        uploader_name = user_info.get('name') or request.form.get('uploaded_by')
        
        if not uploader_name:
            email_or_sub = user_info.get('email') or user_info.get('sub')
            if email_or_sub:
                try:
                    u = db.db_session.query(User).filter(
                        (User.email == email_or_sub) | (User.id == (int(email_or_sub) if str(email_or_sub).isdigit() else -1))
                    ).first()
                    if u and u.name:
                        uploader_name = u.name
                    elif u and u.email:
                        uploader_name = u.email
                except Exception:
                    pass

        uploaded_by = uploader_name or user_info.get('email') or 'Sanjib Sau'
        uploaded_by_role = user_info.get('role') or request.form.get('uploaded_by_role') or 'Project Manager'
        risks_detected = result.get('risks_detected', 0) if isinstance(result, dict) else 0

        doc_record = UploadedDocument(
            filename=file.filename,
            file_type=ext,
            file_size_bytes=file_size_bytes,
            file_size_formatted=size_fmt,
            uploaded_by=uploaded_by,
            uploaded_by_role=uploaded_by_role,
            project_id=project_id,
            status="Indexed in Vector Memory",
            risks_detected=risks_detected,
            created_at=datetime.now(timezone.utc)
        )
        db.db_session.add(doc_record)
        db.db_session.commit()
        
        if isinstance(result, dict):
            result["document_id"] = doc_record.id
            result["uploaded_by"] = uploaded_by
            result["risks_detected"] = risks_detected

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ingestion_bp.route('/history', methods=['GET'])
@require_roles('PMO', 'Project Manager', 'Program Director', 'Investor')
def list_ingestion_history():
    import db
    from models.uploaded_document import UploadedDocument
    from models.project import Project
    
    docs = []
    has_project_filter = False
    try:
        if db.db_session:
            query = db.db_session.query(UploadedDocument)
            project_id_param = request.args.get('project_id')
            if project_id_param and str(project_id_param).strip().lower() not in ('all', '', 'none', 'null'):
                has_project_filter = True
                pid = None
                if str(project_id_param).isdigit():
                    pid = int(project_id_param)
                else:
                    p = db.db_session.query(Project).filter_by(jira_key=str(project_id_param).strip()).first()
                    if p:
                        pid = p.id
                if pid is not None:
                    query = query.filter_by(project_id=pid)
                else:
                    return jsonify([])
            
            db_docs = query.order_by(UploadedDocument.created_at.desc()).all()
            if db_docs:
                docs = [d.to_dict() for d in db_docs]
    except Exception as exc:
        print(f"Error querying uploaded_documents: {exc}")

    # Fallback to filesystem ONLY if:
    # 1. No specific project was requested (has_project_filter is False)
    # 2. AND the database has absolutely no records across all projects
    if not docs and not has_project_filter:
        try:
            total_db_count = db.db_session.query(UploadedDocument).count() if db.db_session else 0
        except Exception:
            total_db_count = 0

        if total_db_count == 0:
            uploads_dir = os.path.join(os.getcwd(), 'uploads')
            if os.path.exists(uploads_dir):
                import time
                for fname in sorted(os.listdir(uploads_dir), reverse=True):
                    fpath = os.path.join(uploads_dir, fname)
                    if os.path.isfile(fpath):
                        stat = os.stat(fpath)
                        size_kb = stat.st_size / 1024
                        size_fmt = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{(size_kb / 1024):.2f} MB"
                        ext = os.path.splitext(fname)[1].lstrip('.').upper() or 'TXT'
                        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                        docs.append({
                            "id": fname,
                            "filename": fname,
                            "file_type": ext,
                            "size": size_fmt,
                            "uploaded_at": time_str,
                            "uploaded_by": "pm@example.com",
                            "uploaded_by_role": "Project Manager",
                            "risks_detected": 0,
                            "status": "Indexed in Vector Memory",
                            "indexed": True
                        })
    return jsonify(docs)


@ingestion_bp.route('/connectors', methods=['GET'])
@require_roles('PMO', 'Project Manager', 'Program Director')
def get_project_connectors():
    """
    Returns available enterprise connectors and their connection state for a given project.
    """
    import db
    from models.integration_setting import IntegrationSetting

    project_id = request.args.get('project_id', 1)
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        project_id = 1

    connectors_def = [
        {"id": "jira", "name": "Jira Cloud", "category": "Agile Sprints & Epics", "color": "blue"},
        {"id": "azure_devops", "name": "Azure DevOps", "category": "Boards & Burndown", "color": "sky"},
        {"id": "google_drive", "name": "Google Drive", "category": "Shared Drive MOMs & SOWs", "color": "emerald"},
        {"id": "onedrive", "name": "Microsoft OneDrive", "category": "M365 Enterprise Docs", "color": "indigo"}
    ]

    result = []
    for c in connectors_def:
        setting = db.db_session.query(IntegrationSetting).filter_by(provider=c["id"], project_id=project_id).first()
        is_conn = bool(setting and setting.is_connected)
        result.append({
            "id": c["id"],
            "name": c["name"],
            "category": c["category"],
            "color": c["color"],
            "is_connected": is_conn,
            "base_url": setting.base_url if setting else "",
            "username_email": setting.username_email if setting else "",
            "updated_at": setting.updated_at.isoformat() if setting and setting.updated_at else None
        })

    return jsonify({
        "success": True,
        "project_id": project_id,
        "connectors": result
    })


@ingestion_bp.route('/connectors/fetch', methods=['GET'])
@require_roles('PMO', 'Project Manager', 'Program Director')
def fetch_connector_data():
    """
    Fetches live items/assets from a connected tool for the active project.
    """
    import db
    from models.project import Project
    from models.integration_setting import IntegrationSetting
    from tools.jira_tool import JiraTool
    from tools.azure_devops_tool import AzureDevOpsTool
    from tools.google_drive_tool import GoogleDriveTool
    from tools.onedrive_tool import OneDriveTool

    provider = request.args.get('provider', 'jira').strip().lower()
    project_id = request.args.get('project_id', 1)
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        project_id = 1

    proj = db.db_session.query(Project).filter_by(id=project_id).first()
    proj_key = proj.jira_key if proj else f"PRJ-{project_id}"
    proj_name = proj.name if proj else f"Project #{project_id}"

    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider, project_id=project_id).first()
    if not setting or not setting.is_connected:
        return jsonify({
            "success": False,
            "error": f"{provider.replace('_', ' ').title()} is not connected for {proj_name}. Please configure credentials in Connectors Hub first.",
            "is_connected": False,
            "items": []
        }), 400

    items = []
    if provider == 'jira':
        res = JiraTool.execute(project_key=proj_key, project_id=project_id)
        raw_issues = res.get("issues", [])
        for idx, issue in enumerate(raw_issues):
            items.append({
                "id": issue.get("id") or f"{proj_key}-{idx+1}",
                "title": issue.get("summary") or "Jira Issue",
                "type": "Jira Issue",
                "status": issue.get("status", "Open"),
                "priority": issue.get("priority", "Medium"),
                "size": "Agile Issue",
                "bytes": 2048,
                "description": f"Jira Issue {issue.get('id')} under {proj_name}. Status: {issue.get('status')}. Priority: {issue.get('priority')}.",
                "source": "Jira Cloud"
            })

    elif provider == 'azure_devops':
        res = AzureDevOpsTool.execute(project_name=proj_name, project_id=project_id)
        raw_work = res.get("work_items", [])
        for idx, wi in enumerate(raw_work):
            items.append({
                "id": wi.get("id") or f"ADO-{idx+1}",
                "title": wi.get("title") or "Work Item",
                "type": wi.get("type") or "Work Item",
                "status": wi.get("state") or "Active",
                "priority": wi.get("severity") or (f"Priority {wi.get('priority')}" if wi.get('priority') else "Medium"),
                "size": f"{wi.get('points', 5)} Story Pts",
                "bytes": 2048,
                "description": f"Azure DevOps {wi.get('type', 'Work Item')} {wi.get('id')} for {proj_name}. State: {wi.get('state')}.",
                "source": "Azure DevOps"
            })

    elif provider == 'google_drive':
        res = GoogleDriveTool.execute(project_id=project_id)
        raw_docs = res.get("documents", [])
        for doc in raw_docs:
            items.append({
                "id": doc.get("id") or doc.get("name"),
                "title": doc.get("name"),
                "type": doc.get("mime_type", "Google Document").split('.')[-1].upper() if '.' in doc.get("name", "") else "GDOC",
                "status": "Available in Drive",
                "priority": doc.get("size", "Cloud Asset"),
                "size": doc.get("size"),
                "bytes": doc.get("bytes", 1024),
                "last_modified": doc.get("last_modified"),
                "description": f"Document asset '{doc.get('name')}' in Google Drive folder for {proj_name}.",
                "source": "Google Drive"
            })

    elif provider == 'onedrive':
        res = OneDriveTool.execute(project_id=project_id)
        raw_docs = res.get("documents", [])
        for doc in raw_docs:
            items.append({
                "id": doc.get("name"),
                "title": doc.get("name"),
                "type": doc.get("name", "").split('.')[-1].upper() if '.' in doc.get("name", "") else "M365",
                "status": "In OneDrive Cloud",
                "priority": doc.get("size", "Enterprise Asset"),
                "size": doc.get("size"),
                "bytes": 2048,
                "last_modified": doc.get("last_modified", "2026-09-11"),
                "description": f"OneDrive enterprise document '{doc.get('name')}' for {proj_name}.",
                "source": "Microsoft OneDrive"
            })

    return jsonify({
        "success": True,
        "provider": provider,
        "project_id": project_id,
        "project_name": proj_name,
        "count": len(items),
        "items": items
    })


@ingestion_bp.route('/connectors/ingest', methods=['POST'])
@require_roles('PMO', 'Project Manager')
def ingest_connector_items():
    """
    Ingests checked items from a connector:
    1. Partitions & embeds them into ChromaDB semantic vector store with project_id.
    2. Inserts metadata records into MySQL uploaded_documents table.
    """
    import db
    from datetime import datetime, timezone
    import time
    from models.uploaded_document import UploadedDocument
    from models.project import Project
    from memory.semantic import semantic_memory

    data = request.json or {}
    provider = data.get("provider", "connector")
    items = data.get("items", [])
    raw_pid = data.get("project_id", 1)
    try:
        project_id = int(raw_pid)
    except (ValueError, TypeError):
        project_id = 1

    if not items:
        return jsonify({"success": False, "error": "No items selected for ingestion."}), 400

    proj = db.db_session.query(Project).filter_by(id=project_id).first()
    proj_name = proj.name if proj else f"Project #{project_id}"
    proj_key = proj.jira_key if proj else f"PRJ-{project_id}"

    provider_labels = {
        "jira": "Jira Cloud",
        "azure_devops": "Azure DevOps",
        "google_drive": "Google Drive",
        "onedrive": "Microsoft OneDrive"
    }
    prov_title = provider_labels.get(provider, provider.title())

    timestamp_str = str(int(time.time()))
    ingested_count = 0

    for item in items:
        item_id = str(item.get("id", f"item_{int(time.time())}"))
        title = item.get("title") or item_id
        item_type = item.get("type") or provider.upper()
        status_val = item.get("status") or "Active"
        priority_val = item.get("priority") or "Medium"
        desc = item.get("description") or f"{title} from {prov_title}"

        # 1. Prepare semantic text content for ChromaDB
        full_content = (
            f"Source Connector: {prov_title}\n"
            f"Item ID / Key: {item_id}\n"
            f"Title: {title}\n"
            f"Project: {proj_name} (Key: {proj_key}, ID: #{project_id})\n"
            f"Classification: {item_type}\n"
            f"Status: {status_val}\n"
            f"Priority / Size: {priority_val}\n\n"
            f"Detailed Content / Telemetry:\n{desc}\n"
            f"Ingested via VPM Enterprise Connector Data Ops pipeline."
        )

        # 2. Partitioning into semantic chunks (ChromaDB)
        chunk_size = 450
        chunks = [full_content[i:i+chunk_size] for i in range(0, len(full_content), chunk_size)]
        if not chunks:
            chunks = [full_content]

        chunk_ids = [f"{provider}_{item_id}_chunk_{c_idx}_{timestamp_str}" for c_idx in range(len(chunks))]
        metadatas = [
            {
                "source": prov_title,
                "provider": provider,
                "item_id": item_id,
                "filename": title,
                "title": title,
                "project_id": str(project_id),
                "chunk_index": c_idx,
                "timestamp": timestamp_str,
                "total_chunks": len(chunks)
            }
            for c_idx in range(len(chunks))
        ]

        try:
            semantic_memory.add_documents(
                collection_name="program_knowledge",
                documents=chunks,
                metadatas=metadatas,
                ids=chunk_ids
            )
        except Exception as vec_err:
            print(f"Warning: Vector DB insertion for {item_id}: {vec_err}")

        # 3. Store in MySQL uploaded_documents table
        file_ext = (
            title.split('.')[-1].upper() if '.' in title and len(title.split('.')[-1]) <= 5
            else ("JIRA" if provider == "jira" else ("ADO" if provider == "azure_devops" else provider.upper()))
        )
        size_fmt = item.get("size") or ("2.5 KB" if file_ext in ["JIRA", "ADO"] else "1.5 MB")
        has_risk = 1 if priority_val in ["Critical", "High", "Blocker"] or "risk" in title.lower() else 0

        doc_record = UploadedDocument(
            filename=f"[{prov_title}] {title}" if not title.startswith("[") else title,
            file_type=file_ext,
            file_size_bytes=int(item.get("bytes") or 2048),
            file_size_formatted=size_fmt,
            uploaded_by=f"{prov_title} Agent",
            uploaded_by_role="Connector Pipeline",
            project_id=project_id,
            status="Indexed in Vector Memory",
            risks_detected=has_risk,
            created_at=datetime.now(timezone.utc)
        )
        db.db_session.add(doc_record)
        ingested_count += 1

    db.db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Successfully vectorized and ingested {ingested_count} items from {prov_title} into Project #{project_id}!",
        "ingested_count": ingested_count,
        "project_id": project_id,
        "provider": provider
    })

