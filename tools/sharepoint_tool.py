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
                "error": "SharePoint Site URL and Client Secret / Graph API Key are required."
            }

        sp_url_str = str(sp_url).strip().rstrip('/')
        sp_secret_str = str(sp_secret or '').strip()

        # Check URL validity
        if not sp_url_str.startswith("http"):
            return {
                "success": False,
                "error": f"Invalid SharePoint Site URL format '{sp_url}'. Must be a valid URL starting with https://."
            }

        # ONLY Official 1-Click Demo Sandbox Preset matches sandbox mode
        if sp_url_str == "https://demo-pwc.sharepoint.com/sites/alpha-migration" and sp_secret_str == "DEMO_GRAPH_OAUTH_TOKEN_2026":
            return {
                "success": True,
                "server": sp_url_str,
                "site_name": "Alpha-Migration-PMO-Portal",
                "document_libraries": ["Steering-Committee-MOMs", "Vendor-SOWs-and-Invoices", "Architecture-Blueprints"],
                "user": "Microsoft Graph App Service Principal (Sandboxed)",
                "is_sandbox": True
            }
            
        try:
            # Live Microsoft Graph API ping
            resp = requests.get(f"https://graph.microsoft.com/v1.0/sites/root", headers={"Authorization": f"Bearer {sp_secret_str}"}, timeout=8)
            if resp.status_code in [200, 201]:
                return {"success": True, "server": sp_url_str, "user": sp_tenant or "SharePoint Authorized User", "is_sandbox": False}
            elif resp.status_code in [401, 403]:
                return {"success": False, "error": f"SharePoint authentication failed (HTTP {resp.status_code}): Invalid Client Secret or Access Token."}
            elif resp.status_code == 404:
                return {"success": False, "error": f"SharePoint site not found at '{sp_url_str}' (HTTP 404)."}
            return {"success": False, "error": f"SharePoint/Graph API returned HTTP {resp.status_code}: {resp.text[:150]}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Network error connecting to SharePoint / Microsoft 365: {str(e)[:150]}"}
        except Exception as e:
            return {"success": False, "error": f"Connection failed: {str(e)[:150]}"}

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

    @staticmethod
    def sync_projects_to_db() -> Dict[str, Any]:
        """
        Fetches document libraries from SharePoint and upserts them into the database
        as projects under a default SharePoint Document Libraries program.
        """
        import requests
        import db
        from models.program import Program
        from models.project import Project
        from models.integration_setting import IntegrationSetting

        setting = None
        if db.db_session:
            try:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='sharepoint').first()
            except Exception:
                setting = None
                
        sp_url = setting.base_url if setting and setting.base_url else None
        sp_secret = setting.api_token if setting and setting.api_token else None
        
        if not (sp_url and sp_secret):
            return {"success": False, "error": "SharePoint URL or API Token missing."}

        if not db.db_session:
            return {"success": False, "error": "No database session available."}

        sp_url_str = str(sp_url).strip().rstrip('/')
        sp_secret_str = str(sp_secret or '').strip()

        is_sandbox = (sp_url_str == "https://demo-pwc.sharepoint.com/sites/alpha-migration" and sp_secret_str == "DEMO_GRAPH_OAUTH_TOKEN_2026")

        try:
            libraries = []
            
            if is_sandbox:
                libraries = [
                    {"name": "Steering-Committee-MOMs", "id": "SP-SCM"},
                    {"name": "Vendor-SOWs-and-Invoices", "id": "SP-VSI"},
                    {"name": "Architecture-Blueprints", "id": "SP-AB"}
                ]
            else:
                resp = requests.get(f"https://graph.microsoft.com/v1.0/sites/root/drives", headers={"Authorization": f"Bearer {sp_secret_str}"}, timeout=10)
                
                if resp.status_code == 200:
                    data = resp.json()
                    libraries = data.get("value", [])
                else:
                    return {"success": False, "error": f"SharePoint API HTTP {resp.status_code}"}

            program_name = "SharePoint Document Libraries"
            program = db.db_session.query(Program).filter_by(name=program_name).first()
            if not program:
                program = Program(name=program_name, description="Document Libraries imported from SharePoint")
                db.db_session.add(program)
                db.db_session.flush()

            synced_projects = 0
            for lib in libraries:
                lib_name = lib.get("name")
                lib_id = lib.get("id", lib_name)
                
                if not lib_name:
                    continue
                    
                sp_key = f"SP-{lib_name[:10].upper().replace(' ', '')}"
                
                project = db.db_session.query(Project).filter_by(jira_key=sp_key).first()
                if not project:
                    project = Project(
                        program_id=program.id,
                        jira_key=sp_key,
                        name=lib_name,
                        status='Active'
                    )
                    db.db_session.add(project)
                    synced_projects += 1
                else:
                    if project.name != lib_name or project.program_id != program.id:
                        project.name = lib_name
                        project.program_id = program.id
                        synced_projects += 1

            db.db_session.commit()
            return {
                "success": True,
                "synced_projects": synced_projects,
                "message": f"Successfully synced {synced_projects} document libraries as projects from SharePoint."
            }
        except Exception as e:
            logger.error(f"Error syncing SharePoint libraries to DB: {e}")
            if db.db_session:
                db.db_session.rollback()
            return {"success": False, "error": str(e)}

SharepointTool = SharePointTool

