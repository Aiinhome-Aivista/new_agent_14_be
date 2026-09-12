from flask import Blueprint, jsonify, request
import db
from models.project import Project
from models.program import Program
from models.budget import Budget
from models.risk_register import RiskRegister
from models.uploaded_document import UploadedDocument
from services.auth_service import require_roles
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

project_bp = Blueprint('projects', __name__)

@project_bp.route('', methods=['GET'])
@project_bp.route('/', methods=['GET'])
@require_roles('PMO', 'Program Director', 'Investor', 'Project Manager')
def list_projects():
    """
    Returns list of all projects enriched with real-time budget, health, 
    risk counts, and document counts for the Projects Hub.
    """
    try:
        projects = db.db_session.query(Project).order_by(Project.id.asc()).all()
        result = []
        
        for p in projects:
            # 1. Budget telemetry
            budget = db.db_session.query(Budget).filter_by(project_id=p.id).order_by(Budget.created_at.desc()).first()
            if budget:
                pl_val = float(budget.planned_spend)
                ac_val = float(budget.actual_spend)
                var_val = float(budget.variance)
                burn_pct = round((ac_val / pl_val * 100)) if pl_val > 0 else 0
                pl_str = f"${pl_val/1000000:.1f}M" if pl_val >= 1000000 else f"${pl_val/1000:.0f}K"
                ac_str = f"${ac_val/1000000:.1f}M" if ac_val >= 1000000 else f"${ac_val/1000:.0f}K"
                b_summary = f"{ac_str} / {pl_str}"
            else:
                pl_val = 1000000.0
                ac_val = 0.0
                var_val = pl_val
                burn_pct = 0
                b_summary = "$0 / $1.0M"

            # 2. Risk telemetry
            risks = db.db_session.query(RiskRegister).filter_by(project_id=p.id).all()
            crit_count = sum(1 for r in risks if str(r.severity).capitalize() == 'Critical' and str(r.status).capitalize() == 'Open')
            high_count = sum(1 for r in risks if str(r.severity).capitalize() == 'High' and str(r.status).capitalize() == 'Open')
            total_open_risks = sum(1 for r in risks if str(r.status).capitalize() == 'Open')
            
            # Health calculation
            health_score = max(40, 95 - (crit_count * 12 + high_count * 6))

            # 3. Document count
            doc_count = db.db_session.query(UploadedDocument).filter_by(project_id=p.id).count()

            # 4. Program name
            prog_name = "Enterprise Portfolio"
            if p.program_id:
                prog = db.db_session.query(Program).filter_by(id=p.program_id).first()
                if prog and prog.name:
                    prog_name = prog.name

            p_dict = p.to_dict()
            p_dict.update({
                'program_name': prog_name,
                'health_score': health_score,
                'planned_spend': pl_val,
                'actual_spend': ac_val,
                'variance': var_val,
                'burn_pct': burn_pct,
                'budget_summary': b_summary,
                'critical_risks_count': crit_count,
                'high_risks_count': high_count,
                'total_risks_count': len(risks),
                'open_risks_count': total_open_risks,
                'documents_count': doc_count
            })
            result.append(p_dict)

        return jsonify({
            'success': True,
            'projects': result,
            'count': len(result)
        })
    except Exception as e:
        logger.error(f"Error listing projects: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@project_bp.route('', methods=['POST'])
@project_bp.route('/', methods=['POST'])
@require_roles('PMO')
def create_project():
    """
    Creates a new project. STRICTLY RESTRICTED TO PMO.
    Validates unique jira_key, creates program if needed, and initializes budget.
    """
    data = request.json or {}
    name = (data.get('name') or '').strip()
    jira_key = (data.get('jira_key') or '').strip().upper()
    description = (data.get('description') or '').strip()
    status = (data.get('status') or 'Active').strip()
    program_name = (data.get('program_name') or 'Enterprise Portfolio').strip()
    raw_budget = data.get('planned_spend', 1000000.0)

    if not name:
        return jsonify({'success': False, 'error': 'Project Name is required.'}), 400

    # Auto-generate unique project key if not explicitly supplied
    if not jira_key:
        words = [w for w in name.split() if w.isalnum()]
        prefix = "".join(w[0].upper() for w in words[:4]) if words else "PRJ"
        if len(prefix) < 2:
            prefix = "PRJ"
        candidate = prefix
        counter = 101
        while db.db_session.query(Project).filter_by(jira_key=candidate).first():
            candidate = f"{prefix}-{counter}"
            counter += 1
        jira_key = candidate
    else:
        # Ensure provided Jira Key doesn't conflict
        existing = db.db_session.query(Project).filter_by(jira_key=jira_key).first()
        if existing:
            return jsonify({'success': False, 'error': f"Project key '{jira_key}' already exists. Please choose a distinct key."}), 400

    try:
        try:
            planned_spend = float(raw_budget)
        except (ValueError, TypeError):
            planned_spend = 1000000.0

        # Program association
        program = db.db_session.query(Program).filter_by(name=program_name).first()
        if not program:
            program = Program(
                name=program_name,
                description=f"Program portfolio for {name}",
                created_at=datetime.now(timezone.utc)
            )
            db.db_session.add(program)
            db.db_session.flush()

        # Create Project
        new_project = Project(
            program_id=program.id,
            jira_key=jira_key,
            name=name,
            description=description,
            status=status,
            created_at=datetime.now(timezone.utc)
        )
        db.db_session.add(new_project)
        db.db_session.flush()

        # Initialize default Budget
        initial_budget = Budget(
            project_id=new_project.id,
            period="Q1 2026",
            planned_spend=planned_spend,
            actual_spend=0.0,
            variance=planned_spend,
            created_at=datetime.now(timezone.utc)
        )
        db.db_session.add(initial_budget)

        db.db_session.commit()

        p_dict = new_project.to_dict()
        p_dict.update({
            'program_name': program.name,
            'health_score': 95,
            'planned_spend': planned_spend,
            'actual_spend': 0.0,
            'variance': planned_spend,
            'burn_pct': 0,
            'budget_summary': f"$0 / ${planned_spend/1000000:.1f}M" if planned_spend >= 1000000 else f"$0 / ${planned_spend/1000:.0f}K",
            'critical_risks_count': 0,
            'high_risks_count': 0,
            'total_risks_count': 0,
            'open_risks_count': 0,
            'documents_count': 0
        })

        return jsonify({
            'success': True,
            'message': f"Project '{name}' [{jira_key}] successfully created.",
            'project': p_dict
        }), 201

    except Exception as e:
        db.db_session.rollback()
        logger.error(f"Error creating project: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@project_bp.route('/<int:project_id>', methods=['GET'])
@require_roles('PMO', 'Program Director', 'Investor', 'Project Manager')
def get_project(project_id):
    """Fetches full project details by ID."""
    project = db.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return jsonify({'success': False, 'error': f"Project ID {project_id} not found"}), 404

    budget = db.db_session.query(Budget).filter_by(project_id=project.id).order_by(Budget.created_at.desc()).first()
    risks = db.db_session.query(RiskRegister).filter_by(project_id=project.id).all()
    docs = db.db_session.query(UploadedDocument).filter_by(project_id=project.id).all()

    crit_count = sum(1 for r in risks if str(r.severity).capitalize() == 'Critical' and str(r.status).capitalize() == 'Open')
    high_count = sum(1 for r in risks if str(r.severity).capitalize() == 'High' and str(r.status).capitalize() == 'Open')
    health_score = max(40, 95 - (crit_count * 12 + high_count * 6))

    res = project.to_dict()
    res.update({
        'health_score': health_score,
        'planned_spend': float(budget.planned_spend) if budget else 1000000.0,
        'actual_spend': float(budget.actual_spend) if budget else 0.0,
        'variance': float(budget.variance) if budget else 1000000.0,
        'risks': [r.to_dict() for r in risks],
        'documents': [d.to_dict() for d in docs]
    })
    return jsonify({'success': True, 'project': res})


@project_bp.route('/<int:project_id>', methods=['PUT', 'PATCH'])
@require_roles('PMO')
def update_project(project_id):
    """Updates an existing project. PMO only."""
    project = db.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return jsonify({'success': False, 'error': f"Project ID {project_id} not found"}), 404

    data = request.json or {}
    if 'name' in data and data['name'].strip():
        project.name = data['name'].strip()
    if 'description' in data:
        project.description = data['description'].strip()
    if 'status' in data and data['status'].strip():
        project.status = data['status'].strip()

    # Update or initialize budget planned_spend
    updated_plan = None
    if 'planned_spend' in data and data['planned_spend'] is not None:
        try:
            new_plan = float(data['planned_spend'])
            updated_plan = new_plan
            budget = db.db_session.query(Budget).filter_by(project_id=project.id).order_by(Budget.created_at.desc()).first()
            if budget:
                budget.planned_spend = new_plan
                budget.variance = new_plan - float(budget.actual_spend or 0.0)
            else:
                budget = Budget(
                    project_id=project.id,
                    period="Q1 2026",
                    planned_spend=new_plan,
                    actual_spend=0.0,
                    variance=new_plan,
                    created_at=datetime.now(timezone.utc)
                )
                db.db_session.add(budget)
        except (ValueError, TypeError):
            pass

    try:
        db.db_session.commit()
        
        # Build enriched response
        b = db.db_session.query(Budget).filter_by(project_id=project.id).order_by(Budget.created_at.desc()).first()
        pl_val = float(b.planned_spend) if b else (updated_plan or 1000000.0)
        ac_val = float(b.actual_spend) if b else 0.0
        var_val = float(b.variance) if b else pl_val
        burn_pct = round((ac_val / pl_val * 100)) if pl_val > 0 else 0
        pl_str = f"${pl_val/1000000:.1f}M" if pl_val >= 1000000 else f"${pl_val/1000:.0f}K"
        ac_str = f"${ac_val/1000000:.1f}M" if ac_val >= 1000000 else f"${ac_val/1000:.0f}K"

        p_dict = project.to_dict()
        p_dict.update({
            'planned_spend': pl_val,
            'actual_spend': ac_val,
            'variance': var_val,
            'burn_pct': burn_pct,
            'budget_summary': f"{ac_str} / {pl_str}"
        })

        return jsonify({
            'success': True,
            'message': f"Project '{project.name}' updated successfully",
            'project': p_dict
        })
    except Exception as e:
        db.db_session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@project_bp.route('/<int:project_id>', methods=['DELETE'])
@require_roles('PMO')
def delete_project(project_id):
    """Deletes a project and its associated records. PMO only."""
    project = db.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return jsonify({'success': False, 'error': f"Project ID {project_id} not found"}), 404

    try:
        # Cascade delete related records
        db.db_session.query(Budget).filter_by(project_id=project.id).delete()
        db.db_session.query(RiskRegister).filter_by(project_id=project.id).delete()
        db.db_session.query(UploadedDocument).filter_by(project_id=project.id).delete()
        db.db_session.delete(project)
        db.db_session.commit()
        return jsonify({'success': True, 'message': f"Project {project_id} deleted successfully"})
    except Exception as e:
        db.db_session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
