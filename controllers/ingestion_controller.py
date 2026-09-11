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
