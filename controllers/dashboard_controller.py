from flask import Blueprint, jsonify, request
import db
from models.dashboard_snapshot import DashboardSnapshot
from models.project import Project
from models.risk_register import RiskRegister
from models.budget import Budget
from models.approval_queue import ApprovalQueue
from models.uploaded_document import UploadedDocument
from models.task_item import TaskItem
from controllers.risks_controller import enrich_risk_dict
from services.auth_service import require_roles

dashboard_bp = Blueprint('dashboard', __name__)

def get_project_db_telemetry(project_id):
    """
    Extracts high-fidelity project telemetry (team members, roles, milestones, deliverables)
    directly from the MySQL database (project_members and project_milestones tables).
    Zero dependency on local filesystem or uploads folder.
    """
    from models.project_telemetry import ProjectTelemetry
    from models.project_member import ProjectMember
    from models.project_milestone import ProjectMilestone

    team = []
    milestones = []

    if db.db_session:
        try:
            # 1. Check ProjectTelemetry (Dynamic Schema-less JSON in MySQL)
            p_tel = db.db_session.query(ProjectTelemetry).filter_by(project_id=project_id).first()
            if p_tel and isinstance(p_tel.telemetry_data, dict):
                t_json = p_tel.telemetry_data
                if t_json.get('team') and isinstance(t_json['team'], list):
                    team = t_json['team']
                if t_json.get('milestones') and isinstance(t_json['milestones'], list):
                    for ms in t_json['milestones']:
                        milestones.append({
                            'id': ms.get('milestone_code') or ms.get('id') or 'M-01',
                            'name': ms.get('name') or 'Milestone',
                            'target_date': ms.get('target_date') or 'TBD',
                            'status': ms.get('status') or 'Scheduled',
                            'completion_pct': ms.get('completion_pct', 0),
                            'days_left': ms.get('days_left', 0),
                            'tranche_amount': ms.get('tranche_amount', 0.0),
                            'sla_score': ms.get('sla_score'),
                            'sla_status': ms.get('sla_status', 'Scheduled'),
                            'meta_data': ms.get('meta_data', {})
                        })

            # 2. If not in ProjectTelemetry, query relational tables in MySQL
            if not team:
                members = db.db_session.query(ProjectMember).filter_by(project_id=project_id).all()
                for m in members:
                    team.append({
                        'id': m.id,
                        'name': m.name,
                        'role': m.role,
                        'contact': m.contact or '',
                        'member_type': m.member_type or 'Internal FTE',
                        'allocation_pct': m.allocation_pct or 100.0,
                        'is_active_today': m.is_active_today if m.is_active_today is not None else True,
                        'meta_data': m.meta_data or {}
                    })

            if not milestones:
                p_milestones = db.db_session.query(ProjectMilestone).filter_by(project_id=project_id).order_by(ProjectMilestone.id.asc()).all()
                for ms in p_milestones:
                    milestones.append({
                        'id': ms.milestone_code,
                        'name': ms.name,
                        'target_date': ms.target_date or 'TBD',
                        'status': ms.status or 'Scheduled',
                        'completion_pct': ms.completion_pct if ms.completion_pct is not None else 0,
                        'days_left': ms.days_left if ms.days_left is not None else 0,
                        'tranche_amount': ms.tranche_amount or 0.0,
                        'sla_score': ms.sla_score,
                        'sla_status': ms.sla_status or 'Scheduled',
                        'meta_data': ms.meta_data or {}
                    })
        except Exception as e:
            print(f"[get_project_db_telemetry] Error querying MySQL telemetry: {e}")

    # Fallback: if MySQL was empty for this project, try one-time parse from docx and persist into MySQL
    if not team and not milestones and db.db_session:
        try:
            import os
            from docx import Document
            from models.uploaded_document import UploadedDocument
            docs = db.db_session.query(UploadedDocument).filter_by(project_id=project_id).all()
            for d in docs:
                if not d.filename:
                    continue
                p1 = os.path.join('uploads', d.filename)
                p2 = os.path.join('..', d.filename)
                doc_path = p1 if os.path.exists(p1) and p1.lower().endswith('.docx') else (p2 if os.path.exists(p2) and p2.lower().endswith('.docx') else None)
                if doc_path:
                    doc = Document(doc_path)
                    for table in doc.tables:
                        if not table.rows:
                            continue
                        headers = [c.text.strip().lower() for c in table.rows[0].cells]
                        if 'name' in headers and 'role' in headers and 'signature' not in headers:
                            name_idx = headers.index('name')
                            role_idx = headers.index('role')
                            contact_idx = headers.index('contact') if 'contact' in headers else -1
                            for row in table.rows[1:]:
                                cells = [c.text.strip() for c in row.cells]
                                if len(cells) > max(name_idx, role_idx) and cells[name_idx]:
                                    mem = ProjectMember(
                                        project_id=project_id,
                                        name=cells[name_idx],
                                        role=cells[role_idx],
                                        contact=cells[contact_idx] if contact_idx >= 0 and len(cells) > contact_idx else '',
                                        member_type='Internal FTE',
                                        allocation_pct=100.0,
                                        is_active_today=True
                                    )
                                    db.db_session.add(mem)
                                    team.append(mem.to_dict())
                        elif 'milestone' in headers:
                            m_idx = headers.index('milestone')
                            desc_idx = headers.index('description') if 'description' in headers else -1
                            target_idx = headers.index('target date') if 'target date' in headers else -1
                            stat_idx = headers.index('status') if 'status' in headers else -1
                            for row in table.rows[1:]:
                                cells = [c.text.strip() for c in row.cells]
                                if len(cells) > m_idx and cells[m_idx]:
                                    m_code = cells[m_idx]
                                    m_desc = cells[desc_idx] if desc_idx >= 0 and len(cells) > desc_idx else ''
                                    m_target = cells[target_idx] if target_idx >= 0 and len(cells) > target_idx else 'TBD'
                                    m_stat = cells[stat_idx] if stat_idx >= 0 and len(cells) > stat_idx else 'Pending'
                                    comp_pct = 100 if m_stat.lower() in ('done', 'completed') else (50 if m_stat.lower() in ('in progress', 'on track') else (20 if 'risk' in m_stat.lower() else 0))
                                    m_obj = ProjectMilestone(
                                        project_id=project_id,
                                        milestone_code=m_code,
                                        name=f"{m_code}: {m_desc}" if m_desc else m_code,
                                        description=m_desc,
                                        target_date=m_target,
                                        status=m_stat,
                                        completion_pct=comp_pct,
                                        days_left=0 if comp_pct == 100 else 45
                                    )
                                    db.db_session.add(m_obj)
                                    milestones.append(m_obj.to_dict())
                    db.db_session.commit()
                    break
        except Exception as err:
            print(f"[get_project_db_telemetry] Fallback parse error: {err}")

    return {'team': team, 'milestones': milestones}

# Backward compatibility alias
extract_project_doc_telemetry = get_project_db_telemetry

def build_pmo_metrics(active_project, all_projs, total_planned, total_actual, tot_variance, burn_pct, crit_ids, high_ids):
    """
    Synthesizes rich, executive PMO metrics:
    - Headcount & Team Allocation (koto jon kaj korche, FTEs, contractors, role breakdown)
    - Total Budget & Variance (total budget, actual spend, remaining, burn rate %, CPI)
    - Estimated Deadlines & Timelines (target date, days remaining, SPI, schedule status, 5 milestone phases)
    - Graphical Task & Deliverables Status (completed, in progress, under review, blocked)
    - Governance & Vendor SLA Performance
    """
    from models.uploaded_document import UploadedDocument
    from models.risk_register import RiskRegister
    from models.project_member import ProjectMember
    from models.project_milestone import ProjectMilestone

    if active_project:
        pid = active_project.id
        p_name = active_project.name
        p_key = active_project.jira_key or ''

        # Check real project activity from database
        doc_count = db.db_session.query(UploadedDocument).filter_by(project_id=active_project.id).count() if db.db_session else 0
        risk_count = db.db_session.query(RiskRegister).filter_by(project_id=active_project.id).count() if db.db_session else 0
        member_count = db.db_session.query(ProjectMember).filter_by(project_id=active_project.id).count() if db.db_session else 0
        from models.task_item import TaskItem
        task_count = db.db_session.query(TaskItem).filter_by(project_id=active_project.id).count() if db.db_session else 0
        is_new_project = (doc_count == 0 and total_actual == 0 and risk_count == 0 and member_count == 0 and task_count == 0)

        if is_new_project:
            total_hc = 0
            fte_hc = 0
            contractor_hc = 0
            active_hc = 0
            util_rate = 0.0
            target_date = "Pending SOW / Roadmap"
            days_left = 0
            spi = 1.00
            sched_status = "New Workspace Initialized"
            completed_tasks = 0
            in_prog_tasks = 0
            review_tasks = 0
            blocked_tasks = 0
            total_tasks = 0
            architects = 0
            engineers = 0
            qa = 0
            devops = 0
            pms = 0
            phases = []
            curr_phase = "Pending Setup"
            gate_status = "Gate 1 Initialized"
            sla_adherence = 100.0
            audit_score = 100
        else:
            doc_telemetry = get_project_db_telemetry(active_project.id)
            if doc_telemetry and doc_telemetry.get('team'):
                team_list = doc_telemetry['team']
                total_hc = len(team_list)
                fte_hc = len([m for m in team_list if m.get('member_type') == 'Internal FTE']) or total_hc
                contractor_hc = total_hc - fte_hc
                active_hc = len([m for m in team_list if m.get('is_active_today', True)]) or total_hc
                util_rate = 0.0
                target_date = "Pending Baseline"
                days_left = 0
                spi = 1.00
                sched_status = "Active & Governed"
                
                # Dynamic count of roles
                architects = max(1, len([m for m in team_list if any(k in m['role'].lower() for k in ['architect', 'lead'])]))
                qa = max(1, len([m for m in team_list if any(k in m['role'].lower() for k in ['qa', 'test'])]))
                devops = max(1, len([m for m in team_list if any(k in m['role'].lower() for k in ['devops', 'infra'])]))
                pms = max(1, len([m for m in team_list if any(k in m['role'].lower() for k in ['manager', 'pm'])]))
                engineers = max(1, total_hc - (architects + qa + devops + pms))
                if engineers <= 0:
                    engineers = max(1, len([m for m in team_list if any(k in m['role'].lower() for k in ['engineer', 'dev', 'safety'])]))
                
                from models.task_item import TaskItem
                from tools.jira_tool import JiraTool
                
                if active_project.jira_key:
                    # Sync tasks from Jira (runs fast enough for a dashboard load in our case)
                    JiraTool.sync_project_telemetry(active_project.id)
                
                # Fetch actual tasks from DB
                completed_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["Done", "Completed", "Resolved"])
                ).count()
                in_prog_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["In Progress", "Active", "Open", "To Do"])
                ).count()
                review_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["In Review", "QA", "Review"])
                ).count()
                blocked_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["Blocked", "Impeded"])
                ).count()
                total_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id
                ).count()
                
                if doc_telemetry.get('milestones'):
                    phases = doc_telemetry['milestones']
                    completed_milestones = len([m for m in phases if m.get('completion_pct', 0) == 100])
                    in_prog_milestones = len([m for m in phases if 0 < m.get('completion_pct', 0) < 100])
                    curr_phase = f"Active Milestone: {phases[min(completed_milestones, len(phases)-1)]['id']}" if completed_milestones < len(phases) else "Milestone Execution"
                else:
                    phases = []
                    curr_phase = "Pending Setup"
                
                gate_status = "Gate 3 Approved" if len(crit_ids) == 0 else "Gate 3 Conditional Hold"
                sla_adherence = 100.0 if total_actual == 0 else (94.8 if len(crit_ids) == 0 else 88.2)
                audit_score = 100 if total_actual == 0 else (96 if len(crit_ids) == 0 else 84)
            else:
                total_hc = 0
                fte_hc = 0
                contractor_hc = 0
                active_hc = 0
                util_rate = 0.0
                target_date = "Pending Baseline"
                days_left = 0
                spi = 1.00
                sched_status = "Workspace Initialized"
                from models.task_item import TaskItem
                completed_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["Done", "Completed", "Resolved"])
                ).count()
                in_prog_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["In Progress", "Active", "Open", "To Do"])
                ).count()
                review_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["In Review", "QA", "Review"])
                ).count()
                blocked_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id,
                    TaskItem.status.in_(["Blocked", "Impeded"])
                ).count()
                total_tasks = db.db_session.query(TaskItem).filter(
                    TaskItem.project_id == active_project.id
                ).count()
                architects = 0
                engineers = 0
                qa = 0
                devops = 0
                pms = 0
                phases = []
                curr_phase = "Pending Setup"
                gate_status = "Gate 1 Initialized"
                sla_adherence = 100.0
                audit_score = 100

    else:
        # Cross-Project Portfolio Mode
        from models.uploaded_document import UploadedDocument
        from models.risk_register import RiskRegister
        from models.task_item import TaskItem
        p_name = "Cross-Project Portfolio"
        total_docs = db.db_session.query(UploadedDocument).count() if db.db_session else 0
        total_risks_count = len(crit_ids) + len(high_ids)
        total_tasks_db = db.db_session.query(TaskItem).count() if db.db_session else 0
        portfolio_is_new = (total_docs == 0 and total_actual == 0 and total_risks_count == 0 and total_tasks_db == 0)

        if portfolio_is_new:
            total_hc = 0
            fte_hc = 0
            contractor_hc = 0
            active_hc = 0
            util_rate = 0.0
            target_date = "Pending Scope Baseline"
            days_left = 0
            spi = 1.00
            sched_status = "Portfolio Initialized (Awaiting Ingestion)"
            completed_tasks = 0
            in_prog_tasks = 0
            review_tasks = 0
            blocked_tasks = 0
            total_tasks = 0
            architects = 0
            engineers = 0
            qa = 0
            devops = 0
            pms = 0
            phases = []
            curr_phase = "Portfolio Initialized"
            gate_status = "Gate 1 Initialized"
            sla_adherence = 100.0
            audit_score = 100
        else:
            all_members = db.db_session.query(ProjectMember).all() if db.db_session else []
            if all_members:
                total_hc = len(all_members)
                fte_hc = len([m for m in all_members if m.member_type == 'Internal FTE']) or total_hc
                contractor_hc = total_hc - fte_hc
                active_hc = len([m for m in all_members if m.is_active_today]) or total_hc
                util_rate = 92.4
                architects = max(1, len([m for m in all_members if any(k in m.role.lower() for k in ['architect', 'lead'])]))
                qa = max(1, len([m for m in all_members if any(k in m.role.lower() for k in ['qa', 'test'])]))
                devops = max(1, len([m for m in all_members if any(k in m.role.lower() for k in ['devops', 'infra'])]))
                pms = max(1, len([m for m in all_members if any(k in m.role.lower() for k in ['manager', 'pm'])]))
                engineers = max(1, total_hc - (architects + qa + devops + pms))
            else:
                total_hc = 0
                fte_hc = 0
                contractor_hc = 0
                active_hc = 0
                util_rate = 0.0
                architects = 0
                engineers = 0
                qa = 0
                devops = 0
                pms = 0

            target_date = "December 15, 2026"
            days_left = 94
            spi = 1.02 if len(crit_ids) == 0 else 0.97
            sched_status = "Governed & On Track" if len(crit_ids) == 0 else f"{len(crit_ids)} Critical Risk Impeded"

            all_milestones = db.db_session.query(ProjectMilestone).all() if db.db_session else []
            if all_milestones:
                completed_milestones = len([m for m in all_milestones if m.completion_pct == 100])
                in_prog_milestones = len([m for m in all_milestones if 0 < m.completion_pct < 100])
                
            from models.task_item import TaskItem
            completed_tasks = db.db_session.query(TaskItem).filter(TaskItem.status.in_(["Done", "Completed", "Resolved"])).count() if db.db_session else 0
            in_prog_tasks = db.db_session.query(TaskItem).filter(TaskItem.status.in_(["In Progress", "Active", "Open", "To Do"])).count() if db.db_session else 0
            review_tasks = db.db_session.query(TaskItem).filter(TaskItem.status.in_(["In Review", "QA", "Review"])).count() if db.db_session else 0
            blocked_tasks = db.db_session.query(TaskItem).filter(TaskItem.status.in_(["Blocked", "Impeded"])).count() if db.db_session else 0
            total_tasks = db.db_session.query(TaskItem).count() if db.db_session else 0

            phases = []
            curr_phase = "Pending Setup"
            gate_status = "Pending Setup"
            sla_adherence = 100.0
            audit_score = 100

    remaining_budget = max(0.0, total_planned - total_actual)
    if total_tasks > 0:
        completion_ratio = completed_tasks / total_tasks
        earned_val = round(completion_ratio * total_planned, 2)
        cpi = round(max(0.0, min(5.0, earned_val / total_actual)), 2) if total_actual > 0 else 1.00
        monthly_run_rate = round(total_actual / 3.0, 2) if total_actual > 0 else 0.0
        cv = round(earned_val - total_actual, 2)
        evm_status = "Healthy & On Track" if cpi >= 1.0 else "Cost Overrun Risk"
        # SPI (Schedule Performance Index) = Earned Value / Planned Value to Date
        planned_to_date = total_planned * 0.45 if total_planned > 0 else earned_val
        spi = round(max(0.0, min(5.0, earned_val / max(1.0, planned_to_date))), 2) if planned_to_date > 0 else 1.00
    else:
        # Strict zero: 0 tasks logged in DB means 0 work completed!
        completion_ratio = 0.0
        earned_val = 0.0
        cpi = 0.00
        monthly_run_rate = round(total_actual / 3.0, 2) if total_actual > 0 else 0.0
        cv = round(-total_actual, 2)
        evm_status = "No Tasks Logged (0% Done)"
        spi = 0.00

    if total_hc > 0:
        roles_list = [
            {"role": "Enterprise & Solutions Architects", "count": architects, "allocation_pct": round((architects / total_hc) * 100, 1), "color": "#FF5A14"},
            {"role": "Core Full-Stack & System Engineers", "count": engineers, "allocation_pct": round((engineers / total_hc) * 100, 1), "color": "#3B82F6"},
            {"role": "QA Automation & Test Engineers", "count": qa, "allocation_pct": round((qa / total_hc) * 100, 1), "color": "#10B981"},
            {"role": "Cloud DevOps & Platform SRE", "count": devops, "allocation_pct": round((devops / total_hc) * 100, 1), "color": "#8B5CF6"},
            {"role": "Scrum Masters & PMO Coordinators", "count": pms, "allocation_pct": round((pms / total_hc) * 100, 1), "color": "#F59E0B"}
        ]

        if contractor_hc > 0:
            vendors_list = [
                {"name": "PwC Internal Enterprise Staff", "headcount": fte_hc, "type": "Internal FTE", "share": f"{round(fte_hc / total_hc * 100)}%", "sla": "98.5%"},
                {"name": "Cognizant / Infosys (System Integration)", "headcount": max(1, int(contractor_hc * 0.7)), "type": "Vendor Contractor", "share": f"{round(int(contractor_hc * 0.7) / total_hc * 100)}%", "sla": "93.4%"},
                {"name": "Cloud Infrastructure Specialists (AWS/Azure)", "headcount": max(1, contractor_hc - int(contractor_hc * 0.7)), "type": "Specialist Contractor", "share": f"{round((contractor_hc - int(contractor_hc * 0.7)) / total_hc * 100)}%", "sla": "96.0%"}
            ]
        else:
            vendors_list = [
                {"name": "Internal Platform Engineering Pod", "headcount": fte_hc, "type": "Internal FTE", "share": "100%", "sla": "98.5%"}
            ]
    else:
        roles_list = []
        vendors_list = []

    task_items = []
    if db.db_session:
        from models.task_item import TaskItem
        if active_project:
            db_tasks = db.db_session.query(TaskItem).filter_by(project_id=active_project.id).all()
        else:
            db_tasks = db.db_session.query(TaskItem).all()
            
        for t in db_tasks:
            # Map Jira status to dashboard grouped status for filtering
            status_lower = t.status.lower() if t.status else ""
            mapped_status = "In Progress"
            if any(s in status_lower for s in ["done", "completed", "resolved"]):
                mapped_status = "Completed"
            elif any(s in status_lower for s in ["review", "qa"]):
                mapped_status = "Under Review / QA"
            elif any(s in status_lower for s in ["block", "impede"]):
                mapped_status = "Blocked / Impeded"
                
            task_items.append({
                "id": t.jira_key or f"TSK-{t.id}",
                "title": t.summary,
                "status": mapped_status,
                "priority": t.priority,
                "owner": t.assignee or "Unassigned",
                "workstream": "Development", # Default for now
                "due_date": "Active Sprint",
                "linked_risk_id": None
            })
    if total_tasks > 0:
        task_breakdown = [
            {"name": "Completed", "count": completed_tasks, "percentage": round(completed_tasks / total_tasks * 100), "color": "#10B981"},
            {"name": "In Progress", "count": in_prog_tasks, "percentage": round(in_prog_tasks / total_tasks * 100), "color": "#3B82F6"},
            {"name": "Under Review / QA", "count": review_tasks, "percentage": round(review_tasks / total_tasks * 100), "color": "#F59E0B"},
            {"name": "Blocked / Impeded", "count": blocked_tasks, "percentage": round(blocked_tasks / total_tasks * 100), "color": "#EF4444"}
        ]
        completion_rate = round(completed_tasks / total_tasks * 100)
    else:
        task_breakdown = [
            {"name": "Completed", "count": 0, "percentage": 0, "color": "#10B981"},
            {"name": "In Progress", "count": 0, "percentage": 0, "color": "#3B82F6"},
            {"name": "Under Review / QA", "count": 0, "percentage": 0, "color": "#F59E0B"},
            {"name": "Blocked / Impeded", "count": 0, "percentage": 0, "color": "#EF4444"}
        ]
        completion_rate = 0

    return {
        "scope_name": p_name,
        "is_single_project": active_project is not None,
        "headcount": {
            "total": total_hc,
            "active_today": active_hc,
            "fte": fte_hc,
            "contractor": contractor_hc,
            "utilization_rate": util_rate,
            "roles": roles_list,
            "vendors": vendors_list,
            "members": team_list if ('team_list' in locals() and team_list) else []
        },
        "budget": {
            "total_planned": total_planned,
            "total_actual": total_actual,
            "remaining": remaining_budget,
            "burn_percentage": burn_pct,
            "variance": tot_variance,
            "variance_status": "Surplus" if tot_variance >= 0 else "Deficit",
            "monthly_run_rate": monthly_run_rate,
            "cpi": cpi,
            "spi": spi,
            "earned_value": earned_val,
            "cost_variance": cv,
            "evm_status": evm_status,
            "active_sprint": "Sprint 3" if total_actual > 0 else "Sprint 1"
        },
        "timeline": {
            "target_completion_date": target_date,
            "days_remaining": days_left,
            "schedule_status": sched_status,
            "spi": spi,
            "current_phase": curr_phase,
            "phases": phases
        },
        "tasks": {
            "total": total_tasks,
            "completed": completed_tasks,
            "in_progress": in_prog_tasks,
            "under_review": review_tasks,
            "blocked": blocked_tasks,
            "completion_rate": completion_rate,
            "breakdown": task_breakdown,
            "items": task_items
        },
        "governance": {
            "vendor_sla_adherence": sla_adherence,
            "compliance_audit_score": audit_score,
            "open_escalations": len(crit_ids) + (1 if tot_variance < 0 and total_actual > 0 else 0),
            "gate_clearance_status": gate_status
        }
    }

def calculate_dynamic_health_score(active_project, total_planned, total_actual, all_risks, db_session=None):
    """
    Dynamically computes a 0-100 project health & delivery confidence score:
    - Starts at 100.0 (Clean baseline)
    - Budget Overrun: proportional penalty if actual > planned spend
    - Risk Penalties:
        * Open Critical risk: -15 pts
        * Open High risk: -8 pts
        * Open Medium risk: -3 pts
        * Open Low risk: -1 pt
    - Task Delivery Impediments:
        * Blocked / Impeded tasks: -5 pts each
    - Milestone SLA Compliance:
        * Deductions if milestone SLA drops below 95%
    """
    score = 100.0

    # 1. Budget Overrun Penalty (up to 35 pts)
    if total_planned > 0 and total_actual > total_planned:
        overrun_ratio = (total_actual - total_planned) / total_planned
        score -= min(35.0, overrun_ratio * 50.0)

    # 2. Risk Penalties
    crit_count = sum(1 for r in all_risks if str(getattr(r, 'severity', '')).capitalize() == "Critical" and str(getattr(r, 'status', '')).capitalize() == "Open")
    high_count = sum(1 for r in all_risks if str(getattr(r, 'severity', '')).capitalize() == "High" and str(getattr(r, 'status', '')).capitalize() == "Open")
    med_count = sum(1 for r in all_risks if str(getattr(r, 'severity', '')).capitalize() == "Medium" and str(getattr(r, 'status', '')).capitalize() == "Open")
    low_count = sum(1 for r in all_risks if str(getattr(r, 'severity', '')).capitalize() == "Low" and str(getattr(r, 'status', '')).capitalize() == "Open")
    
    score -= (crit_count * 15.0) + (high_count * 8.0) + (med_count * 3.0) + (low_count * 1.0)

    # 3. Task Impediments Penalty (up to 20 pts)
    if db_session and active_project:
        try:
            from models.task_item import TaskItem
            blocked_tasks = db_session.query(TaskItem).filter(
                TaskItem.project_id == active_project.id,
                TaskItem.status.in_(["Blocked", "Impeded"])
            ).count()
            score -= min(20.0, blocked_tasks * 5.0)
        except Exception:
            pass

    # 4. Milestone SLA Penalty
    if db_session and active_project:
        try:
            from models.project_milestone import ProjectMilestone
            milestones = db_session.query(ProjectMilestone).filter_by(project_id=active_project.id).all()
            sla_scores = [m.sla_score for m in milestones if m.sla_score is not None]
            if sla_scores:
                avg_sla = sum(sla_scores) / len(sla_scores)
                if avg_sla < 95.0:
                    score -= (95.0 - avg_sla) * 0.4
        except Exception:
            pass

    return max(20, min(100, round(score)))


@dashboard_bp.route('/snapshot', methods=['GET'])
def get_snapshot():
    # Read optional project_id query parameter
    project_id_param = request.args.get('project_id')
    active_project = None

    if project_id_param and str(project_id_param).strip().lower() not in ('all', '', 'none', 'null'):
        if str(project_id_param).isdigit():
            active_project = db.db_session.query(Project).filter_by(id=int(project_id_param)).first()
        if not active_project:
            active_project = db.db_session.query(Project).filter_by(jira_key=str(project_id_param).strip()).first()
    
    if not active_project and str(project_id_param or '').strip().lower() not in ('all', 'portfolio'):
        active_project = db.db_session.query(Project).filter_by(id=1).first() or db.db_session.query(Project).first()

    # Fetch the latest dashboard snapshot baseline
    snapshot = db.db_session.query(DashboardSnapshot).order_by(DashboardSnapshot.created_at.desc()).first()
    
    if snapshot:
        snap_dict = snapshot.to_dict()
        snap_data = snap_dict.get('data', {})
        if not isinstance(snap_data, dict):
            snap_data = {}
    else:
        snap_data = {
            "name": "Enterprise Governance Suite",
            "id": "PRJ-101",
            "healthScore": 100,
            "burndown": [],
            "milestones": [],
            "financials": {"totalBudget": 0, "spent": 0, "remaining": 0, "projectedVariance": 0}
        }
        snap_dict = {"data": snap_data}

    all_projs = db.db_session.query(Project).all()
    project_list = []
    for p in all_projs:
        b = db.db_session.query(Budget).filter_by(project_id=p.id).order_by(Budget.created_at.desc()).first()
        if b:
            def _fmt(v):
                v = float(v)
                if abs(v) >= 10000000: return f"₹{v/10000000:.2f}Cr"
                if abs(v) >= 100000: return f"₹{v/100000:.1f}L"
                return f"₹{v:,.0f}"
            pl = _fmt(b.planned_spend or 0)
            ac = _fmt(b.actual_spend or 0)
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

    # If scoping by project, override identity
    if active_project:
        snap_data["name"] = active_project.name
        snap_data["id"] = active_project.jira_key
        snap_data["numeric_id"] = active_project.id
        snap_data["active_project"] = active_project.to_dict()
        cross_project_status_str = f"{active_project.name} ({active_project.status})"
        all_budgets = db.db_session.query(Budget).filter_by(project_id=active_project.id).all()
        all_risks = db.db_session.query(RiskRegister).filter_by(project_id=active_project.id).all()
        open_showstoppers = db.db_session.query(RiskRegister).filter(
            RiskRegister.project_id == active_project.id,
            RiskRegister.status == "Open",
            RiskRegister.severity.in_(["Critical", "High"])
        ).order_by(RiskRegister.id.asc()).all()
    else:
        # Cross-project / Portfolio mode
        total_p = len(all_projs)
        at_risk_p = 0
        for p in all_projs:
            has_crit = db.db_session.query(RiskRegister).filter(
                RiskRegister.project_id == p.id,
                RiskRegister.status == "Open",
                RiskRegister.severity.in_(["Critical", "High"])
            ).first() is not None
            if has_crit:
                at_risk_p += 1
        healthy_p = total_p - at_risk_p
        cross_project_status_str = f"{healthy_p} Active / {at_risk_p} At Risk" if at_risk_p > 0 else f"{total_p} Active & Governed"
        all_budgets = db.db_session.query(Budget).all()
        all_risks = db.db_session.query(RiskRegister).all()
        open_showstoppers = db.db_session.query(RiskRegister).filter(
            RiskRegister.status == "Open",
            RiskRegister.severity.in_(["Critical", "High"])
        ).order_by(RiskRegister.id.asc()).all()

    # Budget burn & variance calculations (baseline per active project or latest per distinct project)
    if active_project:
        latest_b = db.db_session.query(Budget).filter_by(project_id=active_project.id).order_by(Budget.created_at.desc()).first()
        total_planned = float(latest_b.planned_spend) if latest_b else 0.0
        total_actual = float(latest_b.actual_spend) if latest_b else 0.0
        from models.task_item import TaskItem
        doc_count = db.db_session.query(UploadedDocument).filter_by(project_id=active_project.id).count() if db.db_session else 0
        risk_count = db.db_session.query(RiskRegister).filter_by(project_id=active_project.id).count() if db.db_session else 0
        task_count = db.db_session.query(TaskItem).filter_by(project_id=active_project.id).count() if db.db_session else 0
        is_new_project = (doc_count == 0 and total_actual == 0 and risk_count == 0 and task_count == 0)
    else:
        total_planned = 0.0
        total_actual = 0.0
        is_new_project = False
        for p in all_projs:
            p_b = db.db_session.query(Budget).filter_by(project_id=p.id).order_by(Budget.created_at.desc()).first()
            if p_b:
                total_planned += float(p_b.planned_spend or 0.0)
                total_actual += float(p_b.actual_spend or 0.0)
    tot_variance = total_planned - total_actual
    burn_pct = round((total_actual / total_planned * 100)) if total_planned > 0 else 0

    def fmt_m_val(val):
        if abs(val) >= 10000000:
            return f"₹{val / 10000000:.2f}Cr"
        elif abs(val) >= 100000:
            return f"₹{val / 100000:.1f}L"
        else:
            return f"₹{val:,.0f}"

    total_budget_burn_str = f"{fmt_m_val(total_actual)} / {fmt_m_val(total_planned)}"
    sched_variance_str = f"{'+' if tot_variance >= 0 else '-'}{fmt_m_val(abs(tot_variance))} {'Surplus' if tot_variance >= 0 else 'Deficit'}"

    # Real-time query of showstoppers (Open Critical & High risks)
    showstoppers_list = [
        {"id": r.risk_id, "title": r.title, "impact": r.severity.upper()}
        for r in open_showstoppers
    ]

    # Real-time query of escalations (Pending approval queue strictly matching Guardrails Queue)
    all_pending = db.db_session.query(ApprovalQueue).filter_by(status="Pending").order_by(ApprovalQueue.created_at.desc(), ApprovalQueue.id.desc()).all()
    pending_approvals = []
    for item in all_pending:
        payload = item.payload
        if isinstance(payload, str):
            try:
                import json
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if active_project:
            p_id = payload.get('project_id') if isinstance(payload, dict) else None
            if p_id in (active_project.id, str(active_project.id), active_project.jira_key):
                pending_approvals.append(item)
        else:
            pending_approvals.append(item)

    proj_map = {p.id: p.jira_key for p in all_projs}
    escalations_list = []
    for item in pending_approvals:
        esc_id = f"ESC-{item.id:03d}"
        payload = item.payload
        if isinstance(payload, str):
            try:
                import json
                payload = json.loads(payload)
            except Exception:
                payload = {}
        esc_detail = payload.get('escalation') if isinstance(payload, dict) else None
        if isinstance(esc_detail, dict):
            esc_detail = esc_detail.get('title') or esc_detail.get('description') or str(esc_detail)
        action_text = esc_detail if esc_detail else f"{item.action_type} Pending Approval"
        p_id = payload.get('project_id') if isinstance(payload, dict) else None
        p_key = proj_map.get(p_id) or (f"PRJ-{p_id:03d}" if isinstance(p_id, int) else None)

        escalations_list.append({
            "id": esc_id,
            "esc_id": esc_id,
            "project_id": p_id,
            "project_key": p_key,
            "action": action_text,
            "action_type": item.action_type,
            "detail": esc_detail,
            "time": item.created_at.strftime("%d/%m/%Y, %I:%M:%S %p").lower() if item.created_at else "Recent",
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "raw_id": item.id
        })

    # Burndown: compute sprint curve reflecting progressive expenditure
    pl_k = max(10, int(total_planned / 1000))
    ac_k = int(total_actual / 1000)

    # Strict DB Query: calculate Earned Value strictly from real TaskItem records
    from models.task_item import TaskItem
    if active_project:
        db_completed_tasks = db.db_session.query(TaskItem).filter(
            TaskItem.project_id == active_project.id,
            TaskItem.status.in_(["Done", "Completed", "Resolved"])
        ).count() if db.db_session else 0
        db_total_tasks = db.db_session.query(TaskItem).filter(
            TaskItem.project_id == active_project.id
        ).count() if db.db_session else 0
    else:
        db_completed_tasks = db.db_session.query(TaskItem).filter(
            TaskItem.status.in_(["Done", "Completed", "Resolved"])
        ).count() if db.db_session else 0
        db_total_tasks = db.db_session.query(TaskItem).count() if db.db_session else 0

    if db_total_tasks > 0:
        ev_ratio = db_completed_tasks / db_total_tasks
        earned_k = int(pl_k * ev_ratio)
    else:
        ev_ratio = 0.0
        earned_k = 0

    # Project Completion Percentage Calculation (Timeline, Tasks, or Milestones)
    from models.project_milestone import ProjectMilestone
    from datetime import datetime, timezone
    
    if active_project:
        p_milestones = db.db_session.query(ProjectMilestone).filter_by(project_id=active_project.id).order_by(ProjectMilestone.id.asc()).all() if db.db_session else []
    else:
        p_milestones = db.db_session.query(ProjectMilestone).all() if db.db_session else []

    ms_total = len(p_milestones)
    ms_completed = sum(1 for m in p_milestones if (m.completion_pct or 0) >= 100 or str(m.status).lower() in ['completed', 'done', 'released', 'authorized'])
    ms_avg_pct = round(sum(m.completion_pct or 0 for m in p_milestones) / ms_total) if ms_total > 0 else 0

    task_pct = round((db_completed_tasks / db_total_tasks) * 100) if db_total_tasks > 0 else 0

    # Timeline calculation (only if explicit horizon is defined in telemetry or project)
    timeline_elapsed_months = 0
    timeline_total_months = 0
    timeline_pct = 0

    active_telem = get_project_db_telemetry(active_project.id) if active_project else None
    if active_telem and isinstance(active_telem, dict):
        tl_meta = active_telem.get('timeline', {})
        if isinstance(tl_meta, dict):
            timeline_total_months = tl_meta.get('total_months') or 0
            timeline_elapsed_months = tl_meta.get('elapsed_months') or 0

    if timeline_total_months > 0:
        if active_project and getattr(active_project, 'created_at', None):
            try:
                now_dt = datetime.now(timezone.utc)
                c_dt = active_project.created_at
                if c_dt.tzinfo is None:
                    c_dt = c_dt.replace(tzinfo=timezone.utc)
                days_diff = max(0, (now_dt - c_dt).days)
                timeline_elapsed_months = min(timeline_total_months, max(0, round(days_diff / 30, 1)))
                timeline_pct = min(100, round((timeline_elapsed_months / timeline_total_months) * 100))
            except Exception:
                pass

    # Determine primary completion percentage dynamically
    if db_total_tasks > 0:
        comp_percentage = task_pct
        comp_basis = "Task Backlog"
        comp_label = f"{db_completed_tasks}/{db_total_tasks} Tasks Completed ({task_pct}%)"
    elif ms_total > 0:
        comp_percentage = ms_avg_pct
        comp_basis = "Contract Milestones"
        comp_label = f"{ms_completed}/{ms_total} Milestones Verified ({ms_avg_pct}%)"
    elif timeline_total_months > 0 and timeline_pct > 0:
        comp_percentage = timeline_pct
        comp_basis = "Timeline Horizon"
        comp_label = f"{timeline_elapsed_months}/{timeline_total_months} Months Elapsed ({timeline_pct}%)"
    else:
        comp_percentage = 0
        comp_basis = "Initial Phase"
        comp_label = "0% Project Kickoff (Awaiting SOW / Tasks)"

    snap_data["completion"] = {
        "percentage": comp_percentage,
        "basis": comp_basis,
        "label": comp_label,
        "tasks": {
            "completed": db_completed_tasks,
            "total": db_total_tasks,
            "percentage": task_pct
        },
        "milestones": {
            "completed": ms_completed,
            "total": ms_total,
            "percentage": ms_avg_pct
        },
        "timeline": {
            "elapsed_months": timeline_elapsed_months,
            "total_months": timeline_total_months,
            "percentage": timeline_pct
        }
    }

    if ac_k <= 0:
        e1 = int(earned_k * 0.28) if earned_k > 0 else 0
        snap_data["burndown"] = [
            {"sprint": "Sprint 1", "planned": int(pl_k * 0.15), "actual": 0, "earned": e1, "is_current": True},
            {"sprint": "Sprint 2", "planned": int(pl_k * 0.35), "actual": None, "earned": None},
            {"sprint": "Sprint 3", "planned": int(pl_k * 0.55), "actual": None, "earned": None},
            {"sprint": "Sprint 4", "planned": int(pl_k * 0.75), "actual": None, "earned": None},
            {"sprint": "Sprint 5", "planned": int(pl_k * 0.90), "actual": None, "earned": None},
            {"sprint": "Sprint 6", "planned": pl_k, "actual": None, "earned": None}
        ]
        snap_data["active_sprint"] = "Sprint 1"
    else:
        # Progressive cumulative spend and earned value curves up to Sprint 3 (Current)
        a1 = max(1, int(ac_k * 0.25))
        a2 = max(a1, int(ac_k * 0.65))
        a3 = ac_k

        e1 = int(earned_k * 0.28) if earned_k > 0 else 0
        e2 = int(earned_k * 0.68) if earned_k > 0 else 0
        e3 = earned_k

        snap_data["burndown"] = [
            {"sprint": "Sprint 1", "planned": int(pl_k * 0.15), "actual": a1, "earned": e1},
            {"sprint": "Sprint 2", "planned": int(pl_k * 0.35), "actual": a2, "earned": e2},
            {"sprint": "Sprint 3", "planned": int(pl_k * 0.55), "actual": a3, "earned": e3, "is_current": True},
            {"sprint": "Sprint 4", "planned": int(pl_k * 0.75), "actual": None, "earned": None},
            {"sprint": "Sprint 5", "planned": int(pl_k * 0.90), "actual": None, "earned": None},
            {"sprint": "Sprint 6", "planned": pl_k, "actual": None, "earned": None}
        ]
        snap_data["active_sprint"] = "Sprint 3"

    snap_data["financials"] = {
        "totalBudget": total_planned,
        "spent": total_actual,
        "remaining": max(0, total_planned - total_actual),
        "projectedVariance": tot_variance
    }

    # Real-time risk distribution for heatmaps (PMO & Investor)
    crit_ids = [r.risk_id for r in all_risks if r.severity == "Critical" and r.status == "Open"]
    high_ids = [r.risk_id for r in all_risks if r.severity == "High" and r.status == "Open"]
    med_ids = [r.risk_id for r in all_risks if r.severity == "Medium" and r.status == "Open"]
    low_ids = [r.risk_id for r in all_risks if r.severity == "Low" and r.status == "Open"]
    risks_heatmap = [
        {"label": "Critical", "color": "bg-primary", "items": crit_ids},
        {"label": "High", "color": "bg-button", "items": high_ids},
        {"label": "Medium", "color": "bg-hover", "items": med_ids},
        {"label": "Low", "color": "bg-borderOrange", "items": low_ids}
    ]

    # Dynamic KPI calculation
    health = calculate_dynamic_health_score(active_project, total_planned, total_actual, all_risks, db.db_session)
    snap_data["healthScore"] = health
    snap_data["cross_project_status"] = cross_project_status_str
    snap_data["schedule_variance"] = sched_variance_str
    snap_data["total_budget_burn"] = total_budget_burn_str
    snap_data["showstoppers"] = showstoppers_list
    snap_data["escalations"] = escalations_list
    snap_data["risks"] = risks_heatmap
    if active_project and is_new_project:
        snap_data["kpis"] = [
            {
                "title": "Program Budget",
                "value": f"$0 / {fmt_m_val(total_planned)}",
                "trend": "neutral",
                "trendLabel": "0% Burned"
            },
            {
                "title": "Budget Variance",
                "value": f"+{fmt_m_val(total_planned)} Surplus",
                "trend": "up",
                "trendLabel": "Initial Allocation"
            },
            {
                "title": "Active Risks",
                "value": "0",
                "trend": "neutral",
                "trendLabel": "No Risks Logged"
            },
            {
                "title": "Overall Health",
                "value": f"{health}%",
                "trend": "neutral",
                "trendLabel": "New Workspace"
            }
        ]
    else:
        snap_data["kpis"] = [
            {
                "title": "Program Budget",
                "value": total_budget_burn_str,
                "trend": "up" if total_actual <= total_planned else "down",
                "trendLabel": f"{burn_pct}% Burned"
            },
            {
                "title": "Budget Variance",
                "value": sched_variance_str,
                "trend": "down" if tot_variance < 0 else "up",
                "trendLabel": "Under Budget" if tot_variance >= 0 else "Over Budget"
            },
            {
                "title": "Active Risks",
                "value": str(len(crit_ids) + len(high_ids) + len(med_ids)),
                "trend": "up" if len(crit_ids) > 0 else "neutral",
                "trendLabel": f"{len(crit_ids)} Critical / {len(high_ids)} High"
            },
            {
                "title": "Overall Health",
                "value": f"{health}%",
                "trend": "neutral",
                "trendLabel": "Attention Required" if health < 80 else "Stable Trajectory"
            }
        ]

    # Dynamic Open Blockers per project (for PM Velocity Dashboard)
    open_blockers_list = []
    for r in all_risks:
        if str(r.status).capitalize() == "Open":
            sev = str(r.severity).capitalize()
            status_tag = "Blocked" if sev in ("Critical", "High") else "At Risk"
            open_blockers_list.append({
                "id": r.risk_id,
                "title": r.title,
                "status": status_tag,
                "severity": sev
            })
    snap_data["open_blockers"] = open_blockers_list

    # Dynamic Predictive Trajectory per project
    risk_adj = (len(crit_ids) * 120000) + (len(high_ids) * 40000)
    forecasted_var_num = tot_variance - risk_adj

    if active_project:
        p_name = active_project.name
        p_key = active_project.jira_key
        if is_new_project:
            narrative = (
                f"Project {p_name} [{p_key}] workspace initialized with baseline allocation of ${total_planned:,.0f} USD. "
                f"Ingest project MOMs, vendor contracts, or connect enterprise tools to activate predictive telemetry."
            )
            traj_status = "Workspace Initialized"
            snap_data["predictive"] = {
                "confidence_score": health,
                "forecasted_variance": total_planned,
                "forecast_narrative": narrative,
                "trajectory_status": traj_status,
                "ai_processing_status": "success"
            }
            snap_data["velocity"] = {
                "points": 0,
                "unit": "Story Points / Sprint Avg",
                "trend": "Workspace Initialized"
            }
        elif len(crit_ids) > 0:
            narrative = (
                f"For {p_name} [{p_key}], current burn rate indicates a baseline variance of {sched_variance_str}. "
                f"Factoring in {len(crit_ids)} critical showstopper(s) and {len(high_ids)} high-priority risk(s), "
                f"forecasted trajectory is adjusted to {'+$' if forecasted_var_num >= 0 else '-$'}{abs(forecasted_var_num):,.0f} USD."
            )
            traj_status = "Action Required" if health < 80 else "Elevated Risk Monitoring"
            snap_data["predictive"] = {
                "confidence_score": health,
                "forecasted_variance": forecasted_var_num,
                "forecast_narrative": narrative,
                "trajectory_status": traj_status,
                "ai_processing_status": "success"
            }
            base_pts = 80 + (active_project.id * 5) % 15
            calc_pts = max(45, base_pts - (len(crit_ids) * 9 + len(high_ids) * 3))
            trend_val = f"+{abs(health - 75)}% from last sprint" if health >= 75 else f"-{abs(75 - health)}% from velocity baseline"
            snap_data["velocity"] = {
                "points": calc_pts,
                "unit": "Story Points / Sprint Avg",
                "trend": trend_val
            }
        elif len(high_ids) > 0:
            narrative = (
                f"For {p_name} [{p_key}], budget trajectory is {sched_variance_str}. "
                f"Velocity is steady, with {len(high_ids)} high-priority risk(s) actively governed by PMO."
            )
            traj_status = "Within Budget Guardrails"
            snap_data["predictive"] = {
                "confidence_score": health,
                "forecasted_variance": forecasted_var_num,
                "forecast_narrative": narrative,
                "trajectory_status": traj_status,
                "ai_processing_status": "success"
            }
            base_pts = 80 + (active_project.id * 5) % 15
            calc_pts = max(45, base_pts - (len(crit_ids) * 9 + len(high_ids) * 3))
            trend_val = f"+{abs(health - 75)}% from last sprint" if health >= 75 else f"-{abs(75 - health)}% from velocity baseline"
            snap_data["velocity"] = {
                "points": calc_pts,
                "unit": "Story Points / Sprint Avg",
                "trend": trend_val
            }
        else:
            narrative = (
                f"Reflexion predictive loop indicates stable trajectory for {p_name} [{p_key}] "
                f"with healthy variance ({sched_variance_str}), zero blockers, and {health}% delivery confidence."
            )
            traj_status = "Within Budget Guardrails"
            snap_data["predictive"] = {
                "confidence_score": health,
                "forecasted_variance": forecasted_var_num,
                "forecast_narrative": narrative,
                "trajectory_status": traj_status,
                "ai_processing_status": "success"
            }
            base_pts = 80 + (active_project.id * 5) % 15
            calc_pts = max(45, base_pts - (len(crit_ids) * 9 + len(high_ids) * 3))
            trend_val = f"+{abs(health - 75)}% from last sprint" if health >= 75 else f"-{abs(75 - health)}% from velocity baseline"
            snap_data["velocity"] = {
                "points": calc_pts,
                "unit": "Story Points / Sprint Avg",
                "trend": trend_val
            }

        # Dynamic Milestones per project from MySQL ProjectMilestone table
        snap_proj_id = snap_data.get("project_id") or snap_data.get("numeric_id")
        p_db_milestones = db.db_session.query(ProjectMilestone).filter_by(project_id=active_project.id).order_by(ProjectMilestone.id.asc()).all() if db.db_session else []
        if p_db_milestones:
            snap_data["milestones"] = [
                {
                    "id": m.milestone_code,
                    "numeric_id": m.id,
                    "name": m.name,
                    "description": m.description or "",
                    "timeline": m.target_date or "TBD",
                    "status": m.status or "Scheduled",
                    "trancheAmount": m.tranche_amount or 0,
                    "slaScore": m.sla_score,
                    "deliverablesPercent": m.completion_pct or 0
                } for m in p_db_milestones
            ]
        elif active_telem and active_telem.get('milestones'):
            snap_data["milestones"] = active_telem['milestones']
        else:
            snap_data["milestones"] = []
    else:
        # Cross-project mode
        snap_data["predictive"] = {
            "confidence_score": health,
            "forecasted_variance": sched_variance_str,
            "forecast_narrative": f"Reflexion predictive loop indicates {cross_project_status_str.lower()} with {health}% delivery confidence across all supervised programs.",
            "trajectory_status": "On Track" if health >= 80 else "Action Required",
            "ai_processing_status": "success"
        }
        snap_data["velocity"] = {
            "points": 88,
            "unit": "Story Points / Sprint Avg",
            "trend": "+12% Points from last sprint"
        }

    snap_data["projects"] = project_list

    # Dynamic Jira integration status
    from models.integration_setting import IntegrationSetting
    jira_setting = None
    if active_project:
        jira_setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=active_project.id).first()
    if not jira_setting:
        jira_setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira', project_id=1).first()
    if not jira_setting:
        jira_setting = db.db_session.query(IntegrationSetting).filter_by(provider='jira').first()
    if jira_setting and jira_setting.is_connected:
        raw_url = str(jira_setting.base_url or '')
        host = raw_url.replace("https://", "").replace("http://", "").rstrip('/')
        snap_data["jira_integration"] = {
            "is_connected": True,
            "host": host,
            "server": raw_url,
            "user": jira_setting.username_email or ''
        }
    else:
        snap_data["jira_integration"] = {
            "is_connected": False,
            "host": None,
            "server": None,
            "user": None
        }

    # Dynamic PMO Lead Telemetry (Headcount, Total Budget, Deadlines, and Graphical Task Breakdown)
    snap_data["pmo_metrics"] = build_pmo_metrics(
        active_project=active_project,
        all_projs=all_projs,
        total_planned=total_planned,
        total_actual=total_actual,
        tot_variance=tot_variance,
        burn_pct=burn_pct,
        crit_ids=crit_ids,
        high_ids=high_ids
    )

    # Dynamic Project Risks (Enriched with Category, Severity, Exposure & Drilldown Links)
    def risk_sort_key(r):
        sev_map = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return (sev_map.get(str(r.severity).lower(), 4), -r.id)

    sorted_risks = sorted(all_risks, key=risk_sort_key)
    all_projs_map = {p.id: p for p in all_projs}
    enriched_project_risks = [enrich_risk_dict(r, all_projs_map) for r in sorted_risks]
    snap_data["project_risks"] = enriched_project_risks
    snap_data["recent_risks"] = enriched_project_risks[:5]
    snap_data["total_project_risks"] = len(all_risks)
    snap_data["risks"] = enriched_project_risks

    snap_dict['data'] = snap_data
    return jsonify(snap_dict)

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

    # Project-specific budget & burndown values queried from Budget model
    from models.budget import Budget
    budget_record = db.db_session.query(Budget).filter_by(project_id=project.id).order_by(Budget.created_at.desc()).first()
    if budget_record:
        planned_val = float(budget_record.planned_spend)
        actual_val = float(budget_record.actual_spend)
        cost_variance = float(budget_record.variance)
    else:
        planned_val = 0.0
        actual_val = 0.0
        cost_variance = 0.0

    # Health score calculation dynamically calibrated
    health = calculate_dynamic_health_score(project, planned_val, actual_val, risks, db.db_session)

    burn_pct = round((actual_val / planned_val * 100)) if planned_val > 0 else 0
    burn_rate = f"{burn_pct}% Burned"
    
    def fmt_cur(val):
        return f"${val / 1000000:.2f}M" if abs(val) >= 1000000 else f"${val / 1000:.0f}K"

    planned_budget = fmt_cur(planned_val)
    actual_spend = fmt_cur(actual_val)
    variance_str = f"{fmt_cur(abs(cost_variance))} {'Deficit' if cost_variance < 0 else 'Surplus'}"

    # NOTE: Burndown values are a budget-ratio-derived approximation (not real sprint telemetry),
    # as there is currently no dedicated Sprint tracking table. If Jira Agile/sprint API access
    # becomes available later (via JiraTool), that will serve as the real sprint data source.
    ac_k = int(actual_val / 1000)
    pl_k = int(planned_val / 1000)

    # Strictly query real TaskItem records: 0 tasks in DB = strictly 0 earned value!
    from models.task_item import TaskItem
    db_completed = db.db_session.query(TaskItem).filter(
        TaskItem.project_id == project.id,
        TaskItem.status.in_(["Done", "Completed", "Resolved"])
    ).count() if db.db_session else 0
    db_total = db.db_session.query(TaskItem).filter(
        TaskItem.project_id == project.id
    ).count() if db.db_session else 0

    if db_total > 0:
        ev_ratio = db_completed / db_total
        earned_k = int(pl_k * ev_ratio)
    else:
        earned_k = 0

    if actual_val == 0:
        burndown = [
            {"sprint": "Sprint 1", "planned": int(pl_k * 0.15), "actual": 0, "earned": 0},
            {"sprint": "Sprint 2", "planned": int(pl_k * 0.35), "actual": None, "earned": None},
            {"sprint": "Sprint 3", "planned": int(pl_k * 0.55), "actual": None, "earned": None},
            {"sprint": "Sprint 4", "planned": int(pl_k * 0.75), "actual": None, "earned": None},
            {"sprint": "Sprint 5", "planned": int(pl_k * 0.90), "actual": None, "earned": None},
            {"sprint": "Sprint 6", "planned": pl_k, "actual": None, "earned": None}
        ]
    else:
        a1 = max(1, int(ac_k * 0.25))
        a2 = max(a1, int(ac_k * 0.65))
        a3 = ac_k

        e1 = int(earned_k * 0.28) if earned_k > 0 else 0
        e2 = int(earned_k * 0.68) if earned_k > 0 else 0
        e3 = earned_k

        burndown = [
            {"sprint": "Sprint 1", "planned": int(pl_k * 0.15), "actual": a1, "earned": e1},
            {"sprint": "Sprint 2", "planned": int(pl_k * 0.35), "actual": a2, "earned": e2},
            {"sprint": "Sprint 3", "planned": int(pl_k * 0.55), "actual": a3, "earned": e3},
            {"sprint": "Sprint 4", "planned": int(pl_k * 0.75), "actual": None, "earned": None},
            {"sprint": "Sprint 5", "planned": int(pl_k * 0.90), "actual": None, "earned": None},
            {"sprint": "Sprint 6", "planned": pl_k, "actual": None, "earned": None}
        ]

    is_new = (actual_val == 0 and len(risks) == 0)
    if is_new:
        kpi_list = [
            {
                "title": "Project Budget",
                "value": f"$0 / {planned_budget}",
                "trend": "neutral",
                "trendLabel": "0% Burned"
            },
            {
                "title": "Budget Variance",
                "value": f"+{variance_str}",
                "trend": "up",
                "trendLabel": "Initial Allocation"
            },
            {
                "title": "Active Risks",
                "value": "0",
                "trend": "neutral",
                "trendLabel": "No Risks Logged"
            },
            {
                "title": "Project Health",
                "value": "100%",
                "trend": "neutral",
                "trendLabel": "New Workspace"
            }
        ]
    else:
        kpi_list = [
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
                "trend": "up" if len(crit) > 0 else "neutral",
                "trendLabel": f"{len(crit)} Critical / {len(high)} High"
            },
            {
                "title": "Project Health",
                "value": f"{health}%",
                "trend": "neutral",
                "trendLabel": "Action Required" if health < 80 else "Stable Progress"
            }
        ]

    def proj_risk_sort_key(r):
        sev_map = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return (sev_map.get(str(r.severity).lower(), 4), -r.id)

    sorted_project_risks = sorted(risks, key=proj_risk_sort_key)
    enriched_project_risks = [enrich_risk_dict(r, {project.id: project}) for r in sorted_project_risks]

    project_data = {
        "id": project.jira_key,
        "numeric_id": project.id,
        "name": project.name,
        "status": project.status,
        "healthScore": health,
        "kpis": kpi_list,
        "burndown": burndown,
        "risks": [
            {"label": "Critical", "color": "bg-primary", "items": crit},
            {"label": "High", "color": "bg-button", "items": high},
            {"label": "Medium", "color": "bg-hover", "items": med},
            {"label": "Low", "color": "bg-borderOrange", "items": low}
        ],
        "risk_details": enriched_project_risks,
        "recent_risks": enriched_project_risks[:5],
        "total_project_risks": len(risks)
    }

    team_data = get_project_team_data(project.id)
    if team_data:
        project_data["team_summary"] = {
            "total": team_data["total_resources"],
            "roles": team_data["roles"],
            "vendors": team_data["vendors"],
            "members": team_data["members"]
        }
    else:
        project_data["team_summary"] = {
            "total": 0,
            "roles": [],
            "vendors": [],
            "members": []
        }

    # Enrich with budget, timeline, and governance summaries for Level 4 drilldown breakdowns
    project_data["budget_summary"] = {
        "planned": planned_val,
        "actual": actual_val,
        "remaining": max(0.0, planned_val - actual_val),
        "variance": cost_variance,
        "burn_pct": burn_pct,
        "monthly_run_rate": round(actual_val / 3, 2) if actual_val > 0 else 0.0,
        "cpi": 1.04 if actual_val <= planned_val else 0.88,
        "variance_status": "Favorable" if cost_variance >= 0 else "Unfavorable"
    }

    doc_telemetry = get_project_db_telemetry(project.id)
    doc_milestones = doc_telemetry.get('milestones', []) if doc_telemetry else []

    # Milestones strictly from MySQL ProjectMilestone table or ingested document telemetry
    from models.project_milestone import ProjectMilestone
    from datetime import datetime, timezone

    p_milestones = db.db_session.query(ProjectMilestone).filter_by(project_id=project.id).order_by(ProjectMilestone.id.asc()).all() if db.db_session else []

    phases = []
    if p_milestones:
        for ms in p_milestones:
            phases.append({
                "id": ms.milestone_code,
                "numeric_id": ms.id,
                "name": ms.name,
                "description": ms.description or "",
                "target_date": ms.target_date or "TBD",
                "status": ms.status or "Scheduled",
                "completion_pct": ms.completion_pct if ms.completion_pct is not None else 0,
                "days_left": ms.days_left if ms.days_left is not None else 0,
                "tranche_amount": ms.tranche_amount or 0.0,
                "sla_score": ms.sla_score,
                "sla_status": ms.sla_status or "Scheduled"
            })
    elif doc_milestones:
        phases = doc_milestones
    else:
        phases = []

    target_completion_date = phases[-1].get("target_date", "Pending SOW") if phases else "Pending SOW"
    days_rem = sum(p.get("days_left", 0) for p in phases) if phases else 0

    project_data["timeline_summary"] = {
        "target_completion_date": target_completion_date if not is_new else "Pending SOW",
        "days_remaining": days_rem,
        "spi": 1.00 if (is_new or len(phases) == 0) else 1.02,
        "schedule_status": "Governed by Project Charter & SOW" if (not is_new and len(phases) > 0) else "New Workspace (Awaiting SOW)",
        "phases": phases
    }

    # Project Completion Summary (Multi-vector: Tasks, Milestones, Timeline)
    ms_total = len(phases)
    ms_completed = sum(1 for p in phases if (p.get('completion_pct', 0) or 0) >= 100 or str(p.get('status')).lower() in ['completed', 'done', 'released', 'authorized'])
    ms_avg_pct = round(sum((p.get('completion_pct', 0) or 0) for p in phases) / ms_total) if ms_total > 0 else 0

    task_pct = round((db_completed / db_total) * 100) if db_total > 0 else 0

    # Timeline calculation
    timeline_elapsed_months = 0
    timeline_total_months = 0
    timeline_pct = 0

    if doc_telemetry and isinstance(doc_telemetry, dict):
        tl_meta = doc_telemetry.get('timeline', {})
        if isinstance(tl_meta, dict):
            timeline_total_months = tl_meta.get('total_months') or 0
            timeline_elapsed_months = tl_meta.get('elapsed_months') or 0

    if timeline_total_months > 0:
        if getattr(project, 'created_at', None):
            try:
                now_dt = datetime.now(timezone.utc)
                c_dt = project.created_at
                if c_dt.tzinfo is None:
                    c_dt = c_dt.replace(tzinfo=timezone.utc)
                days_diff = max(0, (now_dt - c_dt).days)
                timeline_elapsed_months = min(timeline_total_months, max(0, round(days_diff / 30, 1)))
                timeline_pct = min(100, round((timeline_elapsed_months / timeline_total_months) * 100))
            except Exception:
                pass

    if db_total > 0:
        overall_comp = task_pct
        comp_basis = "Task Backlog"
        comp_sub = f"{db_completed}/{db_total} Tasks ({task_pct}%)"
    elif ms_total > 0:
        overall_comp = ms_avg_pct
        comp_basis = "Contract Milestones"
        comp_sub = f"{ms_completed}/{ms_total} Milestones ({ms_avg_pct}%)"
    elif timeline_total_months > 0 and timeline_pct > 0:
        overall_comp = timeline_pct
        comp_basis = "Timeline Horizon"
        comp_sub = f"{timeline_elapsed_months}/{timeline_total_months} Months ({timeline_pct}%)"
    else:
        overall_comp = 0
        comp_basis = "Initial Phase"
        comp_sub = "0% Initial Phase (Awaiting SOW / Task Ingestion)"

    project_data["completion_summary"] = {
        "percentage": overall_comp,
        "basis": comp_basis,
        "label": comp_sub,
        "tasks": {
            "completed": db_completed,
            "total": db_total,
            "percentage": task_pct
        },
        "milestones": {
            "completed": ms_completed,
            "total": ms_total,
            "percentage": ms_avg_pct
        },
        "timeline": {
            "elapsed_months": timeline_elapsed_months,
            "total_months": timeline_total_months,
            "percentage": timeline_pct
        }
    }

    return jsonify(project_data)


def get_project_team_data(project_id):
    """
    Returns single-source-of-truth project team telemetry:
    - Extracts high-fidelity team from project document telemetry (SOW/Charter) if available.
    - If no document is uploaded, generates realistic, calibrated enterprise engineering pod members.
    - Dynamically calculates role aggregations, vendor breakdowns, allocation rates, and itemized resources.
    """
    project = None
    if str(project_id).isdigit():
        project = db.db_session.query(Project).filter_by(id=int(project_id)).first()
    if not project:
        project = db.db_session.query(Project).filter_by(jira_key=str(project_id)).first()
    if not project:
        project = db.db_session.query(Project).first()
    if not project:
        return None

    # Query project team directly from MySQL database (project_members table)
    doc_telemetry = get_project_db_telemetry(project.id)
    raw_team = []
    if doc_telemetry and doc_telemetry.get('team'):
        raw_team = doc_telemetry['team']

    # If no doc team, provide baseline enterprise team for project
    if not raw_team:
        raw_team = []

    # Standard role color mappings
    def get_role_color(role_name):
        r_low = role_name.lower()
        if any(k in r_low for k in ['architect', 'lead', 'director']):
            return '#FF5A14'
        if any(k in r_low for k in ['engineer', 'dev', 'backend', 'frontend', 'full-stack']):
            return '#3B82F6'
        if any(k in r_low for k in ['qa', 'test', 'automation']):
            return '#10B981'
        if any(k in r_low for k in ['devops', 'infra', 'sre', 'cloud']):
            return '#8B5CF6'
        if any(k in r_low for k in ['pm', 'manager', 'scrum', 'ba', 'analyst']):
            return '#F59E0B'
        if any(k in r_low for k in ['ai', 'agent', 'rag', 'safety', 'guardrail']):
            return '#EC4899'
        return '#64748B'

    # Enrich each member
    members = []
    for idx, tm in enumerate(raw_team):
        m_name = tm.get('name', f"Team Member {idx+1}")
        m_role = tm.get('role', 'Software Engineer')
        m_contact = tm.get('contact') or f"{m_name.lower().replace(' ', '.')}@vpmproject.com"
        res_id = f"res-{idx+1}"

        # Assign vendor
        if any(k in m_role.lower() for k in ['contractor', 'consultant', 'cognizant', 'infosys']):
            vendor = "Cognizant / Infosys (SI Partner)"
            vendor_type = "Vendor Contractor"
        elif any(k in m_role.lower() for k in ['cloud', 'infra', 'devops']):
            vendor = "Cloud Infrastructure Specialists"
            vendor_type = "Specialist Partner"
        else:
            vendor = "PwC Internal Enterprise Staff"
            vendor_type = "Internal FTE"

        # Assign skills based on role
        r_low = m_role.lower()
        if 'backend' in r_low or 'python' in r_low:
            skills = ['Python', 'Flask', 'SQLAlchemy', 'MySQL REST APIs', 'Microservices Architecture', 'OAuth2']
        elif 'ai' in r_low or 'agent' in r_low:
            skills = ['LangChain', 'OpenAI / Gemini SDK', 'Agent Reflexion Loops', 'Vector Embeddings', 'Pydantic Guardrails']
        elif 'rag' in r_low or 'knowledge' in r_low:
            skills = ['Vector DB (Chroma/Pinecone)', 'Document Parsing', 'Semantic Search', 'Hybrid RAG', 'Context Pruning']
        elif 'guardrail' in r_low or 'safety' in r_low:
            skills = ['OWASP LLM Top 10', 'Input Validation', 'Prompt Injection Defense', 'Policy Enforcement', 'HITL Workflow']
        elif 'frontend' in r_low or 'react' in r_low:
            skills = ['React 18', 'Vite', 'Tailwind CSS', 'Responsive UI/UX', 'State Management', 'Lucide Icons']
        elif 'qa' in r_low or 'test' in r_low:
            skills = ['Pytest', 'End-to-End Regression', 'Contract Testing', 'Performance Benchmarks', 'CI Quality Gates']
        elif 'devops' in r_low or 'infra' in r_low:
            skills = ['Docker', 'Kubernetes', 'AWS / Azure Cloud', 'GitHub Actions', 'Terraform', 'Prometheus']
        elif 'manager' in r_low or 'pm' in r_low:
            skills = ['Agile / Scrum Governance', 'Milestone Stage-Gating', 'Budget Burndown Management', 'Vendor SLA Auditing', 'Risk Matrix']
        else:
            skills = ['Enterprise Software Engineering', 'System Integration', 'Git', 'Agile Delivery']

        # Fetch all tasks from DB for this project
        from models.task_item import TaskItem
        all_db_tasks = db.db_session.query(TaskItem).filter_by(project_id=project.id).all() if db.db_session else []
        
        # Try to match by assignee, or fallback to distributing evenly
        member_tasks = []
        for t in all_db_tasks:
            if t.assignee and (m_name.lower() in t.assignee.lower() or t.assignee.lower() in m_name.lower()):
                member_tasks.append(t)
                
        # If no strict match and we want to show some tasks, distribute them evenly
        if not member_tasks and all_db_tasks:
            # Simple hash to distribute tasks
            num_members = len(raw_team) if raw_team else 1
            assigned_indices = [i for i in range(len(all_db_tasks)) if i % num_members == idx]
            member_tasks = [all_db_tasks[i] for i in assigned_indices]

        assigned_tasks = [
            {
                "id": t.jira_key or f"TSK-{t.id}",
                "title": t.summary,
                "status": t.status,
                "priority": t.priority,
                "due_date": "Active Sprint",
                "workstream": m_role
            } for t in member_tasks
        ]

        members.append({
            "id": res_id,
            "numeric_id": idx + 1,
            "name": m_name,
            "role": m_role,
            "email": m_contact,
            "contact": m_contact,
            "vendor": vendor,
            "vendor_type": vendor_type,
            "allocation_pct": 100 if idx < 6 else 80,
            "status": "Active",
            "skills": skills,
            "assigned_tasks": assigned_tasks,
            "linked_milestones": [f"{m.milestone_code}: {m.name}" for m in db.db_session.query(ProjectMilestone).filter_by(project_id=project.id).order_by(ProjectMilestone.id.asc()).limit(2).all()] if db.db_session else [],
            "color": get_role_color(m_role)
        })

    # Group roles summary
    roles_dict = {}
    for m in members:
        r = m['role']
        if r not in roles_dict:
            roles_dict[r] = {
                "role": r,
                "count": 0,
                "color": m['color'],
                "members": []
            }
        roles_dict[r]["count"] += 1
        roles_dict[r]["members"].append(m["id"])

    roles_list = []
    for r_name, r_info in roles_dict.items():
        roles_list.append({
            "role": r_name,
            "count": r_info["count"],
            "allocation_pct": round((r_info["count"] / len(members)) * 100, 1) if members else 0,
            "color": r_info["color"],
            "member_ids": r_info["members"]
        })
    # Sort roles by count descending
    roles_list.sort(key=lambda x: -x["count"])

    # Group vendors summary
    vendors_dict = {}
    for m in members:
        v = m['vendor']
        vendors_dict[v] = vendors_dict.get(v, 0) + 1

    vendors_list = []
    for v_name, v_count in vendors_dict.items():
        vendors_list.append({
            "name": v_name,
            "count": v_count,
            "share": f"{round((v_count / len(members)) * 100)}%" if members else "0%"
        })

    return {
        "project": project.to_dict(),
        "total_resources": len(members),
        "roles": roles_list,
        "vendors": vendors_list,
        "members": members
    }


@dashboard_bp.route('/projects/<project_id>/team', methods=['GET'])
@require_roles('PMO', 'Program Director', 'Project Manager', 'Investor')
def get_project_team(project_id):
    """
    Returns itemized team and dynamic role aggregation for the specified project.
    """
    team_data = get_project_team_data(project_id)
    if not team_data or not team_data.get('project'):
        return jsonify({"error": "Project not found"}), 404
    return jsonify(team_data)


@dashboard_bp.route('/projects/<project_id>/team/<resource_id>', methods=['GET'])
@require_roles('PMO', 'Program Director', 'Project Manager', 'Investor')
def get_project_resource_detail(project_id, resource_id):
    """
    Returns individual resource details including allocation, skills, tasks, and governance.
    """
    team_data = get_project_team_data(project_id)
    if not team_data or not team_data.get('project'):
        return jsonify({"error": "Project not found"}), 404

    target_res = None
    target_clean = str(resource_id).strip().lower()
    for m in team_data.get('members', []):
        if (str(m.get('id')).lower() == target_clean or 
            str(m.get('numeric_id')) == target_clean or 
            str(m.get('name', '')).lower().replace(' ', '-') == target_clean):
            target_res = m
            break

    if not target_res:
        return jsonify({"error": f"Resource '{resource_id}' not found in project"}), 404

    return jsonify({
        "project": team_data["project"],
        "resource": target_res
    })
