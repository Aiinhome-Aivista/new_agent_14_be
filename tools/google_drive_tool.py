import logging
import json
import re
import time
from typing import Dict, Any, List
import requests

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    service_account = None
    Request = None
    GOOGLE_AUTH_AVAILABLE = False

logger = logging.getLogger(__name__)

DRIVE_SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.metadata.readonly'
]

def extract_folder_id(folder_url: str) -> str:
    """
    Extracts Google Drive folder ID from various Google Drive URL formats.
    e.g.
      https://drive.google.com/drive/folders/1aBcDeFgHiJkLmNoPqRsTuVwXyZ
      https://drive.google.com/drive/u/0/folders/1aBcDeFgHiJkLmNoPqRsTuVwXyZ?usp=sharing
      https://drive.google.com/open?id=1aBcDeFgHiJkLmNoPqRsTuVwXyZ
      1aBcDeFgHiJkLmNoPqRsTuVwXyZ
    """
    if not folder_url:
        return ""
    folder_url = folder_url.strip()
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', folder_url)
    if match:
        return match.group(1)
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', folder_url)
    if match:
        return match.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{15,}$', folder_url):
        return folder_url
    return ""


def resolve_google_access_token(api_token: str, service_email: str = "") -> str:
    """
    Resolves a valid Google Drive OAuth access token from:
    1. Direct OAuth 2.0 Bearer Access Token (starts with ya29. or standard token)
    2. Service Account Private Key PEM ('-----BEGIN PRIVATE KEY-----') + service_email
    3. Full Service Account Credentials JSON
    """
    if not api_token:
        raise ValueError("Google Drive credentials / token is missing.")

    token_clean = api_token.strip()

    # 1. Full JSON credentials format
    if token_clean.startswith("{") and "private_key" in token_clean:
        try:
            info = json.loads(token_clean)
            creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
            creds.refresh(Request())
            return creds.token
        except Exception as e:
            raise ValueError(f"Google Service Account JSON authentication failed: {str(e)}")

    # 2. Service Account Private Key PEM format
    if "BEGIN PRIVATE KEY" in token_clean or "BEGIN RSA PRIVATE KEY" in token_clean:
        if not service_email:
            raise ValueError("Google Account Email is required when using a Service Account Private Key. Please provide the client email (e.g. your-agent@project.iam.gserviceaccount.com) in the Email field.")

        formatted_key = token_clean.replace('\\n', '\n').strip()
        info = {
            "type": "service_account",
            "client_email": service_email.strip(),
            "private_key": formatted_key,
            "token_uri": "https://oauth2.googleapis.com/token"
        }
        try:
            creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
            creds.refresh(Request())
            return creds.token
        except Exception as e:
            err_msg = str(e)
            if "invalid_grant" in err_msg or "account not found" in err_msg:
                raise ValueError(f"Service Account authentication failed: The email '{service_email}' does not match this Private Key or does not exist in Google Cloud Console.")
            raise ValueError(f"Failed to authenticate with Service Account Private Key: {err_msg}")

    # 3. Direct OAuth Bearer Token (ya29... or custom bearer token)
    return token_clean


class GoogleDriveTool:
    """
    Enterprise connector for Google Drive & Google Workspace.
    Supports both Google OAuth 2.0 Access Tokens and Google Cloud Service Account Private Keys.
    Performs REAL authentication verification against Google Drive API v3
    and synchronizes documents from configured Google Drive folders.
    """

    @staticmethod
    def get_credentials(project_id=None):
        import db
        from models.integration_setting import IntegrationSetting
        
        setting = None
        if db.db_session:
            try:
                if project_id:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='google_drive', project_id=project_id).first()
                else:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='google_drive', project_id=1).first()
                    if not setting:
                        setting = db.db_session.query(IntegrationSetting).filter_by(provider='google_drive').first()
            except Exception as e:
                logger.error(f"Error querying IntegrationSetting for google_drive: {e}")
                setting = None

        folder_url = setting.base_url if setting and setting.base_url else ""
        service_email = setting.username_email if setting and setting.username_email else ""
        api_key = setting.api_token if setting and setting.api_token else ""

        return str(folder_url).strip(), str(service_email).strip(), str(api_key).strip()

    @staticmethod
    def test_connection(project_id=None) -> Dict[str, Any]:
        """
        Strictly tests live connection to Google Drive API v3.
        Supports both OAuth 2.0 tokens and Service Account Private Keys.
        Rejects demo tokens, empty credentials, invalid tokens, and unreachable folders.
        """
        folder_url, service_email, api_key = GoogleDriveTool.get_credentials(project_id=project_id)

        # 1. Credentials presence check
        if not api_key:
            return {
                "success": False,
                "error": "Google Drive Access Token or Service Account Private Key is missing."
            }

        if not folder_url:
            return {
                "success": False,
                "error": "Google Drive Folder URL is missing. Please enter a valid Google Drive folder link."
            }

        # 2. Rejection of dummy/demo placeholder tokens
        if "DEMO_GOOGLE_DRIVE_API_KEY_2026" in api_key:
            return {
                "success": False,
                "error": "Demo placeholder detected. Please provide your real Google OAuth 2.0 Access Token or Service Account Private Key."
            }

        # 3. Check for raw Cloud API Key (starts with AIza)
        if api_key.startswith("AIza"):
            return {
                "success": False,
                "error": "Google Drive API requires an OAuth 2.0 Bearer Access Token or a Service Account Private Key. Google Cloud API Keys ('AIza...') cannot access private Drive folders."
            }

        # 4. Folder URL validation
        folder_id = extract_folder_id(folder_url)
        if not folder_id and not ("drive.google.com" in folder_url):
            return {
                "success": False,
                "error": f"Invalid Google Drive URL '{folder_url}'. Must be a valid Drive folder URL (e.g. https://drive.google.com/drive/folders/<FOLDER_ID>)."
            }

        # 5. Resolve real Google Bearer Token (supports Service Account exchange)
        try:
            bearer_token = resolve_google_access_token(api_key, service_email)
        except ValueError as ve:
            return {
                "success": False,
                "error": str(ve)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Token resolution error: {str(e)}"
            }

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json"
        }

        try:
            # Live Google Drive API test: Query profile or drive info
            about_url = "https://www.googleapis.com/drive/v3/about?fields=user,storageQuota"
            resp = requests.get(about_url, headers=headers, timeout=10)

            if resp.status_code == 401:
                return {
                    "success": False,
                    "error": "Google Drive authentication failed (HTTP 401): Invalid or expired access token. Please verify your credentials."
                }
            elif resp.status_code == 403:
                err_msg = "Access forbidden."
                try:
                    err_json = resp.json()
                    err_msg = err_json.get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                return {
                    "success": False,
                    "error": f"Google Drive API error (HTTP 403): {err_msg}. Ensure Google Drive API is enabled in Google Cloud Console."
                }
            elif resp.status_code not in [200, 201]:
                return {
                    "success": False,
                    "error": f"Google Drive API returned HTTP {resp.status_code}: {resp.text[:150]}"
                }

            user_data = resp.json().get("user", {})
            display_name = user_data.get("displayName") or user_data.get("emailAddress") or service_email or "Google Workspace Service Account"
            email = user_data.get("emailAddress") or service_email
            avatar_url = user_data.get("photoLink", "")

            # 6. Verify the specific folder exists and is accessible
            folder_name = "Google Drive Shared Folder"
            if folder_id:
                folder_check_url = f"https://www.googleapis.com/drive/v3/files/{folder_id}?fields=id,name,mimeType,trashed"
                folder_resp = requests.get(folder_check_url, headers=headers, timeout=10)

                if folder_resp.status_code == 200:
                    fdata = folder_resp.json()
                    if fdata.get("trashed"):
                        return {
                            "success": False,
                            "error": f"The target Google Drive folder '{fdata.get('name')}' is in the trash."
                        }
                    folder_name = fdata.get("name", folder_name)
                elif folder_resp.status_code == 404:
                    return {
                        "success": False,
                        "error": f"Google Drive folder not found (HTTP 404). Verify that folder ID '{folder_id}' is correct and that the folder is shared with '{email}'."
                    }
                elif folder_resp.status_code in [401, 403]:
                    return {
                        "success": False,
                        "error": f"Access denied to target Google Drive folder (HTTP {folder_resp.status_code}). Ensure account '{email}' has been granted access to this folder."
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Folder check returned HTTP {folder_resp.status_code}: {folder_resp.text[:150]}"
                    }

            return {
                "success": True,
                "server": folder_url,
                "user": display_name,
                "email": email,
                "avatar_url": avatar_url,
                "folder_name": folder_name,
                "folder_id": folder_id,
                "is_sandbox": False
            }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Connection to Google Drive API timed out (10s). Check internet connectivity."
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Network error connecting to Google Drive API: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error testing Google Drive connection: {str(e)}"
            }

    @staticmethod
    def execute(project_id=None) -> Dict[str, Any]:
        """
        Discovers and lists real project documents from the configured Google Drive folder.
        """
        folder_url, service_email, api_key = GoogleDriveTool.get_credentials(project_id=project_id)

        if not api_key:
            return {
                "success": False,
                "error": "Google Drive credentials / token is missing."
            }

        try:
            bearer_token = resolve_google_access_token(api_key, service_email)
        except Exception as e:
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}"
            }

        folder_id = extract_folder_id(folder_url)
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json"
        }

        if folder_id:
            query = f"'{folder_id}' in parents and trashed = false"
        else:
            query = "trashed = false"

        files_url = "https://www.googleapis.com/drive/v3/files"
        params = {
            "q": query,
            "fields": "files(id, name, mimeType, size, modifiedTime, webViewLink, iconLink)",
            "pageSize": 100,
            "orderBy": "modifiedTime desc"
        }

        try:
            resp = requests.get(files_url, headers=headers, params=params, timeout=15)
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"Google Drive files API error (HTTP {resp.status_code}): {resp.text[:150]}"
                }

            items = resp.json().get("files", [])
            documents = []

            for item in items:
                mime = item.get("mimeType", "")
                if mime == "application/vnd.google-apps.folder":
                    continue

                size_bytes = int(item.get("size") or 0)
                if size_bytes >= 1048576:
                    size_formatted = f"{size_bytes / 1048576:.1f} MB"
                elif size_bytes >= 1024:
                    size_formatted = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes > 0:
                    size_formatted = f"{size_bytes} B"
                else:
                    if "spreadsheet" in mime:
                        size_formatted = "Google Sheet"
                    elif "document" in mime:
                        size_formatted = "Google Doc"
                    elif "presentation" in mime:
                        size_formatted = "Google Slides"
                    else:
                        size_formatted = "Cloud File"

                documents.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "size": size_formatted,
                    "bytes": size_bytes,
                    "last_modified": (item.get("modifiedTime") or "")[:10],
                    "mime_type": mime,
                    "web_view_link": item.get("webViewLink", ""),
                    "source": "Google Drive"
                })

            return {
                "success": True,
                "provider": "google_drive",
                "folder": folder_url,
                "documents": documents
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to fetch documents from Google Drive: {str(e)}"
            }

    @staticmethod
    def sync_project_drive(project_id: int) -> Dict[str, Any]:
        """
        Synchronizes live documents from Google Drive and registers them in the database for this project.
        """
        import db
        from models.uploaded_document import UploadedDocument
        from models.project import Project

        if not db.db_session:
            return {"success": False, "error": "Database session not available"}

        proj = db.db_session.query(Project).filter_by(id=project_id).first()
        if not proj:
            return {"success": False, "error": f"Project ID {project_id} not found"}

        fetch_res = GoogleDriveTool.execute(project_id=project_id)
        if not fetch_res.get("success"):
            return {
                "success": False,
                "error": fetch_res.get("error", "Failed to retrieve documents from Google Drive.")
            }

        docs = fetch_res.get("documents", [])
        synced_count = 0

        for d in docs:
            fname = d.get("name")
            if not fname:
                continue

            existing = db.db_session.query(UploadedDocument).filter_by(
                project_id=proj.id,
                filename=fname
            ).first()

            if not existing:
                ext = fname.split('.')[-1] if '.' in fname else 'gdoc'
                new_doc = UploadedDocument(
                    project_id=proj.id,
                    filename=fname,
                    file_type=ext,
                    file_size_bytes=d.get("bytes") or 1024,
                    file_size_formatted=d.get("size", "1.0 MB"),
                    uploaded_by="Google Drive Sync Agent",
                    uploaded_by_role="Live Google Drive Connector",
                    status="Indexed in Vector Memory",
                    risks_detected=0
                )
                db.db_session.add(new_doc)
                synced_count += 1

        db.db_session.commit()

        if len(docs) == 0:
            return {
                "success": True,
                "project_id": proj.id,
                "project_name": proj.name,
                "total_files_discovered": 0,
                "new_documents_synced": 0,
                "message": f"Connected to Google Drive successfully, but no files were found in the specified folder."
            }

        return {
            "success": True,
            "project_id": proj.id,
            "project_name": proj.name,
            "total_files_discovered": len(docs),
            "new_documents_synced": synced_count,
            "message": f"Successfully synchronized {synced_count} new document(s) (out of {len(docs)} found in Google Drive) into Project [{proj.jira_key}]."
        }
