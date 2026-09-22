import os
from flask import Blueprint, request, jsonify
from services.ingestion_service import IngestionService
from services.auth_service import require_roles

ingestion_bp = Blueprint('ingestion', __name__)

@ingestion_bp.route('/check-accuracy', methods=['POST'])
@require_roles('PMO', 'Project Manager', 'Program Director')
def check_document_accuracy():
    """
    Evaluates uploaded document against target project's description & scope.
    Returns match percentage, threshold from .env, matched aspects, and unmatched aspects.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided for accuracy check"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    raw_pid = request.form.get('project_id', '1')
    try:
        project_id = int(raw_pid)
    except (ValueError, TypeError):
        project_id = 1

    # Temporarily save file to disk for parsing
    temp_dir = os.path.join(os.getcwd(), 'uploads', 'temp_accuracy')
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)
    file.save(temp_path)

    try:
        from services.accuracy_service import DataAccuracyService
        result = DataAccuracyService.evaluate_file(temp_path, project_id=project_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Error checking accuracy: {str(e)}"}), 500
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@ingestion_bp.route('/check-connector-accuracy', methods=['POST'])
@require_roles('PMO', 'Project Manager', 'Program Director')
def check_connector_accuracy():
    """
    Evaluates batch of connector items against target project's description & scope.
    """
    data = request.json or {}
    items = data.get('items', [])
    raw_pid = data.get('project_id', 1)
    provider = data.get('provider', 'connector')
    try:
        project_id = int(raw_pid)
    except (ValueError, TypeError):
        project_id = 1

    if not items:
        return jsonify({"error": "No items provided for accuracy check"}), 400

    try:
        from services.accuracy_service import DataAccuracyService
        result = DataAccuracyService.evaluate_connector_items(items, project_id=project_id, provider=provider)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Error checking connector accuracy: {str(e)}"}), 500


def sync_uploaded_doc_telemetry(file_path, project_id):
    """
    Parses structured team ownership or milestone tables from the uploaded doc
    and persists them permanently into the MySQL database (project_members, project_milestones).
    """
    if not file_path or not project_id or not os.path.exists(file_path):
        return
    if not file_path.lower().endswith('.docx'):
        return

    try:
        import db
        from docx import Document
        from models.project_member import ProjectMember
        from models.project_milestone import ProjectMilestone

        doc = Document(file_path)
        for table in doc.tables:
            if not table.rows:
                continue
            headers = [c.text.strip().lower() for c in table.rows[0].cells]
            if 'name' in headers and 'role' in headers and 'signature' not in headers:
                name_idx = headers.index('name')
                role_idx = headers.index('role')
                contact_idx = headers.index('contact') if 'contact' in headers else -1
                for row in table.rows[1:]:
                    cells = [c.text.strip() for c in row.cells]
                    if len(cells) > max(name_idx, role_idx) and cells[name_idx]:
                        m_name = cells[name_idx]
                        m_role = cells[role_idx]
                        m_contact = cells[contact_idx] if contact_idx >= 0 and len(cells) > contact_idx else ''
                        existing = db.db_session.query(ProjectMember).filter_by(project_id=project_id, name=m_name).first()
                        if existing:
                            existing.role = m_role
                            existing.contact = m_contact
                        else:
                            new_m = ProjectMember(
                                project_id=project_id,
                                name=m_name,
                                role=m_role,
                                contact=m_contact,
                                member_type='Internal FTE',
                                allocation_pct=100.0,
                                is_active_today=True
                            )
                            db.db_session.add(new_m)
            elif 'milestone' in headers or any('milestone' in h for h in headers):
                m_idx = -1
                for idx, h in enumerate(headers):
                    if 'milestone' in h or 'code' in h or 'id' in h:
                        m_idx = idx
                        break
                desc_idx = headers.index('description') if 'description' in headers else -1
                target_idx = headers.index('target date') if 'target date' in headers else (-1 if 'target' not in headers else headers.index('target'))
                stat_idx = headers.index('status') if 'status' in headers else -1
                tranche_idx = -1
                for idx, h in enumerate(headers):
                    if any(k in h for k in ['tranche', 'amount', 'value', 'price', 'cost', 'budget']):
                        tranche_idx = idx
                        break

                for row in table.rows[1:]:
                    cells = [c.text.strip() for c in row.cells]
                    if len(cells) > m_idx and m_idx >= 0 and cells[m_idx]:
                        m_code = cells[m_idx]
                        m_desc = cells[desc_idx] if desc_idx >= 0 and len(cells) > desc_idx else ''
                        m_target = cells[target_idx] if target_idx >= 0 and len(cells) > target_idx else 'TBD'
                        m_stat = cells[stat_idx] if stat_idx >= 0 and len(cells) > stat_idx else 'Pending'
                        
                        m_tranche = 0.0
                        if tranche_idx >= 0 and len(cells) > tranche_idx:
                            raw_tr = cells[tranche_idx]
                            try:
                                clean_tr = raw_tr.replace("$", "").replace(",", "").strip()
                                if clean_tr.lower().endswith("k"):
                                    m_tranche = float(clean_tr[:-1]) * 1000
                                elif clean_tr.lower().endswith("m"):
                                    m_tranche = float(clean_tr[:-1]) * 1000000
                                else:
                                    m_tranche = float(clean_tr)
                            except Exception:
                                m_tranche = 0.0

                        comp_pct = 100 if m_stat.lower() in ('done', 'completed') else (50 if m_stat.lower() in ('in progress', 'on track') else (20 if 'risk' in m_stat.lower() else 0))
                        existing_ms = db.db_session.query(ProjectMilestone).filter_by(project_id=project_id, milestone_code=m_code).first()
                        if existing_ms:
                            existing_ms.name = f"{m_code}: {m_desc}" if m_desc else m_code
                            existing_ms.description = m_desc
                            existing_ms.target_date = m_target
                            existing_ms.status = m_stat
                            existing_ms.completion_pct = comp_pct
                            if m_tranche > 0:
                                existing_ms.tranche_amount = m_tranche
                        else:
                            new_ms = ProjectMilestone(
                                project_id=project_id,
                                milestone_code=m_code,
                                name=f"{m_code}: {m_desc}" if m_desc else m_code,
                                description=m_desc,
                                target_date=m_target,
                                status=m_stat,
                                completion_pct=comp_pct,
                                days_left=0 if comp_pct == 100 else 45,
                                tranche_amount=m_tranche
                            )
                            db.db_session.add(new_ms)
            elif any(any(k in h for k in ['task', 'deliverable', 'action item']) for h in headers):
                from models.task_item import TaskItem
                from datetime import datetime, timezone
                title_idx = -1
                for idx, h in enumerate(headers):
                    if any(k in h for k in ['task', 'deliverable', 'action item', 'title', 'summary', 'work package']):
                        title_idx = idx
                        break
                
                if title_idx != -1:
                    stat_idx = -1
                    assign_idx = -1
                    for idx, h in enumerate(headers):
                        if 'status' in h:
                            stat_idx = idx
                        elif 'assignee' in h or 'owner' in h:
                            assign_idx = idx
                    
                    for row_idx, row in enumerate(table.rows[1:]):
                        cells = [c.text.strip() for c in row.cells]
                        if len(cells) > title_idx and cells[title_idx]:
                            t_title = cells[title_idx]
                            t_stat = cells[stat_idx] if stat_idx >= 0 and len(cells) > stat_idx else 'To Do'
                            t_assign = cells[assign_idx] if assign_idx >= 0 and len(cells) > assign_idx else 'Unassigned'
                            
                            existing_t = db.db_session.query(TaskItem).filter_by(project_id=project_id, summary=t_title).first()
                            if existing_t:
                                existing_t.status = t_stat
                                existing_t.assignee = t_assign
                                existing_t.updated_at = datetime.now(timezone.utc)
                            else:
                                new_t = TaskItem(
                                    project_id=project_id,
                                    jira_key=f"DOC-{project_id}-T{row_idx+1}",
                                    summary=t_title,
                                    status=t_stat,
                                    priority="Medium",
                                    assignee=t_assign,
                                    created_at=datetime.now(timezone.utc),
                                    updated_at=datetime.now(timezone.utc)
                                )
                                db.db_session.add(new_t)
        db.db_session.commit()
    except Exception as e:
        print(f"[sync_uploaded_doc_telemetry] Error saving doc telemetry to MySQL: {e}")

@ingestion_bp.route('/upload', methods=['POST'])
@require_roles('PMO', 'Project Manager', 'Program Director')
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

        from models.project import Project
        valid_pid = None
        if project_id:
            try:
                p = db.db_session.query(Project).filter_by(id=project_id).first()
                if p:
                    valid_pid = p.id
                else:
                    first_p = db.db_session.query(Project).first()
                    if first_p:
                        valid_pid = first_p.id
            except Exception:
                valid_pid = None

        raw_acc = request.form.get('accuracy_score')
        accuracy_score = 90
        if raw_acc and str(raw_acc).isdigit():
            accuracy_score = int(raw_acc)
        else:
            try:
                from services.accuracy_service import DataAccuracyService
                eval_res = DataAccuracyService.evaluate_file(file_path, project_id=valid_pid or 1)
                accuracy_score = eval_res.get('match_percentage', 90)
            except Exception:
                accuracy_score = 90

        doc_record = UploadedDocument(
            filename=file.filename,
            file_type=ext,
            file_size_bytes=file_size_bytes,
            file_size_formatted=size_fmt,
            uploaded_by=uploaded_by,
            uploaded_by_role=uploaded_by_role,
            project_id=valid_pid,
            status="Indexed in Vector Memory",
            risks_detected=risks_detected,
            accuracy_score=accuracy_score,
            created_at=datetime.now(timezone.utc)
        )
        db.db_session.add(doc_record)
        db.db_session.commit()

        # Persist extracted team members and milestones permanently into MySQL
        sync_uploaded_doc_telemetry(file_path, valid_pid or project_id)
        
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
    try:
        if db.db_session:
            query = db.db_session.query(UploadedDocument)
            project_id_param = request.args.get('project_id')
            if project_id_param and str(project_id_param).strip().lower() not in ('all', '', 'none', 'null'):
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

    # ONLY return records that exist in the database (no filesystem fallback)
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
                "assignee": issue.get("assignee", "Unassigned"),
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
@require_roles('PMO', 'Project Manager', 'Program Director')
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
        assignee_val = item.get("assignee") or "Unassigned"
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
            accuracy_score=int(item.get("accuracy_score") or 90),
            created_at=datetime.now(timezone.utc)
        )
        db.db_session.add(doc_record)
        ingested_count += 1

        # If item indicates a critical/high delivery blocker or risk, persist into RiskRegister
        if has_risk:
            from models.risk_register import RiskRegister
            clean_rid = f"R-{item_id}" if not item_id.startswith("R-") else item_id
            existing_risk = db.db_session.query(RiskRegister).filter(
                RiskRegister.project_id == project_id,
                (RiskRegister.risk_id == clean_rid) | (RiskRegister.jira_issue_key == item_id)
            ).first()
            if not existing_risk:
                new_r = RiskRegister(
                    project_id=project_id,
                    risk_id=clean_rid,
                    title=title,
                    description=desc,
                    severity="Critical" if priority_val in ["Critical", "Blocker"] else "High",
                    status="Open",
                    owner=f"{prov_title} Synced",
                    mitigation_plan=f"Ingested from live {prov_title} ticket {item_id}. Prioritize in sprint backlog.",
                    jira_issue_key=item_id if provider == "jira" else None,
                    created_at=datetime.now(timezone.utc)
                )
                db.db_session.add(new_r)

        # Store as TaskItem so it shows up in the dashboard
        from models.task_item import TaskItem
        if provider in ["jira", "azure_devops"]:
            existing_task = db.db_session.query(TaskItem).filter(
                TaskItem.project_id == project_id,
                TaskItem.jira_key == item_id
            ).first()
            if not existing_task:
                new_task = TaskItem(
                    project_id=project_id,
                    jira_key=item_id,
                    summary=title,
                    status=status_val,
                    priority=priority_val,
                    assignee=assignee_val,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.db_session.add(new_task)
            else:
                existing_task.summary = title
                existing_task.status = status_val
                existing_task.priority = priority_val
                existing_task.assignee = assignee_val
                existing_task.updated_at = datetime.now(timezone.utc)

    db.db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Successfully vectorized and ingested {ingested_count} items from {prov_title} into Project #{project_id}!",
        "ingested_count": ingested_count,
        "project_id": project_id,
        "provider": provider
    })

