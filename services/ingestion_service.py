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
        
        jira_data = JiraTool.execute(project_key=jira_key)
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
            def_planned = float(b_rec.planned_spend) if b_rec else 1500000.0
            def_actual = float(b_rec.actual_spend) if b_rec else 1200000.0
            return fin_agent.execute({
                "project_id": project_id,
                "period": "Current",
                "budget_planned": float(intake_out.get("budget_planned", def_planned) or def_planned),
                "budget_actual": float(intake_out.get("budget_actual", def_actual) or def_actual)
            })
            
        def risk_wrapper(inputs):
            intake_out = inputs.get("intake", {})
            p_name = intake_out.get("project_name", f"Project {project_id}")
            context = f"Project: {p_name}. Status: {intake_out.get('status', 'Active')}. Extracted risks: {json.dumps(intake_out.get('risks', []))}. Jira Issues: {json.dumps(jira_issues)}"
            return risk_agent.execute({
                "project_id": str(project_id),
                "project_name": p_name,
                "context_data": context,
                "current_risks": [],
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
            return rep_agent.execute({
                "project_id": project_id,
                "kpis": inputs.get("kpi", {}).get("kpis", []),
                "financials": inputs.get("financial", {}),
                "risks": inputs.get("risk", {}).get("risks", []),
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
        
        # Resolve valid project and program for foreign key integrity
        from models.project import Project
        from models.program import Program

        proj = db.db_session.query(Project).filter_by(id=project_id).first()
        if not proj:
            proj = db.db_session.query(Project).first()
            if not proj:
                prog = db.db_session.query(Program).first()
                if not prog:
                    prog = Program(name="Alpha Migration", description="Core migration program")
                    db.db_session.add(prog)
                    db.db_session.commit()
                proj = Project(program_id=prog.id, jira_key=f"PRJ-{project_id}", name=f"Project {project_id}")
                db.db_session.add(proj)
                db.db_session.commit()
            project_id = proj.id

        prog_id = proj.program_id if proj else None

        for idx, r in enumerate(detected_risks):
            r_id = r.get("id") if isinstance(r, dict) and r.get("id") else f"R-{random.randint(100, 999)}"
            r_title = r.get("title") if isinstance(r, dict) and r.get("title") else str(r)
            r_desc = r.get("description") if isinstance(r, dict) and r.get("description") else r_title
            r_sev = r.get("severity", "Medium") if isinstance(r, dict) else "Medium"
            r_status = r.get("status", "Open") if isinstance(r, dict) else "Open"
            r_mitigation = r.get("mitigation_plan", "") if isinstance(r, dict) else "Under PM review"
            
            existing = db.db_session.query(RiskRegister).filter_by(project_id=project_id, risk_id=r_id).first()
            if existing:
                existing.title = r_title
                existing.description = r_desc
                existing.severity = r_sev
                existing.status = r_status
                existing.mitigation_plan = r_mitigation
            else:
                new_risk = RiskRegister(
                    project_id=project_id,
                    risk_id=r_id,
                    title=r_title,
                    description=r_desc,
                    severity=r_sev,
                    status=r_status,
                    mitigation_plan=r_mitigation
                )
                db.db_session.add(new_risk)
                
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

        snapshot = DashboardSnapshot(
            program_id=prog_id,
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

