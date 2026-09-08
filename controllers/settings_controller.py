from flask import Blueprint, jsonify, request
import db
from models.integration_setting import IntegrationSetting
from services.auth_service import require_roles

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/jira', methods=['GET'])
@require_roles('PMO')
def get_jira_settings():
    setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
    if setting:
        return jsonify(setting.to_dict())
    return jsonify({
        "provider": "jira",
        "base_url": "",
        "username_email": "",
        "updated_at": None
    })

@settings_bp.route('/jira', methods=['POST'])
@require_roles('PMO')
def save_jira_settings():
    data = request.json
    base_url = data.get("base_url", "").strip()
    email = data.get("username_email", "").strip()
    token = data.get("api_token", "").strip()
    
    setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
    
    if not setting:
        setting = IntegrationSetting(provider='jira')
        db.db_session.add(setting)
        
    setting.base_url = base_url
    setting.username_email = email
    
    # Only update token if one was provided (to allow updating URL/Email without re-entering token)
    if token:
        setting.api_token = token
        
    db.db_session.commit()
    return jsonify({"success": True, "message": "Jira settings saved successfully", "data": setting.to_dict()})

@settings_bp.route('/jira/test-connection', methods=['POST'])
@require_roles('PMO')
def test_jira_connection():
    from tools.jira_tool import JiraTool
    result = JiraTool.test_connection()
    return jsonify(result)
