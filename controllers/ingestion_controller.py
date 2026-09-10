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
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ingestion_bp.route('/history', methods=['GET'])
@require_roles('PMO', 'Project Manager', 'Program Director', 'Investor')
def list_ingestion_history():
    uploads_dir = os.path.join(os.getcwd(), 'uploads')
    if not os.path.exists(uploads_dir):
        return jsonify([])

    docs = []
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
                "status": "Indexed in Vector Memory",
                "indexed": True
            })
    return jsonify(docs)
