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
    def get_credentials(project_id=None):
        """
        Resolves Jira credentials with priority:
        1. DB IntegrationSetting for specific project_id
        2. DB IntegrationSetting for project_id = 1 (default project)
        3. Config / .env defaults
        """
        import db
        from models.integration_setting import IntegrationSetting
        from config import Config

        setting = None
        if db.db_session:
            try:
                if project_id:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=project_id).first()
                if not setting:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=1).first()
                if not setting:
                    setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
            except Exception:
                setting = None

        env_url = getattr(Config, 'JIRA_URL', None) or os.getenv('JIRA_URL') or os.getenv('JIRA_BASE_URL') or 'https://dipakkrsaha44.atlassian.net'
        env_email = getattr(Config, 'JIRA_EMAIL', None) or os.getenv('JIRA_EMAIL') or 'dipakkrsaha44@gmail.com'
        env_token = getattr(Config, 'JIRA_API_TOKEN', None) or os.getenv('JIRA_API_TOKEN') or 'ATATT3xFfGF0o2M-o3hxSh4XCKwBcrLO5EvrYYVjZ-DO60zGU6LuMpqMext-Uwy664taZSs1uS8ifdZaIHboUlaG1gKf5C_1rp6tUhYGt7S1G39ramjutsJwM9RrvvXG71mDV9nfXgRk8gcyPG3YBp1DMgYHOfaxkDJGQ0JQo63jr92dgdpGHIs=07F60D9C'

        if setting and setting.base_url:
            jira_url = setting.base_url
            jira_email = setting.username_email or ''
            # Use setting.api_token; only fallback to env_token if email matches env_email
            jira_token = setting.api_token if setting.api_token else (env_token if jira_email == env_email else '')
        else:
            jira_url = env_url
            jira_email = env_email
            jira_token = env_token

        return str(jira_url or '').strip(), str(jira_email or '').strip(), str(jira_token or '').strip()

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
    def test_connection(project_id=None) -> Dict[str, Any]:
        """
        Tests connection to Jira Cloud using live Atlassian REST API (/rest/api/3/myself).
        """
        import requests
        from requests.auth import HTTPBasicAuth
        
        jira_url, jira_email, jira_token = JiraTool.get_credentials(project_id=project_id)
        
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
                avatars = user_info.get("avatarUrls") or {}
                avatar_url = avatars.get("48x48") or avatars.get("32x32") or avatars.get("24x24") or ""
                return {
                    "success": True,
                    "server": base_url,
                    "user": display_name,
                    "email": user_info.get("emailAddress") or jira_email,
                    "account_id": user_info.get("accountId"),
                    "avatar_url": avatar_url,
                    "time_zone": user_info.get("timeZone"),
                    "account_type": user_info.get("accountType")
                }
            else:
                return {
                    "success": False,
                    "error": f"Jira authentication returned HTTP {response.status_code}: {response.text[:200]}"
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute(project_key: str, status: str = "all", project_id=None) -> Dict[str, Any]:
        """
        Executes real Jira Cloud issue fetch using Atlassian /rest/api/3/search/jql API.
        """
        import requests
        from requests.auth import HTTPBasicAuth
        
        jira_url, jira_email, jira_token = JiraTool.get_credentials(project_id=project_id)
        
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

    @staticmethod
    def sync_projects_to_db() -> Dict[str, Any]:
        """
        Fetches all projects and their categories from Jira and upserts them into
        the programs and projects database tables.
        """
        import requests
        from requests.auth import HTTPBasicAuth
        import db
        from models.program import Program
        from models.project import Project

        jira_url, jira_email, jira_token = JiraTool.get_credentials()
        
        if not jira_url or not jira_email or not jira_token:
            return {
                "success": False,
                "error": "Jira credentials not configured."
            }

        if not db.db_session:
            return {
                "success": False,
                "error": "No database session available."
            }

        try:
            base_url = jira_url.rstrip('/')
            headers = {"Accept": "application/json"}
            auth = HTTPBasicAuth(jira_email, jira_token)

            search_url = f"{base_url}/rest/api/3/project/search?expand=projectCategory"
            response = requests.get(search_url, headers=headers, auth=auth, timeout=10)

            if response.status_code != 200:
                logger.error(f"Failed to fetch projects from Jira (HTTP {response.status_code}): {response.text[:200]}")
                return {
                    "success": False,
                    "error": f"Jira API HTTP {response.status_code}"
                }

            projects_data = response.json().get("values", [])
            synced_programs = 0
            synced_projects = 0

            for proj in projects_data:
                proj_name = proj.get("name")
                proj_key = proj.get("key")
                
                if not proj_name or not proj_key:
                    continue

                category = proj.get("projectCategory", {})
                category_name = category.get("name", "Jira Uncategorized Program")

                # Upsert Program
                program = db.db_session.query(Program).filter_by(name=category_name).first()
                if not program:
                    program = Program(
                        name=category_name,
                        description=category.get("description", "Imported from Jira Project Categories")
                    )
                    db.db_session.add(program)
                    db.db_session.flush() # To get program.id
                    synced_programs += 1
                
                # Upsert Project
                project = db.db_session.query(Project).filter_by(jira_key=proj_key).first()
                if not project:
                    project = Project(
                        program_id=program.id,
                        jira_key=proj_key,
                        name=proj_name,
                        status='Active'
                    )
                    db.db_session.add(project)
                    synced_projects += 1
                else:
                    if project.name != proj_name or project.program_id != program.id:
                        project.name = proj_name
                        project.program_id = program.id
                        synced_projects += 1

            db.db_session.commit()
            return {
                "success": True,
                "synced_programs": synced_programs,
                "synced_projects": synced_projects,
                "message": f"Successfully synced {synced_projects} projects and {synced_programs} programs from Jira."
            }
        except Exception as e:
            logger.error(f"Error syncing Jira projects to DB: {e}")
            if db.db_session:
                db.db_session.rollback()
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def sync_project_telemetry(project_id: int) -> Dict[str, Any]:
        """
        Synchronizes live connector data matching the specific active project.
        Fetches issues from Jira matching project_key and maps them to the project in the DB.
        """
        import db
        from models.project import Project
        from models.risk_register import RiskRegister
        import random

        if not db.db_session:
            return {"success": False, "error": "Database session not available"}

        proj = db.db_session.query(Project).filter_by(id=project_id).first()
        if not proj:
            return {"success": False, "error": f"Project ID {project_id} not found"}

        jira_key = proj.jira_key
        fetch_res = JiraTool.execute(project_key=jira_key, project_id=project_id)

        issues = fetch_res.get("issues", [])
        synced_risks = 0

        # Map critical/high issues into RiskRegister
        for iss in issues:
            priority = iss.get("priority", "Medium")
            issue_id = iss.get("id")
            if priority in ("Critical", "High") and issue_id:
                existing_risk = db.db_session.query(RiskRegister).filter_by(
                    project_id=proj.id,
                    jira_issue_key=issue_id
                ).first()

                if not existing_risk:
                    new_risk = RiskRegister(
                        project_id=proj.id,
                        risk_id=f"R-JIRA-{random.randint(100, 999)}",
                        title=iss.get("summary", f"Jira Issue {issue_id}"),
                        description=f"Auto-imported from Jira ticket {issue_id} under project {jira_key}",
                        severity=priority,
                        status="Open",
                        owner="Jira Synced",
                        mitigation_plan="Review Jira ticket in next sprint backlog refinement",
                        jira_issue_key=issue_id
                    )
                    db.db_session.add(new_risk)
                    synced_risks += 1

        db.db_session.commit()

        return {
            "success": True,
            "project_id": proj.id,
            "project_name": proj.name,
            "jira_key": jira_key,
            "total_issues_fetched": len(issues),
            "new_risks_synced": synced_risks,
            "message": f"Successfully matched and synced {len(issues)} issues for project [{jira_key}]. {synced_risks} new risks recorded in project risk register."
        }


