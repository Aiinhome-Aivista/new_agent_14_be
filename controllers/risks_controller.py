from flask import Blueprint, jsonify, request
import db
from models.risk_register import RiskRegister

risks_bp = Blueprint('risks', __name__)

@risks_bp.route('', methods=['GET'])
@risks_bp.route('/', methods=['GET'])
def get_risks():
    risks = db.db_session.query(RiskRegister).order_by(RiskRegister.id.asc()).all()
    result = [r.to_dict() for r in risks]
    return jsonify(result)

@risks_bp.route('/<int:risk_id>', methods=['PUT', 'PATCH'])
def update_risk(risk_id):
    risk = db.db_session.query(RiskRegister).filter_by(id=risk_id).first()
    if not risk:
        return jsonify({"success": False, "error": f"Risk with ID {risk_id} not found"}), 404

    data = request.json or {}
    if 'status' in data:
        risk.status = data['status']
    if 'owner' in data:
        risk.owner = data['owner']
    if 'mitigation_plan' in data:
        risk.mitigation_plan = data['mitigation_plan']
    if 'severity' in data:
        risk.severity = data['severity']
    if 'title' in data:
        risk.title = data['title']
    if 'description' in data:
        risk.description = data['description']

    try:
        db.db_session.commit()
        return jsonify({
            "success": True, 
            "message": f"Risk {risk.risk_id} updated successfully", 
            "risk": risk.to_dict()
        })
    except Exception as e:
        db.db_session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@risks_bp.route('/<int:risk_id>/push-to-jira', methods=['POST'])
def push_risk_to_jira(risk_id):
    risk = db.db_session.query(RiskRegister).filter_by(id=risk_id).first()
    if not risk:
        return jsonify({"success": False, "error": f"Risk with ID {risk_id} not found"}), 404
        
    from tools.jira_tool import JiraTool
    from models.project import Project
    
    proj = db.db_session.query(Project).filter_by(id=risk.project_id).first()
    jira_key = proj.jira_key if proj else "PRJ-101"
    
    issue_type = "Bug" if risk.severity in ("Critical", "High") else "Task"
    
    res = JiraTool.create_issue(
        project_key=jira_key,
        summary=f"[{risk.risk_id}] {risk.title}",
        description=f"{risk.description}\n\nMitigation Plan: {risk.mitigation_plan or 'Under PM review'}\nSeverity: {risk.severity}\nOwner: {risk.owner}",
        issue_type=issue_type,
        priority=risk.severity
    )
    
    if res.get("success"):
        jira_key_created = res.get("key")
        risk.jira_issue_key = jira_key_created
        db.db_session.commit()
        return jsonify({
            "success": True,
            "message": res.get("message") or f"Jira ticket {jira_key_created} created successfully!",
            "jira_issue_key": jira_key_created,
            "jira_url": res.get("url"),
            "risk": risk.to_dict()
        })
    else:
        return jsonify({
            "success": False,
            "error": res.get("error", "Failed to create Jira ticket")
        }), 400

@risks_bp.route('', methods=['POST'])
@risks_bp.route('/', methods=['POST'])
def create_risk():
    data = request.json or {}
    if not data.get('title'):
        return jsonify({"success": False, "error": "Title is required"}), 400

    from models.project import Project
    proj = db.db_session.query(Project).first()
    project_id = data.get('project_id') or (proj.id if proj else 1)

    import random
    new_risk = RiskRegister(
        project_id=project_id,
        risk_id=data.get('risk_id') or f"R-{random.randint(100, 999)}",
        title=data.get('title'),
        description=data.get('description', data.get('title')),
        severity=data.get('severity', 'Medium'),
        status=data.get('status', 'Open'),
        owner=data.get('owner', 'Unassigned'),
        mitigation_plan=data.get('mitigation_plan', '')
    )

    try:
        db.db_session.add(new_risk)
        db.db_session.commit()
        return jsonify({
            "success": True, 
            "message": "Risk created successfully", 
            "risk": new_risk.to_dict()
        }), 201
    except Exception as e:
        db.db_session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@risks_bp.route('/<int:risk_id>', methods=['DELETE'])
def delete_risk(risk_id):
    risk = db.db_session.query(RiskRegister).filter_by(id=risk_id).first()
    if not risk:
        return jsonify({"success": False, "error": f"Risk with ID {risk_id} not found"}), 404

    try:
        db.db_session.delete(risk)
        db.db_session.commit()
        return jsonify({"success": True, "message": f"Risk {risk_id} deleted successfully"})
    except Exception as e:
        db.db_session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
