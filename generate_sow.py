import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import os

def create_sow_doc():
    doc = docx.Document()

    # Title
    title = doc.add_heading('STATEMENT OF WORK (SOW)', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph('Program: Alpha Migration Program (PRJ-101)\nVendor: CloudScale Systems & Delivery Partners\nContract Value: $1,500,000 USD\nGovernance Standard: Autonomous Capital Gatekeeper Framework')
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading('1. Executive Overview & Scope', level=1)
    doc.add_paragraph(
        'This Statement of Work (SOW) defines the contractual scope, technical milestones, deliverable verification criteria, '
        'and tranche disbursement schedules for the Alpha Migration Program. Capital releases are governed by autonomous '
        'telemetry compliance against agreed technical service level agreements (SLAs).'
    )

    doc.add_heading('2. Contractual Delivery Milestones & Capital Tranche Disbursements', level=1)
    doc.add_paragraph(
        'Disbursement of funds is strictly partitioned into milestone tranches. Payouts require 100% verification of deliverables '
        'and SLA compliance above the 90% threshold.'
    )

    table = doc.add_table(rows=1, cols=6)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Milestone ID'
    hdr_cells[1].text = 'Deliverable & Phase'
    hdr_cells[2].text = 'Timeline'
    hdr_cells[3].text = 'Tranche ($ USD)'
    hdr_cells[4].text = 'SLA Benchmark'
    hdr_cells[5].text = 'Disbursement Status'

    milestones_data = [
        ('M-01', 'Architecture Sign-off & Technical Blueprint', 'Jan 15', '$350,000', '98% (Compliant)', 'Released & Paid'),
        ('M-02', 'Core MVP Pipeline & API Gateway Delivery', 'Feb 28', '$450,000', '98% (Compliant)', 'Released & Paid'),
        ('M-03', 'Beta Migration Rollout & ERP Integration', 'Mar 30', '$300,000', '74% (Breached)', 'On Hold (SLA Withheld)'),
        ('M-04', 'Full Production Cutover & Final Sign-off', 'Apr 30', '$400,000', 'Scheduled', 'Locked Phase')
    ]

    for m_id, name, time, tranche, sla, status in milestones_data:
        row_cells = table.add_row().cells
        row_cells[0].text = m_id
        row_cells[1].text = name
        row_cells[2].text = time
        row_cells[3].text = tranche
        row_cells[4].text = sla
        row_cells[5].text = status

    doc.add_heading('3. Milestone 3 Detailed Deliverables & Blockers', level=1)
    doc.add_paragraph(
        'Milestone M-03 encompasses the migration of transactional ERP feeds to cloud endpoints. Current telemetry indicates '
        'Risk R-802 (SAP S/4HANA latency variance exceeding 280ms threshold) has breached contractual technical SLA standards (74% vs. 90% requirement). '
        'In accordance with Investor Safeguard Rule #4, Tranche 3 payout ($300,000 USD) is placed ON HOLD pending remediation.'
    )

    doc.add_heading('4. Program Financials & Risk Highlights', level=1)
    doc.add_paragraph('• Planned Budget: $1,500,000 USD\n• Current Actual Spend: $1,200,000 USD\n• Forecasted Variance: $300,000 Surplus\n• Active Blocker: Risk R-802 (Critical - High Database Latency)')

    output_path = os.path.abspath(os.path.join(os.getcwd(), '..', 'Alpha_Migration_Vendor_SOW.docx'))
    doc.save(output_path)
    print(f"Successfully generated DOCX at: {output_path}")

    # Plain text version
    txt_path = os.path.abspath(os.path.join(os.getcwd(), '..', 'Alpha_Migration_Vendor_SOW.txt'))
    txt_content = """# STATEMENT OF WORK (SOW) — CONTRACT & MILESTONE SCHEDULE
Program: Alpha Migration Program (PRJ-101)
Vendor: CloudScale Systems & Delivery Partners
Contract Value: $1,500,000 USD
Governance Standard: Autonomous Capital Gatekeeper Framework

## 1. Executive Scope
This Statement of Work defines the contractual delivery milestones, technical SLAs, and financial capital tranche disbursements for Project PRJ-101.

## 2. Milestone Attainment & Financial Tranche Disbursement Schedule
- Milestone 1: Architecture Sign-off & Technical Blueprint
  Timeline: Jan 15 | Tranche Allocation: $350,000 USD | Deliverables: 4/4 Verified | SLA: 98% (Compliant) | Status: Released
- Milestone 2: Core MVP Pipeline & API Gateway Delivery
  Timeline: Feb 28 | Tranche Allocation: $450,000 USD | Deliverables: 4/4 Verified | SLA: 98% (Compliant) | Status: Released
- Milestone 3: Beta Migration Rollout & ERP Integration
  Timeline: Mar 30 | Tranche Allocation: $300,000 USD | Deliverables: 2/4 Verified | SLA: 74% (Breached) | Status: On Hold
- Milestone 4: Full Production Cutover & Final Sign-off
  Timeline: Apr 30 | Tranche Allocation: $400,000 USD | Deliverables: 0/4 Pending | SLA: Scheduled | Status: Locked

## 3. Active Risks & Gatekeeper Blockers
- Risk R-802: SAP ERP Database Connector latency exceeds 250ms contractual threshold (Severity: Critical).
- Risk R-105: Third-party OAuth certificate expiry risk during Beta rollout (Severity: Medium).

## 4. Financial Budget Telemetry
- Planned Total Budget: $1,500,000 USD
- Actual Spend To Date: $1,200,000 USD
- Remaining Capital: $300,000 USD
"""
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    print(f"Successfully generated TXT at: {txt_path}")

if __name__ == '__main__':
    create_sow_doc()
