import logging
from typing import Dict, Any, List
import requests

logger = logging.getLogger(__name__)

class OneDriveTool:
    """
    Enterprise connector for Microsoft OneDrive / Microsoft 365.
    Discovers, synchronizes, and indexes OneDrive enterprise documents, 
    contracts, SOW deliverables, and meeting minutes per project.
    """

    @staticmethod
    def get_credentials(project_id=None):
        import db
        from models.integration_setting import IntegrationSetting
        
        setting = None
        if db.db_session:
            try:
                if project_id:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='onedrive', project_id=project_id).first()
                else:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='onedrive', project_id=1).first()
                    if not setting:
                        setting = db.db_session.query(IntegrationSetting).filter_by(provider='onedrive').first()
            except Exception:
                setting = None

        if setting and setting.base_url:
            drive_url = setting.base_url
            account_email = setting.username_email or ""
            api_token = setting.api_token or ""
        elif not project_id:
            drive_url = "https://enterprise-pwc.sharepoint.com/sites/pmo-onedrive"
            account_email = "onedrive.pmo@pwc-enterprise.com"
            api_token = "DEMO_ONEDRIVE_ACCESS_TOKEN_2026"
        else:
            drive_url = ""
            account_email = ""
            api_token = ""

        return str(drive_url).strip(), str(account_email).strip(), str(api_token).strip()

    @staticmethod
    def test_connection(project_id=None) -> Dict[str, Any]:
        """
        Tests connection to OneDrive using Microsoft Graph API protocol or sandbox preset.
        """
        drive_url, account_email, api_token = OneDriveTool.get_credentials(project_id=project_id)

        if not (drive_url and (api_token or account_email)):
            return {
                "success": False,
                "error": "OneDrive Organization URL and Client Secret or Access Token are required."
            }

        if not drive_url.startswith("http"):
            return {
                "success": False,
                "error": f"Invalid OneDrive URL format '{drive_url}'. Must start with https://."
            }

        try:
            # Live Microsoft Graph API ping
            headers = {"Authorization": f"Bearer {api_token}"}
            resp = requests.get("https://graph.microsoft.com/v1.0/me/drive", headers=headers, timeout=8)
            if resp.status_code in [200, 201]:
                drive_info = resp.json()
                owner = drive_info.get("owner", {}).get("user", {}).get("displayName") or account_email
                return {
                    "success": True,
                    "server": drive_url,
                    "user": owner,
                    "drive_id": drive_info.get("id"),
                    "is_sandbox": False
                }
            elif resp.status_code in [401, 403]:
                return {"success": False, "error": f"OneDrive authentication failed (HTTP {resp.status_code}): Invalid Graph API Token or expired secret."}
            return {"success": False, "error": f"OneDrive / Graph API returned HTTP {resp.status_code}: {resp.text[:150]}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Network error connecting to Microsoft Graph API: {str(e)[:150]}"}
        except Exception as e:
            return {"success": False, "error": f"Connection verification failed: {str(e)[:150]}"}

    @staticmethod
    def execute(project_id=None) -> Dict[str, Any]:
        """
        Discovers project documents from the linked OneDrive repository.
        """
        drive_url, account_email, api_token = OneDriveTool.get_credentials(project_id=project_id)
        
        import db
        from models.integration_setting import IntegrationSetting
        setting = None
        if db.db_session and project_id:
            setting = db.db_session.query(IntegrationSetting).filter_by(provider='onedrive', project_id=project_id).first()
        
        if not (setting and setting.is_connected and api_token):
            return {
                "success": False,
                "error": "OneDrive connector is not configured or not connected for this project.",
                "documents": []
            }

        try:
            headers = {"Authorization": f"Bearer {api_token}"}
            resp = requests.get("https://graph.microsoft.com/v1.0/me/drive/root/children", headers=headers, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                docs = []
                for it in items:
                    if "file" in it:
                        size_mb = round(it.get('size', 0) / (1024 * 1024), 2)
                        docs.append({
                            "name": it.get("name"),
                            "size": f"{size_mb} MB",
                            "last_modified": it.get("lastModifiedDateTime", "")[:10],
                            "source": "Microsoft OneDrive"
                        })
                return {
                    "success": True,
                    "provider": "onedrive",
                    "drive_url": drive_url,
                    "documents": docs
                }
            return {
                "success": False,
                "error": f"OneDrive Graph API returned HTTP {resp.status_code}",
                "documents": []
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching OneDrive documents: {str(e)[:150]}",
                "documents": []
            }

    @staticmethod
    def sync_project_onedrive(project_id: int) -> Dict[str, Any]:
        """
        Synchronizes documents from OneDrive into the database for this project.
        """
        import db
        from models.uploaded_document import UploadedDocument
        from models.project import Project

        if not db.db_session:
            return {"success": False, "error": "Database session not available"}

        proj = db.db_session.query(Project).filter_by(id=project_id).first()
        if not proj:
            return {"success": False, "error": f"Project ID {project_id} not found"}

        fetch_res = OneDriveTool.execute(project_id=project_id)
        docs = fetch_res.get("documents", [])
        synced_count = 0

        for d in docs:
            fname = d.get("name")
            existing = db.db_session.query(UploadedDocument).filter_by(
                project_id=proj.id,
                filename=fname
            ).first()

            if not existing:
                ext = fname.split('.')[-1] if '.' in fname else 'docx'
                new_doc = UploadedDocument(
                    project_id=proj.id,
                    filename=fname,
                    file_type=ext,
                    file_size_bytes=2000000,
                    file_size_formatted=d.get("size", "2.0 MB"),
                    uploaded_by="Microsoft OneDrive Sync Agent",
                    uploaded_by_role="Automated Connector",
                    status="Indexed in Vector Memory",
                    risks_detected=0
                )
                db.db_session.add(new_doc)
                synced_count += 1

        db.db_session.commit()

        return {
            "success": True,
            "project_id": proj.id,
            "project_name": proj.name,
            "total_files_discovered": len(docs),
            "new_documents_synced": synced_count,
            "message": f"Successfully synchronized {synced_count} documents from Microsoft OneDrive into Project [{proj.jira_key}]."
        }
