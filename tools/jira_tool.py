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
        Resolves Jira credentials:
        1. If project_id provided, strictly queries DB IntegrationSetting for that project_id where is_connected=True.
           No fallback to .env or other projects.
        2. If project_id is None, queries the first connected IntegrationSetting.
        """
        import db
        from models.integration_setting import IntegrationSetting

        if not db.db_session:
            return '', '', ''

        try:
            if project_id:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=project_id, is_connected=True).first()
            else:
                setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira', is_connected=True).first()
        except Exception:
            setting = None

        if setting and setting.base_url and setting.is_connected:
            return str(setting.base_url or '').strip(), str(setting.username_email or '').strip(), str(setting.api_token or '').strip()

        return '', '', ''

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
                        "description": "The Jira project key (e.g., PSSM, KAN, PAY)"
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
    def test_connection(project_id=None, base_url=None, username_email=None, api_token=None) -> Dict[str, Any]:
        """
        Tests connection to Jira Cloud using live Atlassian REST API (/rest/api/3/myself).
        """
        import requests
        from requests.auth import HTTPBasicAuth
        
        if base_url and username_email and api_token:
            jira_url, jira_email, jira_token = base_url, username_email, api_token
        else:
            jira_url, jira_email, jira_token = JiraTool.get_credentials(project_id=project_id)
            if not jira_url:
                import db
                from models.integration_setting import IntegrationSetting
                if db.db_session and project_id:
                    s = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=project_id).first()
                    if s and s.base_url:
                        jira_url, jira_email, jira_token = s.base_url, s.username_email, s.api_token

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
                    "avatar": avatar_url,
                    "account_id": user_info.get("accountId")
                }
            else:
                return {
                    "success": False,
                    "error": f"Authentication failed (HTTP {response.status_code}): {response.text[:200]}"
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
                "error": "Jira connector is not connected for this project.",
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
            clean_key = project_key.split('-')[0].strip().upper() if project_key else ""
            p_res = requests.get(f"{base_url}/rest/api/3/project/search", headers=headers, auth=auth, timeout=10)
            
            target_key = None
            if p_res.status_code == 200:
                available_projects = p_res.json().get("values", [])
                available_keys = [p.get("key", "").upper() for p in available_projects]
                if clean_key in available_keys:
                    target_key = clean_key
                else:
                    # Match by full key or project name if possible
                    for p in available_projects:
                        if p.get("key", "").upper() == project_key.upper():
                            target_key = p.get("key")
                            break

            if not target_key:
                return {
                    "success": True,
                    "project": project_key,
                    "issues": [],
                    "metrics": {"total_issues": 0, "sprint_burndown": "No Tickets"}
                }

            # Query real Jira issues strictly for this target project
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
    def create_issue(project_key: str, summary: str, description: str = "", issue_type: str = "Task", priority: str = "Medium", project_id=None, project_name=None) -> Dict[str, Any]:
        """
        Creates a live issue directly in Jira Cloud.
        If the project does not exist on Jira Cloud, dynamically creates the project on Jira first!
        """
        import re
        import requests
        from requests.auth import HTTPBasicAuth
        import db
        from models.project import Project
        
        jira_url, jira_email, jira_token = JiraTool.get_credentials(project_id=project_id)
        
        if not jira_url or not jira_email or not jira_token:
            return {
                "success": False, 
                "error": "Jira Cloud is not connected for this project. Please configure credentials in Connectors Hub."
            }

        try:
            base_url = jira_url.rstrip('/')
            auth = HTTPBasicAuth(jira_email, jira_token)
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            clean_proj = project_key.split('-')[0].strip().upper() if project_key else ""
            if not clean_proj:
                clean_proj = "PRJ"

            # Check available projects in Jira instance
            search_proj_url = f"{base_url}/rest/api/3/project/search"
            proj_res = requests.get(search_proj_url, headers=headers, auth=auth, timeout=10)
            
            target_key = None
            existing_projects = []
            if proj_res.status_code == 200:
                existing_projects = proj_res.json().get("values", [])
                for p in existing_projects:
                    pkey = p.get("key", "").upper()
                    pname = p.get("name", "").lower()
                    if clean_proj == pkey or (project_name and project_name.lower() == pname):
                        target_key = pkey
                        break

            # If project does NOT exist in Jira Cloud, DYNAMICALLY CREATE IT ON THE FLY!
            if not target_key:
                logger.info(f"Project '{project_key}' does not exist on Jira Cloud. Dynamically creating it...")
                # 1. Fetch current lead accountId
                myself_res = requests.get(f"{base_url}/rest/api/3/myself", headers=headers, auth=auth, timeout=10)
                lead_id = None
                if myself_res.status_code == 200:
                    lead_id = myself_res.json().get("accountId")

                # 2. Sanitize project key (must be 2-10 uppercase letters)
                candidate_key = re.sub(r'[^A-Z]', '', clean_proj)
                if len(candidate_key) < 2 and project_name:
                    words = project_name.split()
                    candidate_key = ''.join([w[0].upper() for w in words if w])[:6]
                if len(candidate_key) < 2:
                    candidate_key = (candidate_key + "PRJ")[:4]

                # Ensure uniqueness against existing keys
                existing_keys = [p.get("key", "").upper() for p in existing_projects]
                unique_key = candidate_key
                counter = 1
                while unique_key in existing_keys and counter < 100:
                    unique_key = f"{candidate_key[:8]}{counter}"
                    counter += 1

                resolved_name = project_name or f"Project {unique_key}"
                create_proj_payload = {
                    "key": unique_key,
                    "name": resolved_name,
                    "projectTypeKey": "software",
                    "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
                    "description": f"Managed via VPM Enterprise Governance Suite",
                    "assigneeType": "PROJECT_LEAD"
                }
                if lead_id:
                    create_proj_payload["leadAccountId"] = lead_id

                new_proj_res = requests.post(f"{base_url}/rest/api/3/project", headers=headers, auth=auth, json=create_proj_payload, timeout=15)
                if new_proj_res.status_code in (200, 201):
                    new_proj_data = new_proj_res.json()
                    target_key = new_proj_data.get("key") or unique_key
                    logger.info(f"Successfully dynamically created Jira project: {target_key}")
                    # Update local database project record with the established key
                    if project_id and db.db_session:
                        try:
                            local_p = db.db_session.query(Project).filter_by(id=project_id).first()
                            if local_p:
                                local_p.jira_key = target_key
                                db.db_session.commit()
                        except Exception as update_err:
                            logger.warning(f"Could not update local project jira_key: {update_err}")
                else:
                    err_txt = new_proj_res.text[:250]
                    logger.error(f"Dynamic Jira project creation failed (HTTP {new_proj_res.status_code}): {err_txt}")
                    return {
                        "success": False,
                        "error": f"Failed to dynamically create Jira project '{unique_key}' on Jira Cloud: {err_txt}"
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
                    "project_key": target_key,
                    "message": f"Successfully raised live Jira ticket {issue_key} in project {target_key}"
                }
            else:
                logger.error(f"Jira issue creation failed (HTTP {resp.status_code}): {resp.text[:300]}")
                return {
                    "success": False,
                    "error": f"Jira issue creation failed (HTTP {resp.status_code}): {resp.text[:250]}"
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

            search_url = f"{base_url}/rest/api/3/project/search"
            response = requests.get(search_url, headers=headers, auth=auth, timeout=10)

            if response.status_code != 200:
                logger.error(f"Failed to fetch projects from Jira (HTTP {response.status_code}): {response.text[:200]}")
                return {
                    "success": False,
                    "error": f"Jira API HTTP {response.status_code}"
                }

            projects_data = response.json().get("values", [])
            synced_projects = 0
            synced_programs = 0

            for proj in projects_data:
                proj_name = proj.get("name")
                proj_key = proj.get("key")
                
                if not proj_name or not proj_key:
                    continue

                # Do not auto-create projects from Jira. Only user-created projects are tracked.
                project = db.db_session.query(Project).filter_by(jira_key=proj_key).first()
                if not project:
                    continue
                else:
                    if project.name != proj_name:
                        project.name = proj_name
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


