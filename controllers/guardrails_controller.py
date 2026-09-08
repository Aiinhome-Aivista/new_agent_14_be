from flask import Blueprint, jsonify, request
from datetime import datetime, timezone
import db
from models.approval_queue import ApprovalQueue
from models.agent_run_log import AgentRunLog
from models.guardrail_policy import GuardrailPolicy
from services.auth_service import require_roles

guardrails_bp = Blueprint('guardrails', __name__)

DEFAULT_POLICIES = [
    {
        "policy_id": "POL-001",
        "name": "Input Schema Enforcement",
        "category": "Data Integrity",
        "description": "All agent input payloads must conform to strict Pydantic models before execution.",
        "status": "Active",
        "level": "Strict"
    },
    {
        "policy_id": "POL-002",
        "name": "Output Structure Validation",
        "category": "Safety & Format",
        "description": "Validates that LLM JSON output satisfies target agent schemas; rejects malformed output.",
        "status": "Active",
        "level": "Strict"
    },
    {
        "policy_id": "POL-003",
        "name": "Risk Escalation Threshold",
        "category": "Human-in-the-Loop",
        "description": "Risks with Critical severity or confidence scores below 70% automatically route to PMO approval queue.",
        "status": "Active",
        "level": "High"
    },
    {
        "policy_id": "POL-004",
        "name": "Budget Variance Guardrail",
        "category": "Financial Controls",
        "description": "Calculates variance and flags trajectories exceeding 10% budget burn deviation.",
        "status": "Active",
        "level": "Warning"
    },
    {
        "policy_id": "POL-005",
        "name": "Prompt Injection Mitigation",
        "category": "Security",
        "description": "Sanitizes raw document text and system prompts before model invocation.",
        "status": "Active",
        "level": "Strict"
    }
]

def ensure_default_policies():
    """Seeds default policies in DB if table is currently empty."""
    try:
        count = db.db_session.query(GuardrailPolicy).count()
        if count == 0:
            for p in DEFAULT_POLICIES:
                pol = GuardrailPolicy(
                    policy_id=p["policy_id"],
                    name=p["name"],
                    category=p["category"],
                    description=p["description"],
                    status=p["status"],
                    level=p["level"]
                )
                db.db_session.add(pol)
            db.db_session.commit()
    except Exception as e:
        db.db_session.rollback()

@guardrails_bp.route('', methods=['GET'])
@guardrails_bp.route('/', methods=['GET'])
def get_guardrails():
    # Ensure default policies exist in DB
    ensure_default_policies()
    
    # Query persistent policies from DB
    policies = db.db_session.query(GuardrailPolicy).order_by(GuardrailPolicy.id.asc()).all()
    policy_data = [p.to_dict() for p in policies]

    # Fetch real approval queue entries
    queue_items = db.db_session.query(ApprovalQueue).order_by(ApprovalQueue.created_at.desc()).all()
    queue_data = [item.to_dict() for item in queue_items]
    
    # Fetch recent run audit logs
    run_logs = db.db_session.query(AgentRunLog).order_by(AgentRunLog.created_at.desc()).limit(10).all()
    audit_data = [log.to_dict() for log in run_logs]
    
    return jsonify({
        "policies": policy_data,
        "approval_queue": queue_data,
        "audits": audit_data,
        "stats": {
            "active_policies": len(policy_data),
            "pending_approvals": len([q for q in queue_data if q.get("status") == "Pending"]),
            "total_audits": len(audit_data)
        }
    })

@guardrails_bp.route('/queue/<int:item_id>/resolve', methods=['POST'])
@require_roles('Program Director', 'PMO')
def resolve_queue_item(item_id):
    data = request.json or {}
    decision = data.get('decision', 'Approved') # Approved or Rejected
    reasoning = data.get('reasoning', 'Reviewed by authorized officer')
    
    item = db.db_session.query(ApprovalQueue).filter_by(id=item_id).first()
    if not item:
        return jsonify({"error": "Queue item not found"}), 404
        
    item.status = decision
    item.reasoning = reasoning
    item.resolved_at = datetime.now(timezone.utc)
    db.db_session.commit()
    
    return jsonify({"success": True, "item": item.to_dict()})

@guardrails_bp.route('/policies', methods=['POST'])
@require_roles('Program Director', 'PMO')
def create_policy():
    data = request.json or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "Policy name required"}), 400
        
    ensure_default_policies()
    
    total_count = db.db_session.query(GuardrailPolicy).count()
    policy_id = f"POL-{total_count + 1:03d}"
    
    new_policy = GuardrailPolicy(
        policy_id=policy_id,
        name=name,
        category=data.get("category", "Custom"),
        description=data.get("description", "User-defined guardrail rule"),
        status=data.get("status", "Active"),
        level=data.get("level", "Medium")
    )
    db.db_session.add(new_policy)
    db.db_session.commit()
    
    return jsonify({"success": True, "policy": new_policy.to_dict()}), 201
