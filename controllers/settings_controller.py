from flask import Blueprint, jsonify, request
import db
from models.integration_setting import IntegrationSetting
from services.auth_service import require_roles
from tools.jira_tool import JiraTool
from tools.azure_devops_tool import AzureDevOpsTool
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
    "azure_devops": {
        "provider": "azure_devops",
        "base_url": "https://dev.azure.com/demo-pwc-enterprise",
        "username_email": "devops.lead@pwc-vpm.com",
        "api_token": "DEMO_AZURE_DEVOPS_PAT_2026"
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
    "sap_erp": SapErpTool,
    "sharepoint": SharePointTool,
    "notifications": NotificationTool
}

@settings_bp.route('', methods=['GET'])
@settings_bp.route('/', methods=['GET'])
@settings_bp.route('/all', methods=['GET'])
@require_roles('PMO', 'Program Director')
def get_all_settings():
    """Fetches configuration state of all 5 enterprise connectors."""
    providers = ["jira", "azure_devops", "sap_erp", "sharepoint", "notifications"]
    results = {}
    for prov in providers:
        setting = db.db_session.query(IntegrationSetting).filter_by(provider=prov).first()
        if setting:
            results[prov] = setting.to_dict()
        else:
            results[prov] = {
                "provider": prov,
                "base_url": "",
                "username_email": "",
                "is_connected": False,
                "has_token": False,
                "updated_at": None
            }
    return jsonify({
        "success": True,
        "settings": list(results.values()),
        "data": results,
        **results
    })

@settings_bp.route('/<provider>', methods=['GET'])
@require_roles('PMO', 'Program Director')
def get_provider_settings(provider):
    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider).first()
    if setting:
        return jsonify(setting.to_dict())
    return jsonify({
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
    base_url = data.get("base_url", "").strip()
    email = data.get("username_email", "").strip()
    token = data.get("api_token", "").strip()
    
    if not base_url:
        return jsonify({"success": False, "error": f"Base URL / Endpoint is required for {provider}."}), 400

    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider).first()
    if not setting:
        setting = IntegrationSetting(provider=provider)
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

    test_result = tool.test_connection()
    if test_result.get("success"):
        setting.is_connected = True
        db.db_session.commit()
        return jsonify({
            "success": True, 
            "is_connected": True,
            "message": f"Successfully verified and connected to {provider}! Authenticated as {test_result.get('user', 'Verified User')}",
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
    
    result = tool.test_connection()
    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider).first()
    if setting:
        if result.get("success"):
            setting.is_connected = True
        else:
            setting.is_connected = False
        db.db_session.commit()
    return jsonify(result)

@settings_bp.route('/<provider>/disconnect', methods=['POST'])
@require_roles('PMO', 'Program Director')
def disconnect_provider(provider):
    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider).first()
    if setting:
        setting.is_connected = False
        db.db_session.commit()
    return jsonify({
        "success": True, 
        "message": f"{provider} disconnected successfully.",
        "provider": provider,
        "is_connected": False
    })

@settings_bp.route('/demo-presets', methods=['POST'])
@require_roles('PMO', 'Program Director')
def load_demo_presets():
    """1-Click load demo presets for all connectors into the database."""
    target_provider = request.json.get("provider") if request.json else None
    
    providers_to_seed = [target_provider] if target_provider and target_provider in DEMO_PRESETS else DEMO_PRESETS.keys()
    
    seeded = {}
    for prov in providers_to_seed:
        preset = DEMO_PRESETS[prov]
        setting = db.db_session.query(IntegrationSetting).filter_by(provider=prov).first()
        if not setting:
            setting = IntegrationSetting(provider=prov)
            db.db_session.add(setting)
        setting.base_url = preset["base_url"]
        setting.username_email = preset["username_email"]
        setting.api_token = preset["api_token"]
        setting.is_connected = True
        seeded[prov] = setting.to_dict()
        
    db.db_session.commit()
    return jsonify({
        "success": True, 
        "message": f"Demo sandbox credentials loaded and connected for {', '.join(providers_to_seed)}",
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


