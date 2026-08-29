"""
Kaizen Audit — Report Generator
=================================
Generates a self-contained HTML report from a completed AuditSession.
Design: navy/gold, DM Sans, printable via browser → PDF.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List

from .scoring import ProcessScore, top_quick_wins, total_monthly_cost, total_annual_saving_estimate
from .service import AuditSession

REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "reports"))

# ── Automation tool hints by process_id ──────────────────────────────────────
TOOL_HINTS = {
    "engagement_letters":      "Docusign / PandaDoc automated templates",
    "aml_kyc":                 "Thirdfort / SmartSearch automated ID checks",
    "client_data_collection":  "Karbon / TaxCalc client portal",
    "bank_feeds":              "Xero bank feed rules + AI categorisation",
    "receipt_processing":      "Dext / AutoEntry receipt scanning",
    "credit_card_recon":       "Xero bank rules auto-reconciliation",
    "vat_data_chase":          "Automated deadline email sequences",
    "vat_prep":                "Xero VAT return automation",
    "vat_filing":              "MTD direct submission via Xero",
    "yearend_data_chase":      "Scheduled client email sequences",
    "trial_balance":           "Xero management reports",
    "accounts_production":     "CCH / Iris automated accounts production",
    "companies_house_filing":  "Xero direct Companies House filing",
    "payroll_data_collection": "BrightPay / Sage Payroll portals",
    "payroll_calculation":     "BrightPay automated payroll calculation",
    "payroll_hmrc_submission":  "RTI auto-submission via BrightPay",
    "sa_data_chase":           "Automated SA questionnaire sequences",
    "sa_prep":                 "TaxCalc / Iris automated SA prep",
    "sa_client_approval":      "Docusign e-signature workflow",
    "deadline_reminders":      "Karbon / HubSpot automated workflows",
    "query_handling":          "AI-assisted query triage",
    "invoice_chasing":         "Automated debtor chase sequences",
    "wip_tracking":            "Karbon / Senta practice management",
    "compliance_monitoring":   "Automated regulatory alert feeds",
    "onboarding_new_staff":    "Documented playbooks + Notion SOPs",
}


def _fmt_gbp(val: float) -> str:
    return f"£{val:,.0f}"


def _score_bar(score: float, max_score: float = 25.0) -> str:
    pct = min(100, int((score / max_score) * 100))
    if score >= 12:
        colour = "#C8A96E"
    elif score >= 6:
        colour = "#E8A838"
    else:
        colour = "#4A8FD4"
    return (
        f'<div style="background:#1A2540;border-radius:3px;height:6px;width:100%;">'
        f'<div style="background:{colour};border-radius:3px;height:6px;width:{pct}%;"></div>'
        f'</div>'
    )


def _process_rows(scores: List[ProcessScore]) -> str:
    rows = []
    for s in scores:
        if s.flag == "leave_alone":
            row_bg = "#131C2E"
            name_col = "#7A8BAA"
            badge = '<span style="font-size:10px;background:rgba(224,90,106,0.12);color:#E05A6A;border:1px solid rgba(224,90,106,0.25);border-radius:3px;padding:1px 6px;">LEAVE</span>'
        elif s.flag == "quick_win":
            row_bg = "rgba(200,169,110,0.05)"
            name_col = "#E8EAF0"
            badge = '<span style="font-size:10px;background:rgba(200,169,110,0.15);color:#C8A96E;border:1px solid rgba(200,169,110,0.3);border-radius:3px;padding:1px 6px;">QUICK WIN</span>'
        else:
            row_bg = "#131C2E"
            name_col = "#A8B4CC"
            badge = ""

        hint = TOOL_HINTS.get(s.process_id, "")
        hint_cell = f'<span style="color:#7A8BAA;font-size:11px;">{hint}</span>' if hint else "—"

        rows.append(f"""
        <tr style="border-bottom:1px solid #1E2D45;background:{row_bg};">
            <td style="padding:10px 14px;color:{name_col};font-weight:500;">
                {s.process_name}<br>
                <small style="color:#7A8BAA;font-weight:400;">{s.staff_role} · {s.time_mins}min × {s.frequency_per_month:.0f}/mo</small>
            </td>
            <td style="padding:10px 14px;text-align:center;">{badge}</td>
            <td style="padding:10px 14px;text-align:right;font-family:'DM Mono',monospace;color:#E8EAF0;">{_fmt_gbp(s.time_cost_monthly)}</td>
            <td style="padding:10px 14px;text-align:right;font-family:'DM Mono',monospace;color:#4CAF8A;">{_fmt_gbp(s.annual_saving_estimate)}</td>
            <td style="padding:10px 14px;min-width:90px;">
                {_score_bar(s.quick_win_score)}
                <div style="text-align:right;font-size:10px;color:#7A8BAA;margin-top:2px;">{s.quick_win_score:.1f}</div>
            </td>
            <td style="padding:10px 14px;">{hint_cell}</td>
        </tr>""")
    return "\n".join(rows)


def _quick_win_cards(scores: List[ProcessScore]) -> str:
    wins = top_quick_wins(scores, n=3)
    if not wins:
        return '<p style="color:#7A8BAA;">No processes met the quick win threshold. Review automation potential ratings.</p>'

    cards = []
    for i, s in enumerate(wins):
        hint = TOOL_HINTS.get(s.process_id, "Automation tooling TBC")
        rank_labels = ["#1 Priority", "#2 Priority", "#3 Priority"]
        rank = rank_labels[i] if i < 3 else f"#{i+1}"
        cards.append(f"""
        <div style="border:1px solid rgba(200,169,110,0.35);background:rgba(200,169,110,0.04);
                    border-radius:10px;padding:20px 22px;flex:1;min-width:220px;">
            <div style="font-size:10px;color:#C8A96E;font-weight:700;letter-spacing:.08em;margin-bottom:8px;">{rank}</div>
            <div style="font-size:16px;font-weight:700;color:#E8EAF0;margin-bottom:4px;">{s.process_name}</div>
            <div style="font-size:12px;color:#7A8BAA;margin-bottom:14px;">{s.staff_role.title()} · {s.time_mins}min × {s.frequency_per_month:.0f}× per month</div>
            <div style="display:flex;gap:16px;margin-bottom:14px;">
                <div>
                    <div style="font-size:10px;color:#7A8BAA;margin-bottom:2px;">MONTHLY COST</div>
                    <div style="font-size:18px;font-weight:700;color:#E8EAF0;font-family:'DM Mono',monospace;">{_fmt_gbp(s.time_cost_monthly)}</div>
                </div>
                <div>
                    <div style="font-size:10px;color:#7A8BAA;margin-bottom:2px;">ANNUAL SAVING</div>
                    <div style="font-size:18px;font-weight:700;color:#4CAF8A;font-family:'DM Mono',monospace;">{_fmt_gbp(s.annual_saving_estimate)}</div>
                </div>
            </div>
            <div style="background:#1A2540;border-radius:6px;padding:10px 12px;font-size:12px;color:#A8B4CC;">
                <span style="color:#C8A96E;font-weight:600;">Recommended: </span>{hint}
            </div>
        </div>""")
    return f'<div style="display:flex;gap:16px;flex-wrap:wrap;">' + "\n".join(cards) + "</div>"


def generate_report(session: AuditSession, scores: List[ProcessScore]) -> Path:
    """Generate the HTML report and return the file path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    from core.config import (
        KAIZEN_SENDER_NAME,
        KAIZEN_SENDER_TITLE,
        KAIZEN_SENDER_COMPANY,
        KAIZEN_SENDER_EMAIL,
        KAIZEN_SENDER_LINKEDIN,
    )

    date_str = datetime.utcnow().strftime("%-d %B %Y")
    monthly_cost  = total_monthly_cost(scores)
    annual_saving = total_annual_saving_estimate(scores)
    quick_win_count = len([s for s in scores if s.flag == "quick_win"])
    leave_alone_count = len([s for s in scores if s.flag == "leave_alone"])
    process_count = len(scores)

    contact_line = KAIZEN_SENDER_EMAIL or KAIZEN_SENDER_LINKEDIN or "Reply to this message"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Automation Audit — {session.firm_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'DM Sans', system-ui, sans-serif;
    background: #0D1421;
    color: #E8EAF0;
    font-size: 14px;
    line-height: 1.6;
  }}
  .page {{ max-width: 960px; margin: 0 auto; padding: 0 0 60px; }}

  /* Cover band */
  .cover {{
    background: #131C2E;
    border-bottom: 2px solid #C8A96E;
    padding: 32px 48px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }}
  .cover-brand {{ font-size: 13px; font-weight: 700; color: #C8A96E; letter-spacing: .08em; }}
  .cover-label {{ font-size: 11px; color: #7A8BAA; margin-top: 4px; }}
  .cover-right {{ text-align: right; font-size: 12px; color: #7A8BAA; }}
  .cover-right strong {{ color: #E8EAF0; display: block; font-size: 13px; margin-bottom: 2px; }}

  /* Firm hero */
  .firm-hero {{
    padding: 40px 48px 32px;
    border-bottom: 1px solid #1E2D45;
  }}
  .firm-eyebrow {{ font-size: 11px; font-weight: 700; color: #C8A96E; letter-spacing: .1em; text-transform: uppercase; margin-bottom: 8px; }}
  .firm-name {{ font-size: 32px; font-weight: 700; color: #E8EAF0; line-height: 1.2; margin-bottom: 6px; }}
  .firm-meta {{ font-size: 13px; color: #7A8BAA; }}

  /* Stat tiles */
  .stat-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0;
    border-bottom: 1px solid #1E2D45;
  }}
  .stat-tile {{
    padding: 24px 28px;
    border-right: 1px solid #1E2D45;
  }}
  .stat-tile:last-child {{ border-right: none; }}
  .stat-label {{ font-size: 10px; font-weight: 700; color: #7A8BAA; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 6px; }}
  .stat-value {{ font-size: 28px; font-weight: 700; font-family: 'DM Mono', monospace; color: #E8EAF0; line-height: 1; }}
  .stat-value.gold   {{ color: #C8A96E; }}
  .stat-value.green  {{ color: #4CAF8A; }}
  .stat-value.amber  {{ color: #E8A838; }}
  .stat-sub {{ font-size: 11px; color: #7A8BAA; margin-top: 4px; }}

  /* Section */
  .section {{ padding: 36px 48px; border-bottom: 1px solid #1E2D45; }}
  .section-title {{
    font-size: 11px; font-weight: 700; color: #C8A96E;
    letter-spacing: .1em; text-transform: uppercase;
    margin-bottom: 20px; padding-bottom: 10px;
    border-bottom: 1px solid rgba(200,169,110,0.2);
  }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    padding: 8px 14px; font-size: 10px; font-weight: 700;
    color: #7A8BAA; letter-spacing: .06em; text-transform: uppercase;
    background: #1A2540; text-align: left;
    border-bottom: 1px solid #1E2D45;
  }}
  thead th:not(:first-child) {{ text-align: right; }}
  thead th:nth-child(2) {{ text-align: center; }}
  thead th:last-child {{ text-align: left; }}

  /* Notes */
  .notes-box {{
    background: #1A2540; border-radius: 8px;
    padding: 16px 18px; font-size: 13px; color: #A8B4CC;
    white-space: pre-wrap; font-family: 'DM Mono', monospace;
    font-size: 12px;
  }}

  /* Footer */
  .footer {{
    padding: 28px 48px;
    background: #131C2E;
    border-top: 1px solid #1E2D45;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .footer-brand {{ font-size: 13px; font-weight: 700; color: #C8A96E; }}
  .footer-contact {{ font-size: 12px; color: #7A8BAA; text-align: right; }}
  .footer-contact a {{ color: #A8C4E8; text-decoration: none; }}

  /* CTA */
  .cta-box {{
    background: rgba(200,169,110,0.06);
    border: 1px solid rgba(200,169,110,0.25);
    border-radius: 10px;
    padding: 24px 28px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 24px;
    flex-wrap: wrap;
  }}
  .cta-text {{ font-size: 15px; font-weight: 600; color: #E8EAF0; }}
  .cta-sub  {{ font-size: 13px; color: #7A8BAA; margin-top: 3px; }}
  .cta-contact {{
    font-size: 14px; font-weight: 600; color: #C8A96E;
    background: rgba(200,169,110,0.1);
    border: 1px solid rgba(200,169,110,0.3);
    border-radius: 6px; padding: 10px 20px;
    white-space: nowrap;
  }}

  @media print {{
    body {{ background: #fff; color: #111; }}
    .cover, .footer {{ background: #f5f5f0; }}
    .cover {{ border-bottom-color: #b8943e; }}
    .stat-tile, .section, .firm-hero {{ border-color: #e0e0e0; }}
    .stat-value {{ color: #111; }}
    .firm-name {{ color: #111; }}
    .cover-brand, .footer-brand, .section-title {{ color: #b8943e; }}
    .notes-box {{ background: #f9f9f7; color: #333; }}
    .cta-box {{ background: #faf9f5; border-color: #b8943e; }}
  }}
</style>
</head>
<body>
<div class="page">

  <!-- Cover -->
  <div class="cover">
    <div>
      <div class="cover-brand">◈ KAIZEN STUDIOS</div>
      <div class="cover-label">Automation Audit Report · Confidential</div>
    </div>
    <div class="cover-right">
      <strong>{date_str}</strong>
      Prepared by {KAIZEN_SENDER_NAME}, {KAIZEN_SENDER_TITLE}
    </div>
  </div>

  <!-- Firm hero -->
  <div class="firm-hero">
    <div class="firm-eyebrow">Practice Automation Audit</div>
    <div class="firm-name">{session.firm_name}</div>
    <div class="firm-meta">Audited by {session.auditor} &nbsp;·&nbsp; {process_count} processes reviewed &nbsp;·&nbsp; {date_str}</div>
  </div>

  <!-- Stat tiles -->
  <div class="stat-row">
    <div class="stat-tile">
      <div class="stat-label">Monthly Manual Cost</div>
      <div class="stat-value gold">{_fmt_gbp(monthly_cost)}</div>
      <div class="stat-sub">Labour cost of manual processes</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">Annual Saving Potential</div>
      <div class="stat-value green">{_fmt_gbp(annual_saving)}</div>
      <div class="stat-sub">Estimated at 80% time reduction</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">Quick Wins Found</div>
      <div class="stat-value amber">{quick_win_count}</div>
      <div class="stat-sub">High-impact, low-risk automations</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">Processes Audited</div>
      <div class="stat-value">{process_count}</div>
      <div class="stat-sub">{leave_alone_count} flagged leave alone</div>
    </div>
  </div>

  <!-- Quick wins -->
  <div class="section">
    <div class="section-title">Priority Quick Wins</div>
    {_quick_win_cards(scores)}
  </div>

  <!-- Full breakdown -->
  <div class="section">
    <div class="section-title">Full Process Breakdown</div>
    <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr>
            <th>Process</th>
            <th>Flag</th>
            <th>Monthly Cost</th>
            <th>Annual Saving</th>
            <th>Score</th>
            <th>Recommended Tool</th>
          </tr>
        </thead>
        <tbody>
          {_process_rows(scores)}
        </tbody>
      </table>
    </div>
  </div>

  {"<!-- Notes --><div class='section'><div class='section-title'>Auditor Notes</div><div class='notes-box'>" + session.notes + "</div></div>" if session.notes.strip() else ""}

  <!-- CTA -->
  <div class="section">
    <div class="section-title">Recommended Next Steps</div>
    <div class="cta-box">
      <div>
        <div class="cta-text">Ready to reclaim {_fmt_gbp(annual_saving)} per year?</div>
        <div class="cta-sub">Book a 30-minute call to walk through the quick wins and agree a build plan. No obligation.</div>
      </div>
      <div class="cta-contact">{contact_line}</div>
    </div>
  </div>

</div>

<!-- Footer -->
<div class="footer">
  <div>
    <div class="footer-brand">◈ KAIZEN STUDIOS</div>
    <div style="font-size:11px;color:#7A8BAA;margin-top:2px;">AI Automation for UK Accountancy Practices</div>
  </div>
  <div class="footer-contact">
    {KAIZEN_SENDER_NAME} · {KAIZEN_SENDER_TITLE}<br>
    {f'<a href="mailto:{KAIZEN_SENDER_EMAIL}">{KAIZEN_SENDER_EMAIL}</a>' if KAIZEN_SENDER_EMAIL else ''}
    {' · ' if KAIZEN_SENDER_EMAIL and KAIZEN_SENDER_LINKEDIN else ''}
    {f'<a href="{KAIZEN_SENDER_LINKEDIN}">LinkedIn</a>' if KAIZEN_SENDER_LINKEDIN else ''}
  </div>
</div>

</body>
</html>"""

    report_path = REPORTS_DIR / f"audit_{session.id}.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
