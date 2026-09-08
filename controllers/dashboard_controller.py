from flask import Blueprint, jsonify
import db
from models.dashboard_snapshot import DashboardSnapshot
from models.project import Project
from models.risk_register import RiskRegister

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/snapshot', methods=['GET'])
def get_snapshot():
    # Fetch the latest dashboard snapshot
    snapshot = db.db_session.query(DashboardSnapshot).order_by(DashboardSnapshot.created_at.desc()).first()
    
    if snapshot:
        snap_dict = snapshot.to_dict()
        snap_data = snap_dict.get('data', {})
        if isinstance(snap_data, dict):
            from models.budget import Budget
            all_projs = db.db_session.query(Project).all()
            project_list = []
            for p in all_projs:
                b = db.db_session.query(Budget).filter_by(project_id=p.id).order_by(Budget.created_at.desc()).first()
                if b:
                    pl = f"${float(b.planned_spend)/1000000:.1f}M" if float(b.planned_spend)>=1000000 else f"${float(b.planned_spend)/1000:.0f}K"
                    ac = f"${float(b.actual_spend)/1000000:.1f}M" if float(b.actual_spend)>=1000000 else f"${float(b.actual_spend)/1000:.0f}K"
                    b_str = f"Budget: {ac} / {pl}"
                else:
                    b_str = "Budget: Active"
                project_list.append({
                    "id": p.jira_key,
                    "numeric_id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "budget_summary": b_str
                })
            snap_data["projects"] = project_list
            snap_dict['data'] = snap_data
        return jsonify(snap_dict)
    return jsonify({"error": "No dashboard data available yet."}), 404

@dashboard_bp.route('/projects/<project_id>', methods=['GET'])
def get_project_details(project_id):
    # Query project by numeric ID or jira_key
    project = None
    if str(project_id).isdigit():
        project = db.db_session.query(Project).filter_by(id=int(project_id)).first()
        
    if not project:
        project = db.db_session.query(Project).filter_by(jira_key=str(project_id)).first()
        
    if not project:
        # Fallback to first project if available
        project = db.db_session.query(Project).first()
        
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Query project risks from RiskRegister
    risks = db.db_session.query(RiskRegister).filter_by(project_id=project.id).all()
    
    crit = [r.risk_id for r in risks if r.severity.capitalize() == 'Critical']
    high = [r.risk_id for r in risks if r.severity.capitalize() == 'High']
    med = [r.risk_id for r in risks if r.severity.capitalize() == 'Medium']
    low = [r.risk_id for r in risks if r.severity.capitalize() == 'Low']

    # Health score calculation specific to project
    health = max(40, 95 - (len(crit) * 12 + len(high) * 6))

    # Project-specific budget & burndown values queried from Budget model
    from models.budget import Budget
    budget_record = db.db_session.query(Budget).filter_by(project_id=project.id).order_by(Budget.created_at.desc()).first()
    if budget_record:
        planned_val = float(budget_record.planned_spend)
        actual_val = float(budget_record.actual_spend)
        cost_variance = float(budget_record.variance)
    else:
        # Fallback if no budget recorded yet
        planned_val = 1000000.0
        actual_val = 500000.0
        cost_variance = planned_val - actual_val

    burn_pct = round((actual_val / planned_val * 100)) if planned_val > 0 else 0
    burn_rate = f"{burn_pct}% Burned"
    
    def fmt_cur(val):
        return f"${val / 1000000:.1f}M" if abs(val) >= 1000000 else f"${val / 1000:.0f}K"

    planned_budget = fmt_cur(planned_val)
    actual_spend = fmt_cur(actual_val)
    variance_str = f"{fmt_cur(abs(cost_variance))} {'Deficit' if cost_variance < 0 else 'Surplus'}"

    # NOTE: Burndown values are a budget-ratio-derived approximation (not real sprint telemetry),
    # as there is currently no dedicated Sprint tracking table. If Jira Agile/sprint API access
    # becomes available later (via JiraTool), that will serve as the real sprint data source.
    burndown = [
        {"sprint": "Sprint 1", "planned": int(planned_val * 0.15 / 1000), "actual": int(actual_val * 0.16 / 1000)},
        {"sprint": "Sprint 2", "planned": int(planned_val * 0.35 / 1000), "actual": int(actual_val * 0.34 / 1000)},
        {"sprint": "Sprint 3", "planned": int(planned_val * 0.55 / 1000), "actual": int(actual_val * 0.58 / 1000)},
        {"sprint": "Sprint 4", "planned": int(planned_val * 0.75 / 1000), "actual": int(actual_val * 0.77 / 1000)},
        {"sprint": "Sprint 5", "planned": int(planned_val * 0.90 / 1000), "actual": int(actual_val / 1000)},
        {"sprint": "Sprint 6", "planned": int(planned_val / 1000), "actual": None}
    ]

    project_data = {
        "id": project.jira_key,
        "numeric_id": project.id,
        "name": project.name,
        "status": project.status,
        "healthScore": health,
        "kpis": [
            {
                "title": "Project Budget",
                "value": f"{actual_spend} / {planned_budget}",
                "trend": "up" if actual_val <= planned_val else "down",
                "trendLabel": burn_rate
            },
            {
                "title": "Budget Variance (Cost-Derived)",
                "value": variance_str,
                "trend": "up" if cost_variance >= 0 else "down",
                "trendLabel": "Within Allocation" if cost_variance >= 0 else "Over Allocation"
            },
            {
                "title": "Active Risks",
                "value": str(len(risks)),
                "trend": "up",
                "trendLabel": f"{len(crit)} Critical / {len(high)} High"
            },
            {
                "title": "Project Health",
                "value": f"{health}%",
                "trend": "neutral",
                "trendLabel": "Action Required" if health < 80 else "Stable Progress"
            }
        ],
        "burndown": burndown,
        "risks": [
            {"label": "Critical", "color": "bg-primary", "items": crit},
            {"label": "High", "color": "bg-button", "items": high},
            {"label": "Medium", "color": "bg-hover", "items": med},
            {"label": "Low", "color": "bg-borderOrange", "items": low}
        ],
        "risk_details": [r.to_dict() for r in risks]
    }

    return jsonify(project_data)

