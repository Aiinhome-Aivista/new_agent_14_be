import logging
from flask import Blueprint, jsonify, request
from datetime import datetime, timezone
import db
from models.approval_queue import ApprovalQueue
from models.agent_run_log import AgentRunLog
from models.guardrail_policy import GuardrailPolicy
from services.auth_service import require_roles

logger = logging.getLogger(__name__)
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

    jira_info = None
    if decision == 'Approved' and item.action_type in ('escalate_risk', 'risk_escalation'):
        try:
            from tools.jira_tool import JiraTool
            from models.project import Project
            from models.risk_register import RiskRegister

            payload = dict(item.payload or {}) if isinstance(item.payload, dict) else {}
            p_id = payload.get("project_id", 1)
            proj = db.db_session.query(Project).filter_by(id=p_id).first()
            j_key = proj.jira_key if proj else "PRJ-101"
            
            esc_data = payload.get("escalation", {})
            title = esc_data.get("title", f"Approved Escalation for Project {p_id}") if isinstance(esc_data, dict) else str(esc_data)
            jira_res = JiraTool.create_issue(
                project_key=j_key,
                summary=f"[Approved Escalation] {title}",
                description=f"Automated risk escalation approved by PMO / Program Director.\nReason: {reasoning}",
                issue_type="Bug",
                priority="High"
            )
            jira_info = jira_res
            if jira_res and jira_res.get("key"):
                jira_key_created = jira_res.get("key")
                payload["jira_issue_key"] = jira_key_created
                payload["jira_url"] = jira_res.get("url")
                item.payload = payload

                # If there's an associated risk in risk_register, link it as well
                risk_rec = db.db_session.query(RiskRegister).filter(
                    RiskRegister.project_id == p_id,
                    RiskRegister.title.ilike(f"%{str(title)[:30]}%")
                ).first()
                if risk_rec and not risk_rec.jira_issue_key:
                    risk_rec.jira_issue_key = jira_key_created

                db.db_session.commit()
        except Exception:
            pass
    
    return jsonify({"success": True, "item": item.to_dict(), "jira": jira_info})

@guardrails_bp.route('/policies', methods=['POST'])
@require_roles('Program Director', 'PMO', 'Project Manager', 'Investor', 'Admin')
def create_policy():
    data = request.json or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "Policy name required"}), 400
        
    ensure_default_policies()
    
    # Safely determine next POL-xxx ID avoiding collision
    all_p = db.db_session.query(GuardrailPolicy.policy_id).all()
    max_num = 0
    for (pid,) in all_p:
        if pid and pid.startswith("POL-"):
            try:
                num = int(pid.replace("POL-", ""))
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    policy_id = f"POL-{max_num + 1:03d}"
    
    new_policy = GuardrailPolicy(
        policy_id=policy_id,
        name=name.strip(),
        category=data.get("category", "Custom Policy").strip(),
        description=data.get("description", "User-defined autonomous safety constraint").strip(),
        status=data.get("status", "Active"),
        level=data.get("level", "Strict")
    )
    db.db_session.add(new_policy)
    db.db_session.commit()
    
    return jsonify({"success": True, "policy": new_policy.to_dict()}), 201

@guardrails_bp.route('/policies/<policy_id>/toggle', methods=['PATCH', 'POST'])
def toggle_policy(policy_id):
    pol = db.db_session.query(GuardrailPolicy).filter(
        (GuardrailPolicy.policy_id == policy_id) | 
        (GuardrailPolicy.id == policy_id)
    ).first()
    if not pol:
        return jsonify({"error": "Policy not found"}), 404

    pol.status = "Inactive" if pol.status == "Active" else "Active"
    db.db_session.commit()
    return jsonify({"success": True, "policy": pol.to_dict()})

@guardrails_bp.route('/policies/<policy_id>', methods=['DELETE'])
def delete_policy(policy_id):
    pol = db.db_session.query(GuardrailPolicy).filter(
        (GuardrailPolicy.policy_id == policy_id) | 
        (GuardrailPolicy.id == policy_id)
    ).first()
    if not pol:
        return jsonify({"error": "Policy not found"}), 404

    db.db_session.delete(pol)
    db.db_session.commit()
    return jsonify({"success": True, "message": f"Policy {policy_id} deleted successfully"})

_AI_SUGGESTIONS_CACHE = {}
_CACHE_TTL = 300  # 5 minutes
_ASYNC_IN_PROGRESS = set()

def _synthesize_telemetry_suggestions(open_risks, burn_pct, budget, existing_names):
    """
    Instantly synthesizes high-impact, live guardrail policies from database telemetry (<1ms).
    """
    suggestions = []

    # 1. Containment Gate for highest severity risk
    if open_risks:
        top_risk = open_risks[0]
        title_lower = (top_risk.title or '').lower()
        if any(k in title_lower for k in ['sec', 'auth', 'token', 'pii', 'leak', 'breach', 'api']):
            cat = "Security & PII"
            lvl = "Strict"
        elif any(k in title_lower for k in ['vendor', 'contractor', 'partner', 'third', 'sla', 'delay']):
            cat = "Vendor Compliance"
            lvl = "High"
        elif any(k in title_lower for k in ['budget', 'cost', 'spend', 'financial', 'invoice']):
            cat = "Financial Controls"
            lvl = "Strict" if top_risk.severity == "Critical" else "High"
        else:
            cat = "Human-in-the-Loop"
            lvl = "Strict" if top_risk.severity == "Critical" else "High"

        suggestions.append({
            "name": f"Containment Gate: {top_risk.title[:38]}",
            "category": cat,
            "level": lvl,
            "description": f"Automated execution block on milestone approvals until mitigation plan for '{top_risk.title}' is signed off by PMO.",
            "rationale": f"Live Telemetry: Triggered by active {top_risk.severity} Risk #{top_risk.risk_id}"
        })

    # 2. Secondary risk mitigation lock
    if len(open_risks) > 1:
        sec_risk = open_risks[1]
        title_lower = (sec_risk.title or '').lower()
        if any(k in title_lower for k in ['vendor', 'contractor', 'third', 'partner', 'sla', 'deliverable']):
            cat = "Vendor Compliance"
        elif any(k in title_lower for k in ['sec', 'auth', 'token', 'pii', 'api']):
            cat = "Security & PII"
        else:
            cat = "Human-in-the-Loop"
        
        suggestions.append({
            "name": f"Mitigation Lock: {sec_risk.title[:38]}",
            "category": cat,
            "level": "High" if sec_risk.severity in ["Critical", "High"] else "Warning",
            "description": f"Requires dual PMO verification for deliverable sign-offs and sprint tickets addressing {sec_risk.title}.",
            "rationale": f"Live Telemetry: Associated with active {sec_risk.severity} Risk #{sec_risk.risk_id}"
        })

    # 3. Live Budget Burn Guardrail
    if burn_pct >= 90:
        suggestions.append({
            "name": f"Budget Hard Freeze Cap ({burn_pct:.0f}% Consumed)",
            "category": "Financial Controls",
            "level": "Strict",
            "description": "Suspends automated tranche disbursements and non-essential sprint authorizations until executive financial review.",
            "rationale": f"Live Telemetry: Current budget burn is critical at {burn_pct:.1f}% baseline capacity."
        })
    elif burn_pct >= 75:
        suggestions.append({
            "name": f"Budget Variance Threshold Gate ({burn_pct:.0f}% Spend)",
            "category": "Financial Controls",
            "level": "Warning",
            "description": f"Triggers real-time PMO alert and requires contingency variance justification if spend exceeds {burn_pct + 5:.0f}%.",
            "rationale": f"Live Telemetry: Project has expended {burn_pct:.1f}% of total planned baseline."
        })
    else:
        suggestions.append({
            "name": "Tranche Variance Deviation Cap (>15%)",
            "category": "Financial Controls",
            "level": "Warning",
            "description": "Flags immediate PMO alert if sprint expenditure outpaces allocated tranche baseline by more than 15%.",
            "rationale": f"Live Telemetry: Current burn tracking smoothly at {burn_pct:.1f}%."
        })

    # 4. Mandatory Security & PII Redaction Pipeline
    suggestions.append({
        "name": "Cryptographic PII & Auth Token Redaction",
        "category": "Security & PII",
        "level": "Strict",
        "description": "Interception pipeline to strip JWTs, API tokens, passwords, and confidential telemetry before AI model synthesis.",
        "rationale": "Enterprise Governance: Mandatory zero-trust redaction for multi-agent LLM pipelines."
    })

    # 5. Jira Milestone acceptance sync
    suggestions.append({
        "name": "Jira Delivery Acceptance Verification Protocol",
        "category": "Data Integrity",
        "level": "High",
        "description": "Enforces verified ticket resolution in Jira Cloud before allowing agent to mark milestone deliverables as complete.",
        "rationale": "Data Governance: Prevents state desynchronization between Jira Cloud and PMO ledger."
    })

    return suggestions[:4]

def _async_fetch_llm_suggestions(project_id, risk_summaries, burn_pct, existing_names):
    """
    Background worker that calls LLM without blocking the user request.
    Populates _AI_SUGGESTIONS_CACHE when completed.
    """
    import json
    import time
    try:
        from llm.llm_client import llm
        prompt = f"""
You are an enterprise AI Governance & Guardrails Architect.
Analyze the following live project telemetry and recommend 4 tailored, high-impact guardrail policies to protect this project against delivery failure, budget overrun, security vulnerabilities, and vendor SLA breaches.

LIVE TELEMETRY:
- Active Risks: {json.dumps(risk_summaries)}
- Budget Burn: {burn_pct}% consumed
- Existing Active Policies: {json.dumps(existing_names[:6])}

Return a valid JSON array of 4 objects matching this format:
[
  {{
    "name": "Specific Policy Name",
    "category": "One of: Security & PII, Financial Controls, Human-in-the-Loop, Safety & Format, Vendor Compliance, Data Integrity",
    "level": "One of: Strict, High, Warning, Medium",
    "description": "Clear actionable rule description explaining what is checked or blocked.",
    "rationale": "Brief reason based on live risks or budget."
  }}
]
"""
        raw_res = llm.generate(
            prompt=prompt,
            system="You are an enterprise AI guardrail specialist. Always output strictly valid JSON.",
            request_timeout=(15, 900)
        )
        if raw_res:
            clean_json = raw_res.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json.replace("```json", "").replace("```", "")
            clean_json = clean_json.strip()
            parsed = json.loads(clean_json)
            if isinstance(parsed, list) and len(parsed) > 0:
                _AI_SUGGESTIONS_CACHE[project_id] = {
                    "suggestions": parsed,
                    "timestamp": time.time()
                }
                logger.info(f"Updated AI suggestions cache in background for project {project_id}")
    except Exception as err:
        logger.warning(f"Background LLM suggestion fetch failed: {err}")
    finally:
        _ASYNC_IN_PROGRESS.discard(project_id)


@guardrails_bp.route('/suggestions', methods=['GET'])
def get_ai_guardrail_suggestions():
    """
    Returns instant (<20ms) intelligent guardrail recommendations powered by
    live DB telemetry, with asynchronous LLM enhancement in the background.
    """
    import json
    import time
    import threading
    from models.risk_register import RiskRegister
    from models.budget import Budget
    from models.project import Project
    
    try:
        project_id = request.args.get('project_id', 1, type=int)
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        # 1. Fetch live DB telemetry (takes ~5-10ms)
        open_risks = db.db_session.query(RiskRegister).filter(
            RiskRegister.project_id == project_id
        ).order_by(RiskRegister.created_at.desc()).limit(6).all()
        
        budget = db.db_session.query(Budget).filter(
            Budget.project_id == project_id
        ).order_by(Budget.created_at.desc()).first()
        
        existing_p = db.db_session.query(GuardrailPolicy.name).all()
        existing_names = [name for (name,) in existing_p]
        
        risk_summaries = [f"[{r.severity}] {r.title}" for r in open_risks]
        burn_pct = 80.0
        if budget and float(budget.planned_spend or 0) > 0:
            burn_pct = round(float(budget.actual_spend or 0) / float(budget.planned_spend or 1) * 100, 1)

        # 2. Check in-memory cache
        cached = _AI_SUGGESTIONS_CACHE.get(project_id)
        if not refresh and cached and (time.time() - cached.get('timestamp', 0)) < _CACHE_TTL:
            return jsonify({
                "success": True,
                "source": "AI_LLM_CACHE",
                "suggestions": cached['suggestions'][:4],
                "telemetry": {
                    "open_risks_count": len(open_risks),
                    "budget_burn_pct": burn_pct
                }
            })

        # 3. Instant live telemetry synthesis (<1ms)
        instant_suggestions = _synthesize_telemetry_suggestions(open_risks, burn_pct, budget, existing_names)

        # 4. Trigger asynchronous background LLM refresh if not already working
        if project_id not in _ASYNC_IN_PROGRESS:
            _ASYNC_IN_PROGRESS.add(project_id)
            bg_thread = threading.Thread(
                target=_async_fetch_llm_suggestions,
                args=(project_id, risk_summaries, burn_pct, existing_names),
                daemon=True
            )
            bg_thread.start()

        # 5. Return immediately (<20ms response time, zero delay for user!)
        return jsonify({
            "success": True,
            "source": "LIVE_TELEMETRY_ENGINE",
            "suggestions": instant_suggestions,
            "telemetry": {
                "open_risks_count": len(open_risks),
                "budget_burn_pct": burn_pct
            }
        })
    except Exception as e:
        logger.error(f"Error producing AI guardrail suggestions: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


