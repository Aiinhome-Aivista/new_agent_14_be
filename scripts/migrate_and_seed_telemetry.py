import sys
import os
import logging

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import db
from models.project import Project
from models.project_member import ProjectMember
from models.project_milestone import ProjectMilestone
from models.project_telemetry import ProjectTelemetry
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from flask import Flask

def migrate_and_seed():
    app = Flask(__name__)
    app.config.from_object(Config)
    logger.info("Initializing database connection...")
    db.init_db(app)

    logger.info("Creating tables: project_members, project_milestones, project_telemetries if they do not exist...")
    db.Base.metadata.create_all(db.engine)
    logger.info("Tables checked / created successfully.")

    # Ensure meta_data JSON columns exist on MySQL tables
    with db.engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE project_members ADD COLUMN meta_data JSON NULL;"))
            conn.commit()
            logger.info("Added meta_data column to project_members.")
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE project_milestones ADD COLUMN meta_data JSON NULL;"))
            conn.commit()
            logger.info("Added meta_data column to project_milestones.")
        except Exception:
            pass

    # Find PRJ-014 or create it if missing
    session = db.db_session
    projs = session.query(Project).all()
    logger.info(f"Existing projects in DB: {[(p.id, p.jira_key, p.name) for p in projs]}")

    target_projects = []
    prj_014 = session.query(Project).filter_by(jira_key='PRJ-014').first()
    if prj_014:
        target_projects.append(prj_014)
    else:
        first_p = session.query(Project).first()
        if first_p:
            target_projects.append(first_p)

    # If any other project exists, include them as well
    for p in projs:
        if p not in target_projects:
            target_projects.append(p)

    team_seed = [
        {"name": "Ananya Sharma", "role": "Project Manager", "contact": "ananya.sharma@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Rohan Mehta", "role": "Backend Lead (Python/Flask)", "contact": "rohan.mehta@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Priya Nair", "role": "AI / Agent Engineer", "contact": "priya.nair@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Arjun Verma", "role": "RAG / Knowledge Engineer", "contact": "arjun.verma@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Sneha Iyer", "role": "Guardrails / Safety Engineer", "contact": "sneha.iyer@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Vikram Singh", "role": "Frontend Lead (React)", "contact": "vikram.singh@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Divya Reddy", "role": "QA / Test Engineer", "contact": "divya.reddy@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
        {"name": "Karan Patel", "role": "DevOps / Infra", "contact": "karan.patel@vpmproject.com", "member_type": "Internal FTE", "allocation_pct": 100.0, "is_active_today": True},
    ]

    milestones_seed = [
        {"milestone_code": "M1", "name": "M1: Core platform setup: auth, DB schema, project/program CRUD", "description": "Core platform setup: auth, DB schema, project/program CRUD", "target_date": "Completed", "status": "Done", "completion_pct": 100, "days_left": 0, "tranche_amount": 350000.0, "sla_score": 98.0, "sla_status": "Compliant"},
        {"milestone_code": "M2", "name": "M2: Document ingestion + RAG pipeline (ChromaDB) operational", "description": "Document ingestion + RAG pipeline (ChromaDB) operational", "target_date": "Completed", "status": "Done", "completion_pct": 100, "days_left": 0, "tranche_amount": 450000.0, "sla_score": 95.0, "sla_status": "Compliant"},
        {"milestone_code": "M3", "name": "M3: Multi-agent orchestrator + guardrails integration", "description": "Multi-agent orchestrator + guardrails integration", "target_date": "In Progress", "status": "In Progress", "completion_pct": 50, "days_left": 30, "tranche_amount": 300000.0, "sla_score": 90.0, "sla_status": "Compliant"},
        {"milestone_code": "M4", "name": "M4: Dashboard, KPI & risk register UI complete", "description": "Dashboard, KPI & risk register UI complete", "target_date": "In Progress", "status": "In Progress", "completion_pct": 50, "days_left": 45, "tranche_amount": 400000.0, "sla_score": 92.0, "sla_status": "Compliant"},
        {"milestone_code": "M5", "name": "M5: Reporting module (SOW/MOM/Status auto-generation) hardening", "description": "Reporting module (SOW/MOM/Status auto-generation) hardening", "target_date": "Upcoming", "status": "At Risk", "completion_pct": 20, "days_left": 60, "tranche_amount": 250000.0, "sla_score": 74.0, "sla_status": "At Risk"},
        {"milestone_code": "M6", "name": "M6: Integration testing, security review & production readiness", "description": "Integration testing, security review & production readiness", "target_date": "Upcoming", "status": "Scheduled", "completion_pct": 0, "days_left": 90, "tranche_amount": 250000.0, "sla_score": None, "sla_status": "Scheduled"},
    ]

    for p in target_projects:
        # Check members
        existing_members = session.query(ProjectMember).filter_by(project_id=p.id).all()
        if not existing_members:
            logger.info(f"Seeding {len(team_seed)} team members into MySQL for project {p.jira_key} (ID: {p.id})...")
            for tm in team_seed:
                mem = ProjectMember(
                    project_id=p.id,
                    name=tm["name"],
                    role=tm["role"],
                    contact=tm.get("contact"),
                    member_type=tm.get("member_type", "Internal FTE"),
                    allocation_pct=tm.get("allocation_pct", 100.0),
                    is_active_today=tm.get("is_active_today", True)
                )
                session.add(mem)
        else:
            logger.info(f"Project {p.jira_key} (ID: {p.id}) already has {len(existing_members)} members in MySQL.")

        # Check milestones
        existing_ms = session.query(ProjectMilestone).filter_by(project_id=p.id).all()
        if not existing_ms:
            logger.info(f"Seeding {len(milestones_seed)} milestones into MySQL for project {p.jira_key} (ID: {p.id})...")
            for ms in milestones_seed:
                m_obj = ProjectMilestone(
                    project_id=p.id,
                    milestone_code=ms["milestone_code"],
                    name=ms["name"],
                    description=ms.get("description"),
                    target_date=ms.get("target_date", "TBD"),
                    status=ms.get("status", "Scheduled"),
                    completion_pct=ms.get("completion_pct", 0),
                    days_left=ms.get("days_left", 0),
                    tranche_amount=ms.get("tranche_amount", 0.0),
                    sla_score=ms.get("sla_score"),
                    sla_status=ms.get("sla_status", "Scheduled")
                )
                session.add(m_obj)
        # Seed or sync ProjectTelemetry (Full Dynamic JSON Store in MySQL)
        existing_telemetry = session.query(ProjectTelemetry).filter_by(project_id=p.id).first()
        full_telemetry_payload = {
            "project_id": p.id,
            "jira_key": p.jira_key,
            "project_name": p.name,
            "team": team_seed,
            "milestones": milestones_seed,
            "governance": {
                "vendor_sla_adherence": 100.0,
                "compliance_audit_score": 100,
                "compliance_gate": "Gate 3 Approved",
                "trajectory": "Governed by Project Charter & SOW"
            },
            "custom_attributes": {
                "source": "Project Charter & SOW",
                "tier": "Enterprise Mission-Critical",
                "audited_by": "PMO Governance Lead",
                "compliance_framework": "PwC / Big-4 Enterprise PMO Standard"
            }
        }
        if not existing_telemetry:
            logger.info(f"Seeding dynamic ProjectTelemetry JSON into MySQL for project {p.jira_key} (ID: {p.id})...")
            new_tel = ProjectTelemetry(
                project_id=p.id,
                telemetry_data=full_telemetry_payload
            )
            session.add(new_tel)
        else:
            logger.info(f"Updating dynamic ProjectTelemetry JSON for project {p.jira_key} (ID: {p.id})...")
            existing_telemetry.telemetry_data = full_telemetry_payload

    session.commit()
    logger.info("Database migration & seed committed successfully!")

if __name__ == '__main__':
    migrate_and_seed()
