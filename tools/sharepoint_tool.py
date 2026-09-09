import logging
from typing import Dict, Any, List
import requests

logger = logging.getLogger(__name__)

class SharePointTool:
    """
    Enterprise connector for Microsoft SharePoint / OneDrive / Office 365.
    Discovers and syncs governance documents, MOM decks, and project charters.
    """
    
    @staticmethod
    def get_schema() -> Dict[str, Any]:
        return {
            "name": "sync_sharepoint_documents",
            "description": "Polls and downloads new meeting minutes, vendor SOWs, and steering committee decks from SharePoint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_url": {"type": "string", "description": "SharePoint site URL"},
                    "library_name": {"type": "string", "description": "Document library name"}
                }
            }
        }

    @staticmethod
    def test_connection() -> Dict[str, Any]:
        import db
        from models.integration_setting import IntegrationSetting
        
        setting = None
        if db.db_session:
            try:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='sharepoint').first()
            except Exception:
                setting = None
                
        sp_url = setting.base_url if setting and setting.base_url else None
        sp_tenant = setting.username_email if setting and setting.username_email else None
        sp_secret = setting.api_token if setting and setting.api_token else None
        
        if not (sp_url and (sp_secret or sp_tenant)):
            return {
                "success": False,
                "error": "SharePoint credentials not configured. Please enter credentials or click 'Load Demo Credentials'."
            }
            
        # Sandbox detection
        if "demo" in str(sp_url).lower() or "demo" in str(sp_secret).lower():
            return {
                "success": True,
                "server": sp_url,
                "site_name": "Alpha-Migration-PMO-Portal",
                "document_libraries": ["Steering-Committee-MOMs", "Vendor-SOWs-and-Invoices", "Architecture-Blueprints"],
                "user": "Microsoft Graph App Service Principal (Sandboxed)",
                "is_sandbox": True
            }
            
        try:
            # Live Microsoft Graph API ping
            resp = requests.get(f"https://graph.microsoft.com/v1.0/sites/root", headers={"Authorization": f"Bearer {sp_secret}"}, timeout=10)
            if resp.status_code == 200:
                return {"success": True, "server": sp_url, "user": sp_tenant or "SharePoint Authorized"}
            return {"success": False, "error": f"SharePoint/Graph API returned HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute() -> Dict[str, Any]:
        """
        Simulates retrieving recent governance documents ready for vector indexing.
        """
        return {
            "success": True,
            "provider": "sharepoint",
            "documents_discovered": [
                {"name": "Steering_Committee_Q3_Review_Deck.pptx", "size": "4.2 MB", "last_modified": "2026-09-08", "author": "Program Director"},
                {"name": "Alpha_Migration_Milestone_3_SOW.docx", "size": "1.8 MB", "last_modified": "2026-09-07", "author": "Vendor Delivery Head"},
                {"name": "Payment_Gateway_Security_Audit_Report.pdf", "size": "3.1 MB", "last_modified": "2026-09-06", "author": "Chief InfoSec Officer"}
            ]
        }

SharepointTool = SharePointTool

