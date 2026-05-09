"""Fixture data served to demo-mode sessions.

Returned in place of real Gmail/Calendar API calls so reviewers can exercise
the full UI without granting access to a personal inbox.
"""
from __future__ import annotations

from app.models import EmailResult

_DEMO_EMAILS: list[EmailResult] = [
    EmailResult(
        subject="Re: Onsite interview loop — confirming Thursday 2pm",
        sender="recruiter@stripe.com",
        category="action",
        summary=(
            "Recruiter is confirming your onsite loop for Thursday at 2pm PT and "
            "needs a written confirmation plus dietary preferences for lunch."
        ),
        draft_id="demo-draft-001",
        calendar_status="conflict: 'Team standup' 2:00–2:30pm",
    ),
    EmailResult(
        subject="Action required: Sign updated W-9 before Friday",
        sender="payroll@acme-corp.com",
        category="action",
        summary=(
            "Payroll needs you to sign the updated W-9 in DocuSign before Friday "
            "to avoid a hold on next week's paycheck."
        ),
        draft_id="demo-draft-002",
        calendar_status=None,
    ),
    EmailResult(
        subject="Coffee chat next week?",
        sender="alex.chen@friend.dev",
        category="action",
        summary=(
            "Alex is in town next Tuesday or Wednesday and is asking if you're "
            "free for a 30-minute coffee. Suggests Sightglass on Folsom."
        ),
        draft_id="demo-draft-003",
        calendar_status="free both days 10–11am",
    ),
    EmailResult(
        subject="Your weekly LangChain digest",
        sender="newsletter@langchain.dev",
        category="fyi",
        summary=(
            "Weekly roundup: new LangGraph release, three community tutorials on "
            "agent evaluation, and an upcoming webinar on tool use."
        ),
        draft_id=None,
        calendar_status=None,
    ),
    EmailResult(
        subject="GitHub: 3 new pull requests in scarlet-hu/InboxZero-Agent",
        sender="notifications@github.com",
        category="fyi",
        summary=(
            "Three PRs opened today: a Dockerfile cleanup, a README typo fix, "
            "and a new MCP server tool. No reviews requested from you directly."
        ),
        draft_id=None,
        calendar_status=None,
    ),
    EmailResult(
        subject="Your AWS bill for April is now available",
        sender="no-reply@aws.amazon.com",
        category="fyi",
        summary="April AWS invoice for $12.47 is now available in the billing console.",
        draft_id=None,
        calendar_status=None,
    ),
    EmailResult(
        subject="🎉 You've been selected! Claim your $500 prize NOW",
        sender="winner-notification@sketchy-promos.biz",
        category="spam",
        summary="Promotional spam claiming you've won a prize — flagged for deletion.",
        draft_id=None,
        calendar_status=None,
    ),
    EmailResult(
        subject="URGENT: Verify your account or it will be suspended",
        sender="security-alert@phish-domain.tk",
        category="spam",
        summary=(
            "Phishing attempt impersonating account-security warnings. Suspicious "
            "sender domain and pressure tactics — do not click."
        ),
        draft_id=None,
        calendar_status=None,
    ),
    EmailResult(
        subject="Quick favor: can you review my design doc?",
        sender="priya.k@coworker.dev",
        category="action",
        summary=(
            "Priya is asking for feedback on her v2 design doc for the rate-limiter "
            "rewrite. Wants comments by end of week."
        ),
        draft_id="demo-draft-004",
        calendar_status=None,
    ),
    EmailResult(
        subject="Lunch & Learn: Building agents with LangGraph (Friday)",
        sender="events@company.com",
        category="fyi",
        summary=(
            "Optional internal Lunch & Learn on Friday at noon covering LangGraph "
            "patterns. Recording will be available afterward."
        ),
        draft_id=None,
        calendar_status="free 12–1pm Friday",
    ),
]


def get_demo_results(max_results: int) -> list[EmailResult]:
    return _DEMO_EMAILS[: max(0, max_results)]
