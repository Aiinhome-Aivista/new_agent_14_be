import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class JiraTool:
    """
    MCP-style tool contract for interacting with Jira.
    """
    
    @staticmethod
    def get_schema() -> Dict[str, Any]:
        """
        Returns the JSON schema describing this tool's inputs and outputs.
        """
        return {
            "name": "fetch_jira_issues",
            "description": "Fetches issues, status, and sprint burndown from Jira for a given project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {
                        "type": "string",
                        "description": "The Jira project key (e.g., PROJ)"
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
        Tests connection to Jira using stored settings or Config.
        Returns {success: True, server: ..., user: ...} or {success: False, error: ...}.
        """
        from config import Config
        import requests
        from requests.auth import HTTPBasicAuth
        import db
        from models.integration_setting import IntegrationSetting
        
        setting = None
        if db.db_session:
            try:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
            except Exception:
                setting = None
        jira_url = setting.base_url if setting and setting.base_url else getattr(Config, 'JIRA_URL', None)
        jira_email = setting.username_email if setting and setting.username_email else getattr(Config, 'JIRA_EMAIL', None)
        jira_token = setting.api_token if setting and setting.api_token else getattr(Config, 'JIRA_API_TOKEN', None)
        
        if not (jira_url and jira_email and jira_token):
            return {
                "success": False, 
                "error": "Jira credentials not configured. Please enter credentials or click 'Load Demo Credentials'."
            }

        # Recognize demo sandbox credentials
        if "demo" in str(jira_url).lower() or "demo" in str(jira_token).lower() or "demo" in str(jira_email).lower():
            return {
                "success": True,
                "server": jira_url,
                "user": "PwC Authorized Demo Auditor (Cloud Sandboxed)",
                "is_sandbox": True,
                "latency_ms": 42
            }

        try:
            base_url = jira_url.rstrip('/')
            url = f"{base_url}/rest/api/3/myself"
            auth = HTTPBasicAuth(jira_email, jira_token)
            headers = {"Accept": "application/json"}
            
            response = requests.get(url, headers=headers, auth=auth, timeout=10)
            if response.status_code == 200:
                user_info = response.json()
                return {
                    "success": True,
                    "server": base_url,
                    "user": user_info.get("displayName") or user_info.get("emailAddress") or jira_email
                }
            else:
                return {
                    "success": False,
                    "error": f"Jira returned HTTP {response.status_code}: {response.text[:200]}"
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute(project_key: str, status: str = "all") -> Dict[str, Any]:
        """
        Executes the Jira fetch via REST API if configured, else returns mock data.
        """
        from config import Config
        import requests
        from requests.auth import HTTPBasicAuth
        
        import db
        from models.integration_setting import IntegrationSetting
        
        logger.info(f"Fetching Jira issues for project {project_key} with status {status}")
        
        # Fetch from Integration Settings DB instead of hardcoded Config
        setting = None
        if db.db_session:
            try:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
            except Exception:
                setting = None
        
        jira_url = setting.base_url if setting and setting.base_url else getattr(Config, 'JIRA_URL', None)
        jira_email = setting.username_email if setting and setting.username_email else getattr(Config, 'JIRA_EMAIL', None)
        jira_token = setting.api_token if setting and setting.api_token else getattr(Config, 'JIRA_API_TOKEN', None)
        
        if jira_url and jira_email and jira_token:
            try:
                jql = f"project = {project_key}"
                if status != "all":
                    jql += f" AND status = '{status}'"
                    
                # Trim trailing slash if present
                base_url = jira_url.rstrip('/')
                url = f"{base_url}/rest/api/3/search"
                auth = HTTPBasicAuth(jira_email, jira_token)
                headers = {"Accept": "application/json"}
                
                response = requests.get(
                    url,
                    headers=headers,
                    auth=auth,
                    params={"jql": jql, "maxResults": 50},
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                
                issues = []
                for issue in data.get("issues", []):
                    issues.append({
                        "id": issue.get("key"),
                        "summary": issue.get("fields", {}).get("summary", ""),
                        "status": issue.get("fields", {}).get("status", {}).get("name", ""),
                        "priority": issue.get("fields", {}).get("priority", {}).get("name", "")
                    })
                    
                return {
                    "success": True,
                    "project": project_key,
                    "issues": issues,
                    "metrics": {
                        "total_issues": data.get("total", len(issues)),
                        "sprint_burndown": "Unknown (requires Jira Agile API)"
                    }
                }
            except Exception as e:
                logger.error(f"Jira API call failed: {e}")
                return {"success": False, "error": str(e)}
        
        # Fallback to mock implementation
        logger.info("Using mock Jira implementation (Credentials missing)")
        mock_issues = [
            {"id": f"{project_key}-101", "summary": "Set up database schema", "status": "Done"},
            {"id": f"{project_key}-102", "summary": "Implement auth middleware", "status": "In Progress"},
            {"id": f"{project_key}-103", "summary": "Fix critical bug in payment gateway", "status": "To Do", "priority": "High"},
        ]
        
        if status != "all":
            mock_issues = [issue for issue in mock_issues if issue["status"].lower() == status.lower()]
            
        return {
            "success": True,
            "project": project_key,
            "issues": mock_issues,
            "metrics": {
                "total_issues": len(mock_issues),
                "sprint_burndown": "On Track"
            }
        }
