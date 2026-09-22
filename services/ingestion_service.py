import os
import json
import random
import time
from orchestrator.workflow import Orchestrator
from agents.intake_agent.agent import IntakeAgent
from agents.financial_agent.agent import FinancialAgent
from agents.risk_agent.agent import RiskAgent
from agents.predictive_agent.agent import PredictiveAgent
from agents.kpi_agent.agent import KPIAgent
from agents.reporting_agent.agent import ReportingAgent
import db
from models.dashboard_snapshot import DashboardSnapshot
from models.risk_register import RiskRegister
from models.approval_queue import ApprovalQueue

class IngestionService:
    @staticmethod
    def process_file(file_path: str, project_id: int):
        """
        Runs the VPM workflow:
        Intake -> [Financial, Risk (parallel)] -> Predictive -> KPI -> Reporting
        Persists newly detected risks to RiskRegister and saves DashboardSnapshot.
        """
        orchestrator = Orchestrator()
        
        # Resolve project and query Jira integration data
        from models.project import Project
        from models.budget import Budget
        from tools.jira_tool import JiraTool

        proj = db.db_session.query(Project).filter_by(id=project_id).first()
        jira_key = proj.jira_key if proj else f"PRJ-{project_id}"
        
        jira_data = JiraTool.execute(project_key=jira_key, project_id=project_id)
        jira_issues = jira_data.get("issues", [])
        
        # 1. Intake
        intake_agent = IntakeAgent()
        orchestrator.add_node("intake", intake_agent.execute)
        
        # 2. Parallel Processing
        fin_agent = FinancialAgent()
        risk_agent = RiskAgent()
        
        def financial_wrapper(inputs):
            intake_out = inputs.get("intake", {})
            b_rec = db.db_session.query(Budget).filter_by(project_id=project_id).first()
            def_planned = float(b_rec.planned_spend) if b_rec else 0.0
            def_actual = float(b_rec.actual_spend) if b_rec else 0.0
            in_pl = intake_out.get("budget_planned")
            in_ac = intake_out.get("budget_actual")
            return fin_agent.execute({
                "project_id": project_id,
                "period": "Current",
                "budget_planned": float(in_pl) if in_pl is not None else def_planned,
                "budget_actual": float(in_ac) if in_ac is not None else def_actual
            })
            
        def risk_wrapper(inputs):
            intake_out = inputs.get("intake", {})
            p_name = intake_out.get("project_name", f"Project {project_id}")
            
            # Extract complete document text and all tables for thorough risk intelligence
            doc_content = ""
            if file_path and os.path.exists(file_path):
                try:
                    from tools.doc_tool import DocTool
                    doc_content = DocTool.parse_file(file_path)
                except Exception as ex:
                    logger.warning(f"Could not parse doc with DocTool in risk_wrapper: {ex}")

            context = (
                f"Project Name: {p_name}\n"
                f"Project Status: {intake_out.get('status', 'Active')}\n"
                f"Document Path: {file_path}\n"
                f"Document Full Text and Tables:\n{doc_content if doc_content else json.dumps(intake_out.get('risks', []))}\n\n"
                f"Active Jira Issues for Project:\n{json.dumps(jira_issues)}"
            )
            
            # Fetch existing active project risks to give agent contextual awareness and enable deduplication
            curr_risks = []
            try:
                if db.db_session:
                    db_r = db.db_session.query(RiskRegister).filter_by(project_id=project_id).all()
                    curr_risks = [
                        {
                            "id": r.risk_id,
                            "title": r.title,
                            "severity": r.severity or "Medium",
                            "status": r.status or "Open",
                            "description": r.description or r.title,
                            "mitigation_plan": r.mitigation_plan or ""
                        }
                        for r in db_r
                    ]
            except Exception as e:
                logger.warning(f"Error fetching existing risks for risk_wrapper: {e}")
                curr_risks = []

            return risk_agent.execute({
                "project_id": str(project_id),
                "project_name": p_name,
                "context_data": context,
                "current_risks": curr_risks,
                "intake": intake_out
            })
            
        orchestrator.add_node("financial", financial_wrapper)
        orchestrator.add_node("risk", risk_wrapper)
        
        # 3. Predictive
        pred_agent = PredictiveAgent()
        def predictive_wrapper(inputs):
            return pred_agent.execute({
                "current_variance": float(inputs.get("financial", {}).get("variance", 0.0) or 0.0),
                "risks": inputs.get("risk", {}).get("risks", []),
                "project_status": inputs.get("intake", {}).get("status", "Active")
            })
            
        orchestrator.add_node("predictive", predictive_wrapper)
        
        # 4. KPI
        kpi_agent = KPIAgent()
        def kpi_wrapper(inputs):
            return kpi_agent.execute({
                "project_id": project_id,
                "variance": float(inputs.get("financial", {}).get("variance", 0.0) or 0.0),
                "risks": inputs.get("risk", {}).get("risks", []),
                "forecast_confidence": int(inputs.get("predictive", {}).get("confidence_score", 78) or 78)
            })
            
        orchestrator.add_node("kpi", kpi_wrapper)
        
        # 5. Reporting
        rep_agent = ReportingAgent()
        def reporting_wrapper(inputs):
            # Pass all active project risks plus newly detected risks so executive report reflects whole project
            detected = inputs.get("risk", {}).get("risks", [])
            all_known = list(detected)
            try:
                if db.db_session:
                    db_r = db.db_session.query(RiskRegister).filter_by(project_id=project_id, status="Open").all()
                    for r in db_r:
                        if not any(d.get("title", "").strip().lower() == r.title.strip().lower() for d in detected if isinstance(d, dict)):
                            all_known.append({
                                "id": r.risk_id,
                                "title": r.title,
                                "severity": r.severity or "Medium",
                                "status": r.status or "Open",
                                "description": r.description or r.title
                            })
            except Exception:
                pass

            return rep_agent.execute({
                "project_id": project_id,
                "kpis": inputs.get("kpi", {}).get("kpis", []),
                "financials": inputs.get("financial", {}),
                "risks": all_known,
                "predictive": inputs.get("predictive", {})
            })
            
        orchestrator.add_node("reporting", reporting_wrapper)
        
        # Define edges
        orchestrator.add_edge("intake", ["financial", "risk"])
        orchestrator.add_edge("financial", ["predictive"])
        orchestrator.add_edge("risk", ["predictive"])
        orchestrator.add_edge("predictive", ["kpi"])
        orchestrator.add_edge("kpi", ["reporting"])
        
        # Run workflow
        initial_input = {"intake": {"file_path": file_path, "project_id": project_id}}
        final_state = orchestrator.execute("intake", initial_input)
        
        # Extract detected risks and persist to RiskRegister
        risk_output = final_state.get("risk", {})
        detected_risks = risk_output.get("risks", []) or risk_output.get("detected_risks", [])
        
        # Resolve valid project for foreign key integrity
        from models.project import Project

        proj = db.db_session.query(Project).filter_by(id=project_id).first()
        if not proj:
            proj = db.db_session.query(Project).first()
            if not proj:
                proj = Project(jira_key=f"PRJ-{project_id}", name=f"Project {project_id}")
                db.db_session.add(proj)
                db.db_session.commit()
            project_id = proj.id

        # Allocate clean canonical ID RSK-### and semantically deduplicate
        all_p_risks = db.db_session.query(RiskRegister).filter_by(project_id=project_id).all()
        used_ids = {r.risk_id for r in all_p_risks}
        
        def get_next_canonical_id():
            next_n = 1
            while f"RSK-{next_n:03d}" in used_ids:
                next_n += 1
            new_id = f"RSK-{next_n:03d}"
            used_ids.add(new_id)
            return new_id

        for idx, r in enumerate(detected_risks):
            r_title = r.get("title") if isinstance(r, dict) and r.get("title") else str(r)
            if not r_title or r_title.lower() in ('total', 'subtotal', 'risk', 'finding', 'item', 'n/a'):
                continue

            r_id = r.get("id") if isinstance(r, dict) and r.get("id") else None
            r_desc = r.get("description") if isinstance(r, dict) and r.get("description") else r_title
            r_sev = r.get("severity", "Medium") if isinstance(r, dict) else "Medium"
            r_status = r.get("status", "Open") if isinstance(r, dict) else "Open"
            r_mitigation = r.get("mitigation_plan", "") if isinstance(r, dict) else "Under PM review"

            # Normalize severity
            if any(k in str(r_sev).lower() for k in ['crit', 'blocker']):
                r_sev = "Critical"
            elif any(k in str(r_sev).lower() for k in ['high', 'elevated', 'major']):
                r_sev = "High"
            elif any(k in str(r_sev).lower() for k in ['low', 'minor']):
                r_sev = "Low"
            else:
                r_sev = "Medium"
            
            # 1. Match by exact canonical risk_id if valid
            existing = None
            if r_id and not any(r_id.upper().startswith(p) for p in ['R-1-', 'R-0', 'SEC-', 'FINDING-']):
                existing = db.db_session.query(RiskRegister).filter_by(project_id=project_id, risk_id=r_id).first()
            
            # 2. If not matched by ID, check for match by normalized title or semantic containment
            if not existing and r_title:
                clean_t = r_title.strip().lower()
                for pr in all_p_risks:
                    pr_title = (pr.title or "").strip().lower()
                    if pr_title == clean_t or (len(clean_t) > 12 and (clean_t in pr_title or pr_title in clean_t)):
                        existing = pr
                        break

            if existing:
                # Update existing risk details without creating a duplicate record
                existing.title = r_title
                existing.description = r_desc or existing.description
                existing.severity = r_sev or existing.severity
                existing.status = r_status or existing.status
                if r_mitigation and r_mitigation != "Under PM review":
                    existing.mitigation_plan = r_mitigation
            else:
                # Assign clean canonical ID RSK-###
                if not r_id or any(r_id.upper().startswith(p) for p in ['R-1-', 'R-0', 'SEC-', 'FINDING-']) or r_id in used_ids:
                    assigned_id = get_next_canonical_id()
                else:
                    assigned_id = r_id
                    used_ids.add(assigned_id)

                new_risk = RiskRegister(
                    project_id=project_id,
                    risk_id=assigned_id,
                    title=r_title,
                    description=r_desc,
                    severity=r_sev,
                    status=r_status,
                    mitigation_plan=r_mitigation
                )
                db.db_session.add(new_risk)
                all_p_risks.append(new_risk)
        db.db_session.commit()
                
        # Enqueue escalations if detected
        escalations = risk_output.get("escalations", [])
        for esc in escalations:
            queue_item = ApprovalQueue(
                action_type="escalate_risk",
                payload={"project_id": project_id, "escalation": esc},
                status="Pending",
                reasoning=f"Automatic escalation detected by RiskAgent for project {project_id}"
            )
            db.db_session.add(queue_item)

        # Extract and persist tasks from the document
        from models.task_item import TaskItem
        from datetime import datetime, timezone
        
        extracted_tasks = final_state.get("intake", {}).get("tasks", [])
        if extracted_tasks and len(extracted_tasks) > 0:
            for idx, t in enumerate(extracted_tasks):
                t_title = t.get("title", f"Document Task {idx}") if isinstance(t, dict) else str(t)
                t_status = t.get("status", "To Do") if isinstance(t, dict) else "To Do"
                t_assignee = t.get("assignee", "Unassigned") if isinstance(t, dict) else "Unassigned"
                
                # Check if a task with this summary already exists to avoid duplicates
                existing_t = db.db_session.query(TaskItem).filter_by(project_id=project_id, summary=t_title).first()
                if existing_t:
                    existing_t.status = t_status
                    existing_t.assignee = t_assignee
                    existing_t.updated_at = datetime.now(timezone.utc)
                else:
                    new_task = TaskItem(
                        project_id=project_id,
                        jira_key=f"DOC-{project_id}-{idx+100}",
                        summary=t_title,
                        status=t_status,
                        priority="Medium",
                        assignee=t_assignee,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    db.db_session.add(new_task)
            db.db_session.commit()

        # Determine overall AI processing status across pipeline agents
        intake_status = final_state.get("intake", {}).get("ai_processing_status")
        risk_status = risk_output.get("ai_processing_status")
        financial_status = final_state.get("financial", {}).get("ai_processing_status")
        kpi_status = final_state.get("kpi", {}).get("ai_processing_status")
        predictive_status = final_state.get("predictive", {}).get("ai_processing_status")
        ai_proc_status = "degraded_fallback" if (
            intake_status == "degraded_fallback"
            or risk_status == "degraded_fallback"
            or financial_status == "degraded_fallback"
            or kpi_status == "degraded_fallback"
            or predictive_status == "degraded_fallback"
        ) else "success"

        # Save snapshot
        snapshot_data = final_state.get("reporting", {}).get("dashboard_data", {})
        if isinstance(snapshot_data, dict):
            snapshot_data["ai_processing_status"] = ai_proc_status
            snapshot_data["jira_synced"] = jira_data.get("success", False)
            snapshot_data["jira_issues_count"] = len(jira_issues)

            # Ensure snapshot reflects all current active project risks in RiskRegister
            all_db_open = db.db_session.query(RiskRegister).filter_by(project_id=project_id, status="Open").all()
            total_active = len(all_db_open)
            crit_active = sum(1 for r in all_db_open if r.severity == "Critical")
            high_active = sum(1 for r in all_db_open if r.severity == "High")
            
            if "kpis" in snapshot_data and isinstance(snapshot_data["kpis"], list):
                for kpi in snapshot_data["kpis"]:
                    if kpi.get("title") == "Active Risks":
                        kpi["value"] = str(total_active)
                        kpi["trendLabel"] = f"{crit_active} Critical / {high_active} High"

            # Dynamic Milestone Attainment & Tranche Handling
            intake_milestones = final_state.get("intake", {}).get("milestones", [])
            if intake_milestones and len(intake_milestones) > 0:
                snapshot_data["milestones"] = intake_milestones
            else:
                # Retain existing milestone telemetry from previous snapshot if not overridden by SOW
                prev_snap = db.db_session.query(DashboardSnapshot).order_by(DashboardSnapshot.created_at.desc()).first()
                if prev_snap:
                    prev_data = prev_snap.to_dict().get("data", {})
                    if isinstance(prev_data, dict) and prev_data.get("milestones"):
                        snapshot_data["milestones"] = prev_data["milestones"]

        snapshot = DashboardSnapshot(
            data=snapshot_data
        )
        db.db_session.add(snapshot)
        db.db_session.commit()
        
        return {
            "status": "success",
            "snapshot_id": snapshot.id,
            "risks_detected": len(detected_risks),
            "escalations_count": len(escalations),
            "ai_processing_status": ai_proc_status,
            "jira_issues_count": len(jira_issues)
        }

