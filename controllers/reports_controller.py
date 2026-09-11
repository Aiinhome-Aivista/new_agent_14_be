import os
import logging
from flask import Blueprint, jsonify, send_file, request

reports_bp = Blueprint('reports', __name__)
logger = logging.getLogger(__name__)

@reports_bp.route('/list', methods=['GET'])
def list_reports():
    reports_dir = os.path.join(os.getcwd(), 'reports')
    if not os.path.exists(reports_dir):
        return jsonify([])
        
    project_id_param = request.args.get('project_id')
    active_project = None
    if project_id_param and str(project_id_param).strip().lower() not in ('all', '', 'none', 'null'):
        import db
        from models.project import Project
        if str(project_id_param).isdigit():
            active_project = db.db_session.query(Project).filter_by(id=int(project_id_param)).first()
        if not active_project:
            active_project = db.db_session.query(Project).filter_by(jira_key=str(project_id_param).strip()).first()

    reports = []
    for file in sorted(os.listdir(reports_dir), reverse=True):
        if file.endswith('.docx') or file.endswith('.pdf'):
            import time
            fpath = os.path.join(reports_dir, file)
            stat = os.stat(fpath)
            date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
            size_kb = stat.st_size / 1024
            size_fmt = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{(size_kb / 1024):.2f} MB"
            
            match = True
            if active_project:
                pid = active_project.id
                key = active_project.jira_key.lower()
                file_lower = file.lower()
                target_keys = [
                    f"prj_{pid}_",
                    f"report_{pid}_",
                ]
                if key != "prj":
                    target_keys.extend([f"_{key}_", f"prj_{key}_"])
                match = any(k in file_lower for k in target_keys)

            if match:
                reports.append({
                    "id": file,
                    "name": file,
                    "date": date_str,
                    "size": size_fmt,
                    "type": "Executive Briefing" if ("Executive" in file or "report_" in file) else "Status Report",
                    "project_id": active_project.id if active_project else None,
                    "project_name": active_project.name if active_project else None,
                    "url": f"/api/reports/download/{file}"
                })
    return jsonify(reports)

@reports_bp.route('/download/<filename>', methods=['GET'])
def download_report(filename):
    file_path = os.path.join(os.getcwd(), 'reports', filename)
    if os.path.exists(file_path):
        mimetype = 'application/pdf' if filename.endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        return send_file(file_path, as_attachment=True, download_name=filename, mimetype=mimetype)
    return jsonify({"error": "File not found"}), 404

@reports_bp.route('/generate', methods=['POST'])
def generate_report():
    import json
    import db
    from models.dashboard_snapshot import DashboardSnapshot
    from models.risk_register import RiskRegister
    from agents.reporting_agent.agent import ReportingAgent
    from models.project import Project
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
            
        project_id = proj.id if proj else 1
        project_name = proj.name if proj else f"Project {project_id}"
        
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
            budget_actual = 1200000.0

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
        
        filename = os.path.basename(report_result.get("report_file_path", f"Executive_Report_PRJ_{project_id}.pdf"))
        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/reports/download/{filename}",
            "narrative_summary": report_result.get("narrative_summary", "")
        })
    except Exception as e:
        logger.error(f"Failed to generate report: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

