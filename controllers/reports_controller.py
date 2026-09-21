import os
import time
import logging
from flask import Blueprint, jsonify, send_file, request
from datetime import datetime, timezone

import db
from models.project import Project
from models.generated_report import GeneratedReport

reports_bp = Blueprint('reports', __name__)
logger = logging.getLogger(__name__)

@reports_bp.route('/list', methods=['GET'])
def list_reports():
    """
    Returns only reports that are explicitly tracked in the database.
    If the database is truncated or empty, returns an empty list [].
    """
    try:
        project_id_param = request.args.get('project_id')
        query = db.db_session.query(GeneratedReport)

        if project_id_param and str(project_id_param).strip().lower() not in ('all', '', 'none', 'null'):
            active_project = None
            if str(project_id_param).isdigit():
                active_project = db.db_session.query(Project).filter_by(id=int(project_id_param)).first()
            if not active_project:
                active_project = db.db_session.query(Project).filter_by(jira_key=str(project_id_param).strip()).first()

            if active_project:
                query = query.filter(GeneratedReport.project_id == active_project.id)
            else:
                # If a specific project was requested but doesn't exist, return empty
                return jsonify([])

        reports = query.order_by(GeneratedReport.created_at.desc(), GeneratedReport.id.desc()).all()
        return jsonify([r.to_dict() for r in reports])
    except Exception as e:
        logger.error(f"Error listing reports from database: {e}", exc_info=True)
        return jsonify([]), 500


@reports_bp.route('/download/<path:identifier>', methods=['GET'])
def download_report(identifier):
    """
    Downloads a report file ONLY if it is registered in the database.
    Accepts report database ID or filename.
    If physical file is missing from server storage, automatically regenerates it on the fly.
    """
    try:
        report = None
        if str(identifier).isdigit():
            report = db.db_session.query(GeneratedReport).filter_by(id=int(identifier)).first()
        if not report:
            report = db.db_session.query(GeneratedReport).filter(
                (GeneratedReport.filename == identifier) | (GeneratedReport.name == identifier)
            ).first()

        if not report:
            return jsonify({"error": "Report not found in database record."}), 404

        file_path = report.file_path
        
        # Multi-location candidate check for physical file
        candidate_paths = []
        if file_path:
            candidate_paths.append(file_path)
        if report.filename:
            candidate_paths.extend([
                os.path.join(os.getcwd(), 'reports', report.filename),
                os.path.join(os.getcwd(), 'new_agent_14_be', 'reports', report.filename),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'reports', report.filename),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'reports', report.filename)
            ])

        # Always ensure report file is freshly generated with latest boardroom layout
        logger.info(f"Ensuring fresh report generation for '{report.filename}'...")
        try:
            import json
            import shutil
            from agents.reporting_agent.agent import ReportingAgent
            from models.risk_register import RiskRegister
            from models.budget import Budget
            from models.dashboard_snapshot import DashboardSnapshot

            project_id = report.project_id or 1
            proj = db.db_session.query(Project).filter_by(id=project_id).first()
            project_name = proj.name if proj else f"Project #{project_id}"

            snapshot = db.db_session.query(DashboardSnapshot).order_by(DashboardSnapshot.created_at.desc()).first()
            snap_data = snapshot.data if snapshot else {}
            if isinstance(snap_data, str):
                try:
                    snap_data = json.loads(snap_data)
                except Exception:
                    snap_data = {}

            risks = db.db_session.query(RiskRegister).filter_by(project_id=project_id).all()
            budget_row = db.db_session.query(Budget).filter_by(project_id=project_id).order_by(Budget.created_at.desc()).first()
            budget_planned = float(budget_row.planned_spend) if budget_row else 0.0
            budget_actual = float(budget_row.actual_spend) if budget_row else 0.0

            from controllers.dashboard_controller import calculate_dynamic_health_score, get_project_db_telemetry
            health_score = calculate_dynamic_health_score(proj, budget_planned, budget_actual, risks, db.db_session)
            telemetry = get_project_db_telemetry(project_id) or {}
            milestones = telemetry.get('milestones', []) if isinstance(telemetry, dict) else []

            rep_agent = ReportingAgent()
            res = rep_agent.execute({
                "project_id": project_id,
                "project_name": project_name,
                "kpis": snap_data.get("kpis", []),
                "financials": {
                    "budget_planned": budget_planned,
                    "budget_actual": budget_actual
                },
                "milestones": milestones,
                "risks": [r.to_dict() for r in risks],
                "predictive": {
                    "confidence_score": health_score
                }
            })

            is_pdf = report.filename.lower().endswith('.pdf')
            gen_path = res.get("pdf_path") if is_pdf else res.get("docx_path")
            if gen_path and os.path.exists(gen_path):
                target_dest = report.file_path or os.path.join(os.getcwd(), 'reports', report.filename)
                if gen_path != target_dest:
                    try:
                        shutil.copy2(gen_path, target_dest)
                        found_path = target_dest
                    except Exception:
                        found_path = gen_path
                else:
                    found_path = gen_path
                report.file_path = found_path
                try:
                    db.db_session.commit()
                except Exception:
                    db.db_session.rollback()
        except Exception as regen_err:
            logger.error(f"Failed to regenerate report: {regen_err}", exc_info=True)
            if candidate_paths:
                for cp in candidate_paths:
                    if cp and os.path.exists(cp):
                        found_path = cp
                        break

        if not found_path or not os.path.exists(found_path):
            return jsonify({"error": "Report file is missing from server storage."}), 404

        mimetype = 'application/pdf' if report.filename.lower().endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        response = send_file(
            found_path, 
            as_attachment=True, 
            download_name=report.filename, 
            mimetype=mimetype,
            etag=False,
            conditional=False
        )
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception as e:
        logger.error(f"Error downloading report '{identifier}': {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@reports_bp.route('/<int:report_id>', methods=['DELETE'])
def delete_report(report_id):
    """
    Deletes a report from the database and removes its physical file from disk.
    """
    try:
        report = db.db_session.query(GeneratedReport).filter_by(id=report_id).first()
        if not report:
            return jsonify({"success": False, "error": "Report not found."}), 404

        # Remove file from disk if present
        if report.file_path and os.path.exists(report.file_path):
            try:
                os.remove(report.file_path)
            except Exception as fe:
                logger.warning(f"Could not remove physical report file: {fe}")

        db.db_session.delete(report)
        db.db_session.commit()
        return jsonify({"success": True, "message": f"Report #{report_id} deleted successfully."})
    except Exception as e:
        db.db_session.rollback()
        logger.error(f"Error deleting report #{report_id}: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@reports_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    Generates a new executive report, saves physical PDF/DOCX files,
    and inserts tracking records into the database.
    """
    import json
    from models.dashboard_snapshot import DashboardSnapshot
    from models.risk_register import RiskRegister
    from agents.reporting_agent.agent import ReportingAgent
    from models.budget import Budget

    try:
        data = request.json or {}
        raw_pid = data.get('project_id', 1)

        proj = None
        try:
            proj = db.db_session.query(Project).filter_by(id=int(raw_pid)).first()
        except (ValueError, TypeError):
            pass
        if not proj:
            proj = db.db_session.query(Project).filter_by(jira_key=str(raw_pid)).first()
        if not proj:
            all_projs = db.db_session.query(Project).order_by(Project.id).all()
            try:
                idx = int(raw_pid) - 1
                if 0 <= idx < len(all_projs):
                    proj = all_projs[idx]
            except Exception:
                pass
        if not proj:
            proj = db.db_session.query(Project).first()

        if not proj:
            return jsonify({
                "success": False,
                "error": "No projects exist in database. Please create a project before generating reports."
            }), 400

        project_id = proj.id
        project_name = proj.name

        # Fetch latest snapshot data
        snapshot = db.db_session.query(DashboardSnapshot).order_by(DashboardSnapshot.created_at.desc()).first()

        snap_data = snapshot.data if snapshot else {}
        if isinstance(snap_data, str):
            try:
                snap_data = json.loads(snap_data)
            except Exception:
                snap_data = {}

        risks = db.db_session.query(RiskRegister).filter_by(project_id=project_id).all()

        budget_row = db.db_session.query(Budget).filter_by(project_id=project_id).order_by(Budget.created_at.desc()).first()
        if budget_row:
            budget_planned = float(budget_row.planned_spend)
            budget_actual = float(budget_row.actual_spend)
        else:
            budget_planned = 0.0
            budget_actual = 0.0

        from controllers.dashboard_controller import calculate_dynamic_health_score, get_project_db_telemetry
        p_obj = db.db_session.query(Project).filter_by(id=project_id).first() if db.db_session else None
        health_score = calculate_dynamic_health_score(p_obj, budget_planned, budget_actual, risks, db.db_session)

        telemetry = get_project_db_telemetry(project_id) or {}
        milestones = telemetry.get('milestones', []) if isinstance(telemetry, dict) else []

        rep_agent = ReportingAgent()
        report_result = rep_agent.execute({
            "project_id": project_id,
            "project_name": project_name,
            "kpis": snap_data.get("kpis", []),
            "financials": {
                "budget_planned": budget_planned,
                "budget_actual": budget_actual
            },
            "milestones": milestones,
            "risks": [r.to_dict() for r in risks],
            "predictive": {
                "confidence_score": health_score
            }
        })

        created_records = []
        now = datetime.now(timezone.utc)

        def format_size(path):
            try:
                s = os.stat(path).st_size
                kb = s / 1024
                return f"{kb:.1f} KB" if kb < 1024 else f"{(kb/1024):.2f} MB"
            except Exception:
                return "15.0 KB"

        # 1. Register PDF report in database
        pdf_path = report_result.get("pdf_path")
        pdf_filename = report_result.get("pdf_filename") or (os.path.basename(pdf_path) if pdf_path else None)
        if pdf_path and os.path.exists(pdf_path):
            pdf_rep = GeneratedReport(
                project_id=project_id,
                name=pdf_filename,
                filename=pdf_filename,
                file_type='pdf',
                report_type='Executive PDF Briefing',
                file_size=format_size(pdf_path),
                file_path=pdf_path,
                summary=report_result.get("narrative_summary", ""),
                generated_by="Autonomous Reporting Agent",
                created_at=now
            )
            db.db_session.add(pdf_rep)
            created_records.append(pdf_rep)

        # 2. Register Word (.docx) report in database
        docx_path = report_result.get("docx_path")
        docx_filename = report_result.get("docx_filename") or (os.path.basename(docx_path) if docx_path else None)
        if docx_path and os.path.exists(docx_path):
            docx_rep = GeneratedReport(
                project_id=project_id,
                name=docx_filename,
                filename=docx_filename,
                file_type='docx',
                report_type='Enterprise Word (.docx)',
                file_size=format_size(docx_path),
                file_path=docx_path,
                summary=report_result.get("narrative_summary", ""),
                generated_by="Autonomous Reporting Agent",
                created_at=now
            )
            db.db_session.add(docx_rep)
            created_records.append(docx_rep)

        db.db_session.commit()

        primary_filename = pdf_filename or docx_filename or "Executive_Report.pdf"
        return jsonify({
            "success": True,
            "filename": primary_filename,
            "download_url": f"/api/reports/download/{primary_filename}",
            "narrative_summary": report_result.get("narrative_summary", ""),
            "records_created": len(created_records),
            "reports": [r.to_dict() for r in created_records]
        })
    except Exception as e:
        db.db_session.rollback()
        logger.error(f"Failed to generate report: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
