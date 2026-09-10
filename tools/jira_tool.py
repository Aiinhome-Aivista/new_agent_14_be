import logging
import os
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class JiraTool:
    """
    Production-ready Jira Cloud integration using Atlassian REST API v3.
    Directly creates, syncs, and reads live tickets on Jira Cloud.
    """
    
    @staticmethod
    def get_credentials():
        """
        Resolves Jira credentials with priority:
        1. DB IntegrationSetting (configured by user in Connectors UI)
        2. Config / .env defaults
        """
        import db
        from models.integration_setting import IntegrationSetting
        from config import Config

        setting = None
        if db.db_session:
            try:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
            except Exception:
                setting = None

        env_url = getattr(Config, 'JIRA_URL', None) or os.getenv('JIRA_URL') or os.getenv('JIRA_BASE_URL') or 'https://dipakkrsaha44.atlassian.net'
        env_email = getattr(Config, 'JIRA_EMAIL', None) or os.getenv('JIRA_EMAIL') or 'dipakkrsaha44@gmail.com'
        env_token = getattr(Config, 'JIRA_API_TOKEN', None) or os.getenv('JIRA_API_TOKEN') or 'ATATT3xFfGF0o2M-o3hxSh4XCKwBcrLO5EvrYYVjZ-DO60zGU6LuMpqMext-Uwy664taZSs1uS8ifdZaIHboUlaG1gKf5C_1rp6tUhYGt7S1G39ramjutsJwM9RrvvXG71mDV9nfXgRk8gcyPG3YBp1DMgYHOfaxkDJGQ0JQo63jr92dgdpGHIs=07F60D9C'

        jira_url = (setting.base_url if setting and setting.base_url else None) or env_url
        jira_email = (setting.username_email if setting and setting.username_email else None) or env_email
        jira_token = (setting.api_token if setting and setting.api_token else None) or env_token

        return str(jira_url).strip(), str(jira_email).strip(), str(jira_token).strip()

    @staticmethod
    def get_schema() -> Dict[str, Any]:
        """
        Returns the JSON schema describing this tool's inputs and outputs.
        """
        return {
            "name": "fetch_jira_issues",
            "description": "Fetches live issues, status, and sprint burndown from Jira Cloud for a given project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {
                        "type": "string",
                        "description": "The Jira project key (e.g., PSSM, KAN)"
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by issue status (e.g., 'To Do', 'In Progress', 'Done')",
                        "default": "all"
                    }
                },
                "required": ["project_key"]
            }
        }
        
    @staticmethod
    def test_connection() -> Dict[str, Any]:
        """
        Tests connection to Jira Cloud using live Atlassian REST API (/rest/api/3/myself).
        """
        import requests
        from requests.auth import HTTPBasicAuth
        
        jira_url, jira_email, jira_token = JiraTool.get_credentials()
        
        if not jira_url or not jira_email or not jira_token:
            return {
                "success": False, 
                "error": "Jira URL, Email, or API Token is missing. Please configure credentials."
            }

        try:
            base_url = jira_url.rstrip('/')
            url = f"{base_url}/rest/api/3/myself"
            headers = {"Accept": "application/json"}
            auth = HTTPBasicAuth(jira_email, jira_token)
            
            response = requests.get(url, headers=headers, auth=auth, timeout=10)
            if response.status_code == 200:
                user_info = response.json()
                display_name = user_info.get("displayName") or user_info.get("emailAddress") or jira_email
                return {
                    "success": True,
                    "server": base_url,
                    "user": display_name
                }
            else:
                return {
                    "success": False,
                    "error": f"Jira authentication returned HTTP {response.status_code}: {response.text[:200]}"
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute(project_key: str, status: str = "all") -> Dict[str, Any]:
        """
        Executes real Jira Cloud issue fetch using Atlassian /rest/api/3/search/jql API.
        """
        import requests
        from requests.auth import HTTPBasicAuth
        
        jira_url, jira_email, jira_token = JiraTool.get_credentials()
        
        if not jira_url or not jira_email or not jira_token:
            return {
                "success": False,
                "project": project_key,
                "issues": [],
                "error": "Jira credentials not configured",
                "metrics": {
                    "total_issues": 0,
                    "sprint_burndown": "Offline"
                }
            }

        try:
            base_url = jira_url.rstrip('/')
            headers = {"Accept": "application/json"}
            auth = HTTPBasicAuth(jira_email, jira_token)

            # Discover projects in instance
            clean_key = project_key.split('-')[0].strip() if project_key else ""
            p_res = requests.get(f"{base_url}/rest/api/3/project/search", headers=headers, auth=auth, timeout=10)
            
            target_key = clean_key
            if p_res.status_code == 200:
                available_keys = [p.get("key") for p in p_res.json().get("values", [])]
                if available_keys:
                    if clean_key in available_keys:
                        target_key = clean_key
                    elif "PSSM" in available_keys:
                        target_key = "PSSM"
                    else:
                        target_key = available_keys[0]

            if not target_key:
                return {
                    "success": True,
                    "project": project_key,
                    "issues": [],
                    "metrics": {"total_issues": 0, "sprint_burndown": "No Projects"}
                }

            # Query real Jira issues
            jql = f'project = "{target_key}"'
            if status != "all":
                jql += f' AND status = "{status}"'
            jql += ' ORDER BY created DESC'

            search_url = f"{base_url}/rest/api/3/search/jql"
            response = requests.get(
                search_url,
                headers=headers,
                auth=auth,
                params={"jql": jql, "maxResults": 50, "fields": "key,summary,status,priority"},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                issues = []
                for issue in data.get("issues", []):
                    fields = issue.get("fields") or {}
                    issues.append({
                        "id": issue.get("key"),
                        "summary": fields.get("summary", ""),
                        "status": (fields.get("status") or {}).get("name", "Open"),
                        "priority": (fields.get("priority") or {}).get("name", "Medium")
                    })
                    
                return {
                    "success": True,
                    "project": target_key,
                    "issues": issues,
                    "metrics": {
                        "total_issues": len(issues),
                        "sprint_burndown": f"Live Synchronized ({len(issues)} tickets)"
                    }
                }
            else:
                logger.warning(f"Jira search API returned HTTP {response.status_code}: {response.text[:200]}")
                return {
                    "success": False,
                    "project": target_key,
                    "issues": [],
                    "error": f"Jira API HTTP {response.status_code}: {response.text[:200]}",
                    "metrics": {
                        "total_issues": 0,
                        "sprint_burndown": "Sync Failed"
                    }
                }
        except Exception as e:
            logger.error(f"Failed to fetch live Jira issues: {e}")
            return {
                "success": False,
                "project": project_key,
                "issues": [],
                "error": str(e),
                "metrics": {
                    "total_issues": 0,
                    "sprint_burndown": "Error"
                }
            }

    @staticmethod
    def create_issue(project_key: str, summary: str, description: str = "", issue_type: str = "Task", priority: str = "Medium") -> Dict[str, Any]:
        """
        Creates a live issue directly in Jira Cloud via Atlassian REST API v3.
        """
        import requests
        from requests.auth import HTTPBasicAuth
        
        jira_url, jira_email, jira_token = JiraTool.get_credentials()
        
        if not jira_url or not jira_email or not jira_token:
            return {
                "success": False, 
                "error": "Jira credentials not configured. Please set URL, Email, and API Token."
            }

        try:
            base_url = jira_url.rstrip('/')
            auth = HTTPBasicAuth(jira_email, jira_token)
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            clean_proj = project_key.split('-')[0].strip() if project_key else ""

            # Check available projects in Jira instance
            search_proj_url = f"{base_url}/rest/api/3/project/search"
            proj_res = requests.get(search_proj_url, headers=headers, auth=auth, timeout=10)
            
            target_key = clean_proj
            if proj_res.status_code == 200:
                p_data = proj_res.json()
                projs = p_data.get("values", [])
                if projs:
                    existing_keys = [p.get("key") for p in projs]
                    if clean_proj in existing_keys:
                        target_key = clean_proj
                    elif "PSSM" in existing_keys and ("migration" in summary.lower() or "sap" in summary.lower() or "alpha" in summary.lower()):
                        target_key = "PSSM"
                    elif "PSSM" in existing_keys:
                        target_key = "PSSM"
                    else:
                        target_key = existing_keys[0]
                else:
                    return {
                        "success": False,
                        "error": "No projects exist on your Jira Cloud instance. Please create a project (e.g., PSSM or KAN) first."
                    }
            else:
                return {
                    "success": False,
                    "error": f"Failed to query Jira projects (HTTP {proj_res.status_code}): {proj_res.text[:200]}"
                }

            # Map issue type: Bug for Critical / High, Task for others
            target_issue_type = "Bug" if priority in ("Critical", "High") or issue_type == "Bug" else "Task"

            # Build Atlassian Document Format (ADF) payload
            create_url = f"{base_url}/rest/api/3/issue"
            full_description = description.strip() if description else summary

            payload = {
                "fields": {
                    "project": {"key": target_key},
                    "summary": summary[:250],
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": full_description
                                    }
                                ]
                            }
                        ]
                    },
                    "issuetype": {"name": target_issue_type}
                }
            }
            
            resp = requests.post(create_url, headers=headers, auth=auth, json=payload, timeout=12)
            
            # If Bug fails due to project schema constraints, fallback to Task
            if resp.status_code not in (200, 201) and target_issue_type != "Task":
                payload["fields"]["issuetype"]["name"] = "Task"
                resp = requests.post(create_url, headers=headers, auth=auth, json=payload, timeout=12)

            if resp.status_code in (200, 201):
                created_data = resp.json()
                issue_key = created_data.get("key")
                issue_id = created_data.get("id")
                return {
                    "success": True,
                    "key": issue_key,
                    "id": issue_id,
                    "url": f"{base_url}/browse/{issue_key}",
                    "message": f"Successfully raised live Jira ticket {issue_key} in project {target_key}"
                }
            else:
                logger.error(f"Jira issue creation failed (HTTP {resp.status_code}): {resp.text[:300]}")
                return {
                    "success": False,
                    "error": f"Jira API rejected ticket creation (HTTP {resp.status_code}): {resp.text[:250]}"
                }
        except Exception as e:
            logger.error(f"Failed to create live Jira issue: {e}")
            return {
                "success": False,
                "error": f"Failed to connect to Jira Cloud: {str(e)}"
            }
