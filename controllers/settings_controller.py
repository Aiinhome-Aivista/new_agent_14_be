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
        "base_url": "https://demo-pwc.atlassian.net",
        "username_email": "demo.pm@pwc-vpm.com",
        "api_token": "DEMO_JIRA_ATLASSIAN_TOKEN_2026"
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
                "updated_at": None
            }
    return jsonify(results)

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
        "updated_at": None
    })

@settings_bp.route('/<provider>', methods=['POST'])
@require_roles('PMO', 'Program Director')
def save_provider_settings(provider):
    data = request.json or {}
    base_url = data.get("base_url", "").strip()
    email = data.get("username_email", "").strip()
    token = data.get("api_token", "").strip()
    
    setting = db.db_session.query(IntegrationSetting).filter_by(provider=provider).first()
    if not setting:
        setting = IntegrationSetting(provider=provider)
        db.db_session.add(setting)
        
    setting.base_url = base_url
    setting.username_email = email
    if token:
        setting.api_token = token
        
    db.db_session.commit()
    return jsonify({"success": True, "message": f"{provider} settings saved successfully", "data": setting.to_dict()})

@settings_bp.route('/<provider>/test-connection', methods=['POST'])
@require_roles('PMO', 'Program Director')
def test_provider_connection(provider):
    tool = TOOL_MAP.get(provider)
    if not tool:
        return jsonify({"success": False, "error": f"Unknown connector provider: {provider}"}), 400
    result = tool.test_connection()
    return jsonify(result)

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
        seeded[prov] = setting.to_dict()
        
    db.db_session.commit()
    return jsonify({
        "success": True, 
        "message": f"Demo sandbox credentials loaded for {', '.join(providers_to_seed)}",
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

