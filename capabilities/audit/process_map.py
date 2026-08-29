"""
Kaizen Audit — Standard Process Map
====================================
Defines the canonical set of accountancy processes audited during a
Kaizen Audit session. Each process carries a base automation potential
score and descriptive metadata to guide the conversation.

Kane can toggle each process active/inactive per firm and override
any field during the live session.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class AuditProcess:
    """One auditable process within an accountancy practice."""

    id: str
    name: str
    description: str          # Prompt for Kane during the call
    base_automation: int      # 1–5 default automation potential
    base_risk: int            # 1–5 default risk score
    typical_time_mins: int    # Suggested starting point for time estimate
    example_tools: List[str] = field(default_factory=list)  # Common tools seen


@dataclass
class ProcessCategory:
    """A logical grouping of audit processes."""
    id: str
    name: str
    icon: str
    processes: List[AuditProcess] = field(default_factory=list)


PROCESS_MAP: List[ProcessCategory] = [
    ProcessCategory(
        id="onboarding",
        name="Client Onboarding",
        icon="🚪",
        processes=[
            AuditProcess(
                id="engagement_letters",
                name="Engagement letters & e-signing",
                description="Drafting, sending, chasing, and filing engagement letters",
                base_automation=4,
                base_risk=2,
                typical_time_mins=30,
                example_tools=["email", "DocuSign", "manual post"],
            ),
            AuditProcess(
                id="aml_kyc",
                name="AML / KYC checks",
                description="Identity verification, source of funds checks, filing results",
                base_automation=3,
                base_risk=4,
                typical_time_mins=45,
                example_tools=["SmartSearch", "manual", "Companies House"],
            ),
            AuditProcess(
                id="client_data_collection",
                name="Initial client data collection",
                description="Gathering chart of accounts, prior year figures, login credentials",
                base_automation=4,
                base_risk=2,
                typical_time_mins=60,
                example_tools=["email", "Dropbox", "spreadsheet"],
            ),
        ],
    ),
    ProcessCategory(
        id="bookkeeping",
        name="Bookkeeping & Data Entry",
        icon="📒",
        processes=[
            AuditProcess(
                id="bank_feeds",
                name="Bank feed reconciliation",
                description="Reviewing uncategorised transactions, applying rules, matching receipts",
                base_automation=5,
                base_risk=2,
                typical_time_mins=40,
                example_tools=["Xero", "QuickBooks", "Sage"],
            ),
            AuditProcess(
                id="receipt_processing",
                name="Receipt & invoice processing",
                description="Receiving, scanning, coding, and filing supplier invoices and receipts",
                base_automation=5,
                base_risk=2,
                typical_time_mins=30,
                example_tools=["Dext", "AutoEntry", "email", "manual"],
            ),
            AuditProcess(
                id="credit_card_recon",
                name="Credit card reconciliation",
                description="Matching credit card statements to bookkeeping records",
                base_automation=4,
                base_risk=2,
                typical_time_mins=25,
                example_tools=["Xero", "spreadsheet"],
            ),
        ],
    ),
    ProcessCategory(
        id="vat",
        name="VAT Returns",
        icon="📊",
        processes=[
            AuditProcess(
                id="vat_data_chase",
                name="Client data chase for VAT",
                description="Chasing missing invoices, bank statements, or queries before filing",
                base_automation=5,
                base_risk=1,
                typical_time_mins=45,
                example_tools=["email", "phone", "WhatsApp"],
            ),
            AuditProcess(
                id="vat_prep",
                name="VAT return preparation",
                description="Reviewing figures, adjusting entries, preparing the return",
                base_automation=3,
                base_risk=3,
                typical_time_mins=60,
                example_tools=["Xero", "QuickBooks", "Sage", "spreadsheet"],
            ),
            AuditProcess(
                id="vat_filing",
                name="VAT filing & confirmation",
                description="Filing with HMRC, saving confirmation, updating client",
                base_automation=4,
                base_risk=2,
                typical_time_mins=15,
                example_tools=["HMRC MTD", "Xero", "BTC"],
            ),
        ],
    ),
    ProcessCategory(
        id="yearend",
        name="Year-End Accounts",
        icon="📅",
        processes=[
            AuditProcess(
                id="yearend_data_chase",
                name="Year-end client data chase",
                description="Requesting bank statements, invoices, payroll summaries, loan schedules",
                base_automation=5,
                base_risk=1,
                typical_time_mins=90,
                example_tools=["email", "phone", "Dropbox"],
            ),
            AuditProcess(
                id="trial_balance",
                name="Trial balance prep & adjustments",
                description="Journal entries, depreciation, accruals, prepayments",
                base_automation=2,
                base_risk=4,
                typical_time_mins=120,
                example_tools=["Xero", "Sage", "spreadsheet"],
            ),
            AuditProcess(
                id="accounts_production",
                name="Statutory accounts production",
                description="Producing statutory accounts in the correct format for filing",
                base_automation=2,
                base_risk=4,
                typical_time_mins=180,
                example_tools=["Xero", "IRIS", "CCH", "VT"],
            ),
            AuditProcess(
                id="companies_house_filing",
                name="Companies House & HMRC filing",
                description="Filing accounts at Companies House and CT600 with HMRC",
                base_automation=3,
                base_risk=3,
                typical_time_mins=30,
                example_tools=["Companies House portal", "HMRC", "IRIS"],
            ),
        ],
    ),
    ProcessCategory(
        id="payroll",
        name="Payroll",
        icon="💰",
        processes=[
            AuditProcess(
                id="payroll_data_collection",
                name="Payroll data collection",
                description="Chasing starters, leavers, hours, overtime, expenses from clients",
                base_automation=5,
                base_risk=2,
                typical_time_mins=30,
                example_tools=["email", "spreadsheet", "WhatsApp"],
            ),
            AuditProcess(
                id="payroll_calculation",
                name="Payroll calculation & payslips",
                description="Running payroll, generating payslips, calculating PAYE/NI",
                base_automation=3,
                base_risk=3,
                typical_time_mins=45,
                example_tools=["BrightPay", "Xero Payroll", "Sage Payroll", "Moneysoft"],
            ),
            AuditProcess(
                id="payroll_hmrc_submission",
                name="RTI submission to HMRC",
                description="Submitting FPS/EPS to HMRC and confirming receipt",
                base_automation=4,
                base_risk=3,
                typical_time_mins=15,
                example_tools=["BrightPay", "HMRC Basic PAYE"],
            ),
        ],
    ),
    ProcessCategory(
        id="selfassessment",
        name="Self-Assessment",
        icon="🧾",
        processes=[
            AuditProcess(
                id="sa_data_chase",
                name="SA client data chase",
                description="Annual chase for P60s, dividend certs, rental income, bank interest",
                base_automation=5,
                base_risk=1,
                typical_time_mins=60,
                example_tools=["email", "standard letter", "phone"],
            ),
            AuditProcess(
                id="sa_prep",
                name="SA return preparation",
                description="Entering data, calculating tax liability, reviewing",
                base_automation=2,
                base_risk=3,
                typical_time_mins=90,
                example_tools=["IRIS", "Taxcalc", "CCH", "Xero Tax"],
            ),
            AuditProcess(
                id="sa_client_approval",
                name="Client approval & filing",
                description="Sending draft to client, chasing approval, filing with HMRC",
                base_automation=4,
                base_risk=2,
                typical_time_mins=20,
                example_tools=["email", "DocuSign", "HMRC portal"],
            ),
        ],
    ),
    ProcessCategory(
        id="communication",
        name="Client Communication & Chasing",
        icon="📬",
        processes=[
            AuditProcess(
                id="deadline_reminders",
                name="Deadline reminders",
                description="Sending filing deadline reminders to clients across all services",
                base_automation=5,
                base_risk=1,
                typical_time_mins=20,
                example_tools=["email", "manual calendar", "spreadsheet"],
            ),
            AuditProcess(
                id="query_handling",
                name="Client query handling",
                description="Answering ad-hoc client questions by email or phone",
                base_automation=2,
                base_risk=2,
                typical_time_mins=60,
                example_tools=["email", "phone"],
            ),
            AuditProcess(
                id="invoice_chasing",
                name="Invoice chasing & billing",
                description="Raising invoices, chasing overdue payments, recording receipts",
                base_automation=4,
                base_risk=1,
                typical_time_mins=30,
                example_tools=["Xero", "QuickBooks", "email", "phone"],
            ),
        ],
    ),
    ProcessCategory(
        id="practice",
        name="Practice Management",
        icon="⚙️",
        processes=[
            AuditProcess(
                id="wip_tracking",
                name="WIP & job tracking",
                description="Tracking work in progress, job status, team workload",
                base_automation=3,
                base_risk=2,
                typical_time_mins=30,
                example_tools=["spreadsheet", "Karbon", "TaxCalc", "Practice Ignition"],
            ),
            AuditProcess(
                id="compliance_monitoring",
                name="Compliance & deadline monitoring",
                description="Monitoring upcoming filing deadlines across all clients",
                base_automation=4,
                base_risk=3,
                typical_time_mins=30,
                example_tools=["spreadsheet", "Taxfiler", "IRIS", "Companies House API"],
            ),
            AuditProcess(
                id="onboarding_new_staff",
                name="Staff onboarding & training",
                description="Onboarding new team members, documenting processes, handovers",
                base_automation=3,
                base_risk=2,
                typical_time_mins=240,
                example_tools=["email", "Notion", "Word docs"],
            ),
        ],
    ),
]


def get_all_processes() -> List[AuditProcess]:
    """Return a flat list of all processes across all categories."""
    return [p for cat in PROCESS_MAP for p in cat.processes]


def get_process(process_id: str) -> AuditProcess | None:
    """Return a process by ID."""
    return next((p for p in get_all_processes() if p.id == process_id), None)
