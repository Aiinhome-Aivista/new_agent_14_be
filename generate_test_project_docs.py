import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

SAMPLE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'sample_documents'))

def generate_sow():
    txt_content = """================================================================================
STATEMENT OF WORK (SOW) - NEXTGEN AI BANKING PLATFORM & CLOUD MODERNIZATION
Vendor: CyberCore Solutions & Cloud Architects Inc.
Client: Enterprise Digital Banking Program
Project Identifier: PRJ-103
Effective Date: August 15, 2026
Term: 9 Months (August 2026 - May 2027)
================================================================================

1. EXECUTIVE SCOPE & OBJECTIVES
-------------------------------
CyberCore Solutions Inc. ("Vendor") shall architect, construct, and deploy a high-concurrency,
fault-tolerant cloud banking platform supporting ISO 20022 messaging standards, real-time
AI-driven fraud evaluation, and event-driven microservices architecture hosted on AWS.

2. FINANCIAL COMMITMENTS & TRANCHE DISBURSEMENTS
------------------------------------------------
- Total Contract Ceiling Price: $2,500,000 USD
- Invoiced to Date: $1,650,000 USD
- Remaining Contingency Budget: $850,000 USD
- Payment Terms: Net 30 days upon PMO milestone sign-off and SLA compliance audit.

Milestone Schedule:
1. Deliverable M-1: Multi-Region High-Availability AWS Landing Zone ($600,000) - Completed
2. Deliverable M-2: ISO 20022 Payment Gateway & Clearinghouse Interconnect ($800,000) - In Progress
3. Deliverable M-3: Real-Time AI Fraud Prevention Microservices Pipeline ($650,000) - In Progress
4. Deliverable M-4: PCI-DSS 4.0 Compliance Audit, Penetration Hardening & Production Cutover ($450,000) - Pending

3. SERVICE LEVEL AGREEMENTS (SLAs) & CONTRACTUAL THRESHOLDS
----------------------------------------------------------
- Core API P99 Latency: Maximum 120 milliseconds under 25,000 transactions per second (TPS).
- System Availability: 99.99% uptime across primary and disaster recovery zones.
- Mean Time to Remediate (MTTR) Severity-1 Incidents: < 20 minutes.
- Contractual Penalty: 2.0% tranche deduction per calendar week of unexcused milestone delay.

4. IDENTIFIED DELIVERY RISKS & BOTTLENECKS
------------------------------------------
[RISK-FIN-01] Payment Gateway Sandbox Latency Under Peak Stress:
- Severity: Critical
- Category: Performance & Infrastructure
- Description: Intermittent 480ms latency spikes observed in clearinghouse transaction routing when stress-tested beyond 18,000 TPS.
- Mitigation Plan: Vendor to provision dedicated hardware security modules (HSM) and deploy Redis enterprise caching tier within 72 hours.

[RISK-FIN-02] Third-Party Identity & Access Management (IAM) Token Vulnerability:
- Severity: High
- Category: Security & Compliance
- Description: OAuth2 token refresh race condition identified in external KYC partner verification service.
- Mitigation Plan: Implement mutual TLS (mTLS) authentication and short-lived ephemeral token rotation.

[RISK-FIN-03] Accelerated Cloud GPU Ingestion Costs for Fraud Inference:
- Severity: Medium
- Category: Financial & Budget
- Description: Dedicated GPU cluster training costs trending 18% higher than projected in Sprint 3.
- Mitigation Plan: Shift off-peak batch training to Spot instances and quantize model weights with TensorRT.

5. SIGN-OFF & ESCALATION PATHWAY
---------------------------------
- Level 1: Vendor Technical Lead -> Client Engineering Manager (SLA: 2 Hours)
- Level 2: Vendor Delivery Director -> Client PMO Lead (SLA: 8 Hours)
- Level 3: Joint Steering Committee / Executive PMO (Immediate Action for Showstoppers)
================================================================================
"""
    txt_path = os.path.join(SAMPLE_DIR, 'NextGen_Banking_Vendor_SOW.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt_content)

    # Word Doc
    doc = docx.Document()
    title = doc.add_heading('STATEMENT OF WORK (SOW)', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph('Project: NextGen AI Banking Platform (PRJ-103)\nVendor: CyberCore Solutions & Cloud Architects Inc.\nTotal Contract Value: $2,500,000 USD\nGovernance Standard: Enterprise Capital Gatekeeper Framework')
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading('1. Executive Scope & Objectives', level=1)
    doc.add_paragraph(
        'This Statement of Work (SOW) defines the contractual scope, delivery milestones, SLA benchmarks, '
        'and tranche disbursement schedules for the NextGen AI Banking Platform (PRJ-103). All payouts '
        'are governed by automated telemetry compliance and PMO oversight.'
    )

    doc.add_heading('2. Financial Commitments & Tranche Disbursements', level=1)
    doc.add_paragraph('Total Approved Budget: $2,500,000 USD | Invoiced to Date: $1,650,000 USD | Remaining: $850,000 USD')

    table = doc.add_table(rows=1, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    hdr[0].text = 'Milestone'
    hdr[1].text = 'Deliverable Description'
    hdr[2].text = 'Tranche ($ USD)'
    hdr[3].text = 'SLA Compliance'
    hdr[4].text = 'Status'

    milestones = [
        ('M-1', 'Multi-Region High-Availability AWS Landing Zone', '$600,000', '99.5% (Compliant)', 'Completed'),
        ('M-2', 'ISO 20022 Payment Gateway & Clearinghouse Hub', '$800,000', '82.0% (Warning)', 'In Progress'),
        ('M-3', 'Real-Time AI Fraud Prevention Microservices', '$650,000', '91.0% (Compliant)', 'In Progress'),
        ('M-4', 'PCI-DSS 4.0 Audit, Pen Testing & Cutover', '$450,000', 'Pending', 'Scheduled')
    ]

    for m_id, name, tranche, sla, status in milestones:
        row = table.add_row().cells
        row[0].text = m_id
        row[1].text = name
        row[2].text = tranche
        row[3].text = sla
        row[4].text = status

    doc.add_heading('3. Key Delivery Risks & Mitigation Roadmap', level=1)
    doc.add_paragraph(
        '[RISK-FIN-01] Critical: Payment Gateway Sandbox Latency Under Peak Stress (480ms vs 120ms target). '
        'Mitigation: Provision hardware security modules (HSM) and deploy Redis caching tier within 72 hours.'
    )
    doc.add_paragraph(
        '[RISK-FIN-02] High: Third-Party Identity & Access Management (IAM) OAuth2 token race condition. '
        'Mitigation: Implement mutual TLS (mTLS) and automated ephemeral token revocation.'
    )
    doc.add_paragraph(
        '[RISK-FIN-03] Medium: Accelerated Cloud GPU Ingestion Costs for Fraud Inference (+18% burn rate). '
        'Mitigation: Transition batch pipelines to AWS Spot instances and enable TensorRT quantization.'
    )

    docx_path = os.path.join(SAMPLE_DIR, 'NextGen_Banking_Vendor_SOW.docx')
    doc.save(docx_path)
    print(f"Generated: {txt_path} and {docx_path}")

def generate_mom():
    txt_content = """================================================================================
MINUTES OF MEETING (MOM) - STEERING COMMITTEE GOVERNANCE REVIEW
Program: Digital Core Banking Transformation
Project Identifier: PRJ-103 - NextGen AI Banking Platform
Date: September 10, 2026
Session: Bi-Weekly Steering Committee & Capital Tranche Gate
Attendees: Chief Information Officer (Sponsor), Lead Enterprise Architect, PMO Lead, Vendor Delivery Principal
================================================================================

1. EXECUTIVE STATUS OVERVIEW
----------------------------
Project Status: Active (Elevated Supervision Required)
Sprint 5 telemetry shows substantial progress on core cloud infrastructure (94% complete).
However, real-time clearinghouse testing under simulated peak load revealed latency degradation
in the ISO 20022 microservice adapter, triggering a temporary hold on Tranche 2 disbursement.

2. FINANCIAL & CAPITAL TELEMETRY
--------------------------------
- Approved Project Budget: $2,500,000 USD
- Actual Capital Incurred to Date: $1,720,000 USD
- Current Variance: $780,000 USD (Positive runway, burn acceleration at +9.2%)
- Projected Completion Cost: $2,480,000 USD (Within overall portfolio envelope)

3. MILESTONE STATUS & TRANCHE GATING
-------------------------------------
- Milestone 1 (Cloud Landing Zone): 100% Verified, funds disbursed ($600,000).
- Milestone 2 (Payment Gateway Hub): 74% Complete. Delayed by 1.5 weeks due to latency issues.
- Milestone 3 (AI Fraud Microservices): 65% Complete. Model precision exceeds 99.4%.
- Milestone 4 (PCI-DSS Certification): Scheduled to commence in November 2026.

4. CRITICAL ESCALATIONS & REGISTERED RISKS
------------------------------------------
[RISK-FIN-01] SHOWSTOPPER: Core Payment Clearinghouse Latency Spike
- Severity: Critical
- Status: Open
- Description: P99 latency reached 480ms against the contractually enforced 120ms SLA threshold.
- Action: Vendor engineering task force assigned 24/7 rotation; patch deployment scheduled for Friday midnight.

[RISK-FIN-02] HIGH SEVERITY: InfoSec Compliance Sign-off Pending for External Gateway
- Severity: High
- Status: Open
- Description: Automated vulnerability scan flagged outdated cipher suites on legacy interconnect proxy.
- Action: Security Architect mandated TLS 1.3 enforcement across all staging VPC endpoints.

[RISK-FIN-04] MEDIUM SEVERITY: Testing Dataset Synthetic Data Generator Drift
- Severity: Medium
- Status: Mitigated
- Description: Synthetic payment data lacked edge-case fraud patterns for Southeast Asian currencies.
- Action: RAG knowledge vectors updated with 5,000 additional historical transaction scenarios.

5. DECISIONS & ACTION ITEMS
----------------------------
1. PMO Lead to log formal Risk-FIN-01 escalation into VPM Approval Queue for steering committee review.
2. Tranche 2 disbursement ($800,000 USD) withheld until latency benchmark (< 120ms) is verified by automated testing.
3. Next Governance Gate scheduled for September 24, 2026.
================================================================================
"""
    txt_path = os.path.join(SAMPLE_DIR, 'NextGen_Banking_Steering_MOM.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt_content)

    doc = docx.Document()
    title = doc.add_heading('MINUTES OF MEETING (MOM)', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph('Project: NextGen AI Banking Platform (PRJ-103)\nProgram: Digital Core Banking Transformation\nGovernance Gate: Bi-Weekly Steering Committee Review\nDate: September 10, 2026')
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading('1. Executive Status Overview', level=1)
    doc.add_paragraph(
        'The steering committee conducted an in-depth audit of Sprint 5 deliverables. While overall '
        'infrastructure migration is 94% complete, critical payment gateway latency triggers elevated '
        'supervision and tranche retention.'
    )

    doc.add_heading('2. Financial & Budget Telemetry', level=1)
    doc.add_paragraph('Planned Budget: $2,500,000 USD | Actual Spend: $1,720,000 USD | Variance: $780,000 USD')

    doc.add_heading('3. Key Decisions & Escalation Actions', level=1)
    doc.add_paragraph(
        '1. Critical Escalation: Payment gateway latency spike (480ms) logged into VPM Governance Approval Queue.\n'
        '2. Capital Retention: Tranche 2 payout ($800,000 USD) withheld pending SLA latency verification.\n'
        '3. Security Gate: TLS 1.3 cipher suite mandated on all external microservices.\n'
        '4. Next Steering Committee scheduled for September 24, 2026.'
    )

    docx_path = os.path.join(SAMPLE_DIR, 'NextGen_Banking_Steering_MOM.docx')
    doc.save(docx_path)
    print(f"Generated: {txt_path} and {docx_path}")

if __name__ == '__main__':
    generate_sow()
    generate_mom()
