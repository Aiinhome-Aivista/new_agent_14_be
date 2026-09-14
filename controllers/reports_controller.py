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
        if not file_path or not os.path.exists(file_path):
            fallback = os.path.join(os.getcwd(), 'reports', report.filename)
            if os.path.exists(fallback):
                file_path = fallback
            else:
                return jsonify({"error": "Report file is missing from server storage."}), 404

        mimetype = 'application/pdf' if report.filename.lower().endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        return send_file(file_path, as_attachment=True, download_name=report.filename, mimetype=mimetype)
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
            budget_planned = 1500000.0
            budget_actual = 0.0

        crit_count = sum(1 for r in risks if str(r.severity).capitalize() == 'Critical' and str(r.status).capitalize() == 'Open')
        high_count = sum(1 for r in risks if str(r.severity).capitalize() == 'High' and str(r.status).capitalize() == 'Open')
        health_score = max(40, 95 - (crit_count * 12 + high_count * 6))

        rep_agent = ReportingAgent()
        report_result = rep_agent.execute({
            "project_id": project_id,
            "project_name": project_name,
            "kpis": snap_data.get("kpis", []),
            "financials": {
                "budget_planned": budget_planned,
                "budget_actual": budget_actual
            },
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
