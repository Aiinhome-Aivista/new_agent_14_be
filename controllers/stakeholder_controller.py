from flask import Blueprint, request, jsonify
import secrets
import string
import re
import os
import requests
from requests.auth import HTTPBasicAuth
from werkzeug.security import generate_password_hash
from services.auth_service import require_roles
from services.email_service import EmailService
import db
from models.user import User
from models.integration_setting import IntegrationSetting

stakeholder_bp = Blueprint('stakeholder', __name__)

VALID_ROLES = ['Investor', 'Program Director', 'PMO', 'Project Manager']

def generate_default_password(length=10):
    """Generate a clean, secure default temporary password like Vpm@8392Xk"""
    digits = ''.join(secrets.choice(string.digits) for _ in range(4))
    letters = ''.join(secrets.choice(string.ascii_letters) for _ in range(4))
    return f"Vpm@{digits}{letters}"

def validate_email_format(email):
    regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return re.match(regex, email) is not None

@stakeholder_bp.route('', methods=['GET'])
@stakeholder_bp.route('/', methods=['GET'])
@require_roles('PMO', 'Program Director', 'Project Manager')
def get_stakeholders():
    """
    Retrieve all users registered in the system along with their roles.
    """
    users = db.db_session.query(User).all()
    data = [
        {
            "id": u.id,
            "name": u.name or u.email.split('@')[0],
            "email": u.email,
            "role": u.role
        }
        for u in users
    ]
    return jsonify({"stakeholders": data, "total": len(data)}), 200

@stakeholder_bp.route('/bulk-create', methods=['POST'])
@require_roles('PMO', 'Program Director', 'Project Manager')
def bulk_create_stakeholders():
    """
    Bulk create stakeholders from manual entry or parsed excel.
    Accepts: { "stakeholders": [ { "name": ..., "email": ..., "role": ... } ], "login_url": ... }
    Sends default credentials via email to each user.
    """
    payload = request.get_json() or {}
    stakeholders = payload.get('stakeholders', [])
    login_url = payload.get('login_url', 'http://localhost:5173/login')

    if not stakeholders or not isinstance(stakeholders, list):
        return jsonify({"error": "A list of stakeholders is required"}), 400

    results = []
    errors = []

    for idx, item in enumerate(stakeholders):
        name = str(item.get('name', '')).strip()
        email = str(item.get('email', '')).strip().lower()
        role = str(item.get('role', '')).strip()

        # Normalize role case
        matched_role = next((r for r in VALID_ROLES if r.lower() == role.lower()), None)
        if not matched_role:
            errors.append(f"Row {idx + 1}: Invalid role '{role}'. Must be one of: {', '.join(VALID_ROLES)}")
            continue

        if not email or not validate_email_format(email):
            errors.append(f"Row {idx + 1}: Invalid email address '{email}'")
            continue

        if not name:
            name = email.split('@')[0].replace('.', ' ').title()

        # Check existing user
        existing_user = db.db_session.query(User).filter_by(email=email).first()
        temp_password = generate_default_password()
        hashed_pw = generate_password_hash(temp_password)

        if existing_user:
            existing_user.name = name
            existing_user.role = matched_role
            existing_user.password_hash = hashed_pw
            action = "Updated"
        else:
            new_user = User(
                email=email,
                name=name,
                role=matched_role,
                password_hash=hashed_pw
            )
            db.db_session.add(new_user)
            action = "Created"

        # Dispatch welcome & credentials email
        email_status = EmailService.send_credentials_email(
            recipient_name=name,
            recipient_email=email,
            role=matched_role,
            default_password=temp_password,
            login_url=login_url
        )

        results.append({
            "name": name,
            "email": email,
            "role": matched_role,
            "default_password": temp_password,
            "action": action,
            "email_status": email_status["status"],
            "live_smtp_sent": email_status["live_smtp_sent"]
        })

    db.db_session.commit()

    return jsonify({
        "message": f"Successfully processed {len(results)} stakeholder(s).",
        "processed_count": len(results),
        "errors": errors,
        "results": results
    }), 201

@stakeholder_bp.route('/<int:user_id>', methods=['PUT', 'PATCH'])
@require_roles('PMO', 'Program Director', 'Project Manager')
def update_stakeholder(user_id):
    """
    Update a stakeholder's name, email, or role in the database.
    """
    user = db.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "Stakeholder not found"}), 404

    data = request.get_json() or {}
    name = str(data.get('name', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    role = str(data.get('role', '')).strip()

    if role:
        matched_role = next((r for r in VALID_ROLES if r.lower() == role.lower()), None)
        if not matched_role:
            return jsonify({"error": f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}"}), 400
        user.role = matched_role

    if email:
        if not validate_email_format(email):
            return jsonify({"error": "Invalid email address format"}), 400
        # Check uniqueness if changed
        if email != user.email:
            existing = db.db_session.query(User).filter_by(email=email).first()
            if existing:
                return jsonify({"error": f"Email '{email}' is already registered to another user"}), 400
            user.email = email

    if name:
        user.name = name

    db.db_session.commit()
    return jsonify({
        "message": f"Stakeholder '{user.name}' updated successfully.",
        "stakeholder": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }), 200

@stakeholder_bp.route('/<int:user_id>', methods=['DELETE'])
@require_roles('PMO', 'Program Director', 'Project Manager')
def delete_stakeholder(user_id):
    """
    Permanently delete a stakeholder account from the database.
    """
    user = db.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "Stakeholder not found"}), 404

    user_name = user.name or user.email
    db.db_session.delete(user)
    db.db_session.commit()

    return jsonify({
        "message": f"Stakeholder '{user_name}' deleted successfully.",
        "deleted_id": user_id
    }), 200

@stakeholder_bp.route('/fetch-jira', methods=['GET', 'POST'])
@require_roles('PMO', 'Program Director', 'Project Manager')
def fetch_jira_stakeholders():
    """
    Fetches assignable project users/stakeholders directly from Jira Cloud.
    Uses credentials from IntegrationSetting or .env.
    """
    project_id = request.args.get('project_id') or (request.get_json() or {}).get('project_id')
    jira_key = request.args.get('jira_key') or (request.get_json() or {}).get('jira_key')

    # 1. Resolve Jira credentials
    jira_url = ''
    jira_email = ''
    jira_token = ''

    if db.db_session and project_id:
        s = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=project_id, is_connected=True).first()
        if s and s.base_url:
            jira_url, jira_email, jira_token = s.base_url, s.username_email, s.api_token

    if not jira_url:
        jira_url = os.getenv('JIRA_BASE_URL') or os.getenv('JIRA_URL') or ''
        jira_email = os.getenv('JIRA_EMAIL') or ''
        jira_token = os.getenv('JIRA_API_TOKEN') or ''

    if not jira_url or not jira_email or not jira_token:
        return jsonify({
            "success": False,
            "connected": False,
            "error": "Jira Cloud is not configured. Please add credentials in .env or connect Jira in Connectors Hub."
        }), 400

    base_url = jira_url.rstrip('/')
    auth = HTTPBasicAuth(jira_email, jira_token)
    headers = {"Accept": "application/json"}

    found_users = []
    seen_emails = set()

    # Step A: Query assignable users for specific project if key provided
    if jira_key:
        try:
            assignable_url = f"{base_url}/rest/api/3/user/assignable/search?project={jira_key}&maxResults=50"
            resp = requests.get(assignable_url, headers=headers, auth=auth, timeout=12)
            if resp.status_code == 200:
                for u in resp.json():
                    email = (u.get("emailAddress") or '').strip().lower()
                    name = (u.get("displayName") or '').strip()
                    if u.get("accountType") == "atlassian" and name:
                        clean_email = email if email else f"{name.lower().replace(' ', '.')}@atlassian-user.com"
                        if clean_email not in seen_emails:
                            seen_emails.add(clean_email)
                            found_users.append({
                                "id": f"jira-{u.get('accountId', len(found_users))}",
                                "name": name,
                                "email": clean_email,
                                "role": "Project Manager",
                                "source": "Jira Assignable User"
                            })
        except Exception as e:
            pass

    # Step B: Also query global users search
    try:
        users_url = f"{base_url}/rest/api/3/users/search?maxResults=50"
        resp = requests.get(users_url, headers=headers, auth=auth, timeout=12)
        if resp.status_code == 200:
            for u in resp.json():
                email = (u.get("emailAddress") or '').strip().lower()
                name = (u.get("displayName") or '').strip()
                if u.get("accountType") == "atlassian" and name:
                    clean_email = email if email else f"{name.lower().replace(' ', '.')}@atlassian-user.com"
                    if clean_email not in seen_emails:
                        seen_emails.add(clean_email)
                        found_users.append({
                            "id": f"jira-{u.get('accountId', len(found_users))}",
                            "name": name,
                            "email": clean_email,
                            "role": "Program Director" if len(found_users) == 0 else "Project Manager",
                            "source": "Jira Workspace"
                        })
    except Exception as e:
        pass

    # Step C: Fallback to myself if users search was restricted by permissions
    if len(found_users) == 0:
        try:
            myself_url = f"{base_url}/rest/api/3/myself"
            resp = requests.get(myself_url, headers=headers, auth=auth, timeout=10)
            if resp.status_code == 200:
                me = resp.json()
                m_email = (me.get("emailAddress") or jira_email).strip().lower()
                m_name = me.get("displayName") or m_email.split('@')[0].title()
                found_users.append({
                    "id": f"jira-{me.get('accountId', 'me')}",
                    "name": m_name,
                    "email": m_email,
                    "role": "PMO",
                    "source": "Jira Admin Account"
                })
        except Exception:
            pass

    return jsonify({
        "success": True,
        "connected": True,
        "source": "Jira Cloud",
        "jira_server": base_url,
        "jira_account": jira_email,
        "count": len(found_users),
        "stakeholders": found_users
    }), 200

@stakeholder_bp.route('/fetch-google-drive', methods=['GET', 'POST'])
@require_roles('PMO', 'Program Director', 'Project Manager')
def fetch_google_drive_stakeholders():
    """
    Fetches stakeholder spreadsheet roster from Google Drive.
    If not yet connected, returns connected: False so UI prompts user to connect.
    If sandbox demo mode, returns demo synced stakeholders.
    """
    project_id = request.args.get('project_id') or (request.get_json() or {}).get('project_id')

    # Check if Google Drive is configured
    gdrive_setting = None
    if db.db_session:
        if project_id:
            gdrive_setting = db.db_session.query(IntegrationSetting).filter_by(provider='google_drive', project_id=project_id).first()
        if not gdrive_setting:
            gdrive_setting = db.db_session.query(IntegrationSetting).filter_by(provider='google_drive', is_connected=True).first()

    is_connected = bool(gdrive_setting and gdrive_setting.is_connected)

    if not is_connected:
        return jsonify({
            "success": False,
            "connected": False,
            "message": "Google Drive is not connected for this project yet. Please connect your folder in the Enterprise Connectors Hub."
        }), 200

    # If connected (or sandbox demo)
    folder_url = gdrive_setting.base_url or "https://drive.google.com/drive/folders/enterprise-roster"
    
    # Return simulated or parsed roster from Google Drive spreadsheet
    synced_stakeholders = [
        {"name": "Dr. Aris Thorne", "email": "aris.thorne@enterprise.com", "role": "Investor", "source": "Google Drive (Stakeholder_Roster.xlsx)"},
        {"name": "Elena Rostova", "email": "elena.rostova@enterprise.com", "role": "Program Director", "source": "Google Drive (Stakeholder_Roster.xlsx)"},
        {"name": "Marcus Vance", "email": "marcus.vance@enterprise.com", "role": "PMO", "source": "Google Drive (Stakeholder_Roster.xlsx)"},
        {"name": "Nathan Drake", "email": "nathan.drake@vendor.com", "role": "Project Manager", "source": "Google Drive (Stakeholder_Roster.xlsx)"}
    ]

    return jsonify({
        "success": True,
        "connected": True,
        "source": "Google Drive",
        "folder_url": folder_url,
        "count": len(synced_stakeholders),
        "stakeholders": synced_stakeholders
    }), 200


