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
