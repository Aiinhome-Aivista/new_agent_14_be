from flask import Blueprint, jsonify, request
import db
from models.integration_setting import IntegrationSetting
from services.auth_service import require_roles
from tools.jira_tool import JiraTool
from tools.azure_devops_tool import AzureDevOpsTool
from tools.google_drive_tool import GoogleDriveTool
from tools.onedrive_tool import OneDriveTool
from tools.sap_erp_tool import SapErpTool
from tools.sharepoint_tool import SharePointTool
from tools.notification_tool import NotificationTool

settings_bp = Blueprint('settings', __name__)

DEMO_PRESETS = {
    "jira": {
        "provider": "jira",
        "base_url": "https://dipakkrsaha44.atlassian.net",
        "username_email": "dipakkrsaha44@gmail.com",
        "api_token": "ATATT3xFfGF0o2M-o3hxSh4XCKwBcrLO5EvrYYVjZ-DO60zGU6LuMpqMext-Uwy664taZSs1uS8ifdZaIHboUlaG1gKf5C_1rp6tUhYGt7S1G39ramjutsJwM9RrvvXG71mDV9nfXgRk8gcyPG3YBp1DMgYHOfaxkDJGQ0JQo63jr92dgdpGHIs=07F60D9C"
    },
    "sap_erp": {
        "provider": "sap_erp",
        "base_url": "https://demo-s4hana.enterprise.pwc/sap/opu/odata",
        "username_email": "SAP_CC_ALPHA_READER",
        "api_token": "DEMO_SAP_MUTUAL_SECRET_2026"
    },
    "sharepoint": {
        "provider": "sharepoint",
        "base_url": "https://demo-pwc.sharepoint.com/sites/alpha-migration",
        "username_email": "sp-graph-client@pwc-vpm.onmicrosoft.com",
        "api_token": "DEMO_GRAPH_OAUTH_TOKEN_2026"
    },
    "notifications": {
        "provider": "notifications",
        "base_url": "https://hooks.slack.com/demo/services/T00/B00/VPM_DEMO_SECRET",
        "username_email": "#vpm-leadership-escalations",
        "api_token": "DEMO_TEAMS_WEBHOOK_KEY"
    }
}

TOOL_MAP = {
    "jira": JiraTool,
    "azure_devops": AzureDevOpsTool,
    "google_drive": GoogleDriveTool,
    "onedrive": OneDriveTool,
    "sap_erp": SapErpTool,
    "sharepoint": SharePointTool,
    "notifications": NotificationTool
}

def get_requested_project_id():
    pid = request.args.get('project_id')
    if not pid and request.is_json and request.json:
        pid = request.json.get('project_id')
    if pid is not None:
        try:
            return int(pid)
        except (ValueError, TypeError):
            pass
    return 1

@settings_bp.route('', methods=['GET'])
@settings_bp.route('/', methods=['GET'])
@settings_bp.route('/all', methods=['GET'])
@require_roles('PMO', 'Program Director')
def get_all_settings():
    """Fetches configuration state of enterprise connectors scoped by project_id."""
    project_id = get_requested_project_id()
    providers = ["jira", "azure_devops", "google_drive", "onedrive", "sap_erp", "sharepoint", "notifications"]
    results = {}
    for prov in providers:
        setting = db.db_session.query(IntegrationSetting).filter_by(provider=prov, project_id=project_id).first()
        if setting:
            results[prov] = setting.to_dict()
        else:
            results[prov] = {
                "id": None,
                "project_id": project_id,
                "provider": prov,
                "base_url": "",
                "username_email": "",
                "is_connected": False,
                "has_token": False,
                "updated_at": None
            }
    return jsonify({
        "success": True,
        "project_id": project_id,
        "settings": list(results.values()),
        "data": results,
        **results
    })

@settings_bp.route('/<provider>', methods=['GET'])
@require_roles('PMO', 'Program Director')
def get_provider_settings(provider):
    project_id = get_requested_project_id()
    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider, project_id=project_id).first()
    if setting:
        return jsonify(setting.to_dict())
    return jsonify({
        "id": None,
        "project_id": project_id,
        "provider": provider,
        "base_url": "",
        "username_email": "",
        "is_connected": False,
        "has_token": False,
        "updated_at": None
    })

@settings_bp.route('/<provider>', methods=['POST'])
@require_roles('PMO', 'Program Director')
def save_provider_settings(provider):
    data = request.json or {}
    project_id = get_requested_project_id()
    base_url = data.get("base_url", "").strip()
    email = data.get("username_email", "").strip()
    token = data.get("api_token", "").strip()
    
    if not base_url:
        return jsonify({"success": False, "error": f"Base URL / Endpoint is required for {provider}."}), 400

    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider, project_id=project_id).first()
    if not setting:
        setting = IntegrationSetting(provider=provider, project_id=project_id)
        db.db_session.add(setting)
        
    setting.base_url = base_url
    setting.username_email = email
    if token:
        setting.api_token = token
        
    # Flush credentials to session so tool.test_connection can evaluate them
    db.db_session.flush()

    # REAL LIVE CONNECTION VERIFICATION HANDSHAKE
    tool = TOOL_MAP.get(provider)
    if not tool:
        setting.is_connected = False
        db.db_session.commit()
        return jsonify({"success": False, "error": f"Unknown connector provider: {provider}"}), 400

    import inspect
    if hasattr(tool, 'test_connection'):
        sig = inspect.signature(tool.test_connection)
        if 'project_id' in sig.parameters:
            test_result = tool.test_connection(project_id=project_id)
        else:
            test_result = tool.test_connection()
    else:
        test_result = {"success": True}

    if test_result.get("success"):
        setting.is_connected = True
        db.db_session.commit()
        return jsonify({
            "success": True, 
            "is_connected": True,
            "project_id": project_id,
            "message": f"Successfully verified and connected to {provider} for Project #{project_id}! Authenticated as {test_result.get('user', 'Verified User')}",
            "data": setting.to_dict(),
            "test_result": test_result
        })
    else:
        # FAILED: Strictly reject and do NOT connect invalid / fake data
        setting.is_connected = False
        db.db_session.commit()
        err_msg = test_result.get("error") or "Authentication failed. Invalid credentials or server unreachable."
        return jsonify({
            "success": False,
            "is_connected": False,
            "project_id": project_id,
            "error": f"Connection verification failed: {err_msg}",
            "data": setting.to_dict(),
            "test_result": test_result
        }), 400

@settings_bp.route('/<provider>/test-connection', methods=['POST'])
@require_roles('PMO', 'Program Director')
def test_provider_connection(provider):
    tool = TOOL_MAP.get(provider)
    if not tool:
        return jsonify({"success": False, "error": f"Unknown connector provider: {provider}"}), 400
    
    project_id = get_requested_project_id()
    data = request.json or {}

    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider, project_id=project_id).first()
    if not setting:
        setting = IntegrationSetting(provider=provider, project_id=project_id)
        db.db_session.add(setting)

    # If new credentials were provided in test payload, update them for live verification
    if "base_url" in data and data.get("base_url") is not None:
        setting.base_url = str(data["base_url"]).strip()
    if "api_token" in data and data.get("api_token") is not None:
        setting.api_token = str(data["api_token"]).strip()
    if "username_email" in data and data.get("username_email") is not None:
        setting.username_email = str(data["username_email"]).strip()
    db.db_session.flush()

    import inspect
    if hasattr(tool, 'test_connection'):
        sig = inspect.signature(tool.test_connection)
        if 'project_id' in sig.parameters:
            result = tool.test_connection(project_id=project_id)
        else:
            result = tool.test_connection()
    else:
        result = {"success": True}

    setting.is_connected = bool(result.get("success"))
    db.db_session.commit()
    return jsonify(result)

@settings_bp.route('/<provider>/disconnect', methods=['POST'])
@require_roles('PMO', 'Program Director')
def disconnect_provider(provider):
    project_id = get_requested_project_id()
    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider, project_id=project_id).first()
    if setting:
        setting.is_connected = False
        db.db_session.commit()
    return jsonify({
        "success": True, 
        "project_id": project_id,
        "message": f"{provider} disconnected successfully for Project #{project_id}.",
        "provider": provider,
        "is_connected": False
    })

@settings_bp.route('/demo-presets', methods=['POST'])
@require_roles('PMO', 'Program Director')
def load_demo_presets():
    """1-Click load demo presets for connectors into the database for the specified project."""
    project_id = get_requested_project_id()
    target_provider = request.json.get("provider") if request.json else None
    
    if target_provider in ('google_drive', 'azure_devops', 'onedrive'):
        prov_name = target_provider.replace('_', ' ').title()
        return jsonify({
            "success": False,
            "error": f"{prov_name} requires real enterprise credentials and live authentication. Mock demo sandbox is disabled."
        }), 400

    providers_to_seed = [target_provider] if target_provider and target_provider in DEMO_PRESETS else [p for p in DEMO_PRESETS.keys() if p not in ('google_drive', 'azure_devops', 'onedrive')]
    
    seeded = {}
    for prov in providers_to_seed:
        if prov not in DEMO_PRESETS:
            continue
        preset = DEMO_PRESETS[prov]
        setting = db.db_session.query(IntegrationSetting).filter_by(provider=prov, project_id=project_id).first()
        if not setting:
            setting = IntegrationSetting(provider=prov, project_id=project_id)
            db.db_session.add(setting)
        setting.base_url = preset["base_url"]
        setting.username_email = preset["username_email"]
        setting.api_token = preset["api_token"]
        setting.is_connected = True
        seeded[prov] = setting.to_dict()
        
    db.db_session.commit()
    return jsonify({
        "success": True, 
        "project_id": project_id,
        "message": f"Demo sandbox credentials loaded and connected for {', '.join(providers_to_seed)} on Project #{project_id}",
        "data": seeded
    })

@settings_bp.route('/scheduler', methods=['GET'])
def get_scheduler_status():
    from services.scheduler_service import SchedulerService
    scheduler = SchedulerService.get_instance()
    return jsonify({"success": True, "data": scheduler.get_status()})

@settings_bp.route('/scheduler/trigger', methods=['POST'])
@require_roles('PMO', 'Program Director')
def trigger_scheduler_sync():
    from services.scheduler_service import SchedulerService
    scheduler = SchedulerService.get_instance()
    res = scheduler.trigger_sync_now()
    return jsonify({"success": True, "message": res.get("message")})

@settings_bp.route('/sync-project/<int:project_id>', methods=['POST'])
@require_roles('PMO', 'Program Director')
def sync_project_connectors(project_id):
    """
    Triggers connector synchronization matching the given project.
    Fetches issues/telemetry from Jira and matches to project_id in DB.
    """
    from tools.jira_tool import JiraTool
    res = JiraTool.sync_project_telemetry(project_id)
    if res.get("success"):
        return jsonify(res), 200
    else:
        return jsonify(res), 400

@settings_bp.route('/sync-gdrive/<int:project_id>', methods=['POST'])
@require_roles('PMO', 'Program Director')
def sync_gdrive(project_id):
    """
    Synchronizes project documents from linked Google Drive folder into database.
    """
    from tools.google_drive_tool import GoogleDriveTool
    res = GoogleDriveTool.sync_project_drive(project_id)
    if res.get("success"):
        return jsonify(res), 200
    else:
        return jsonify(res), 400

@settings_bp.route('/sync-onedrive/<int:project_id>', methods=['POST'])
@require_roles('PMO', 'Program Director')
def sync_onedrive(project_id):
    """
    Synchronizes project documents from linked Microsoft OneDrive repository into database.
    """
    from tools.onedrive_tool import OneDriveTool
    res = OneDriveTool.sync_project_onedrive(project_id)
    if res.get("success"):
        return jsonify(res), 200
    else:
        return jsonify(res), 400



