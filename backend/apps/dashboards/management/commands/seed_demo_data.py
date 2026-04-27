"""Seed the database with demo fixtures matching the frontend mockData.

The deterministic generators (`pick`, `rand`, `phone`) are direct ports of the
TypeScript helpers in ``frontend/src/services/mockData.ts`` — same indexing,
same modulo math — so seeded rows have the same IDs the frontend already
shows. Run with::

    python manage.py seed_demo_data --reset

``--reset`` truncates the demo tables first; without it the command upserts
and is safe to re-run (good for incremental dev).
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.agents.models import Agent
from apps.ai_governance.models import CaioAudit, CeoBriefing, CeoRecommendation
from apps.analytics.models import KPITrend
from apps.audit.models import AuditEvent
from apps.calls.models import ActiveCall, Call, CallTranscriptLine
from apps.compliance.models import Claim
from apps.crm.models import Customer, Lead
from apps.dashboards.models import DashboardMetric
from apps.learning_engine.models import LearningRecording
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.rewards.models import RewardPenalty
from apps.shipments.models import Shipment, WorkflowStep

# ----- Constants mirrored from mockData.ts -----

PRODUCT_CATEGORIES: Sequence[str] = (
    "Weight Management",
    "Blood Purification",
    "Men Wellness",
    "Women Wellness",
    "Immunity Booster",
    "Lungs Detox",
    "Body Detox",
    "Joint Care",
)

STATES: Sequence[str] = (
    "Maharashtra",
    "Delhi",
    "Uttar Pradesh",
    "Rajasthan",
    "Gujarat",
    "Madhya Pradesh",
    "Bihar",
    "Karnataka",
    "Tamil Nadu",
    "Punjab",
    "Haryana",
    "West Bengal",
    "Telangana",
    "Odisha",
)

NAMES: Sequence[str] = (
    "Rajesh Kumar", "Sunita Verma", "Amit Sharma", "Priya Singh", "Vikas Yadav",
    "Neha Gupta", "Mohammed Aslam", "Anita Devi", "Suresh Patel", "Kavita Joshi",
    "Arun Mehta", "Pooja Rani", "Dinesh Choudhary", "Manju Bisht", "Ravi Shankar",
    "Lakshmi Nair", "Sandeep Rathore", "Geeta Kumari", "Vivek Tiwari", "Shilpa Reddy",
    "Karan Malhotra", "Asha Pandey", "Naveen Kashyap", "Bharti Saxena", "Hemant Goswami",
    "Renu Bansal", "Tushar Khanna", "Sushma Iyer", "Pankaj Mishra", "Deepa Bhatia",
)

CITIES: dict[str, list[str]] = {
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik"],
    "Delhi": ["New Delhi", "Dwarka", "Rohini"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara"],
    "Madhya Pradesh": ["Indore", "Bhopal", "Gwalior"],
    "Bihar": ["Patna", "Gaya"],
    "Karnataka": ["Bengaluru", "Mysuru"],
    "Tamil Nadu": ["Chennai", "Coimbatore"],
    "Punjab": ["Ludhiana", "Amritsar"],
    "Haryana": ["Gurgaon", "Faridabad"],
    "West Bengal": ["Kolkata", "Howrah"],
    "Telangana": ["Hyderabad"],
    "Odisha": ["Bhubaneswar", "Cuttack"],
}

SOURCES: Sequence[str] = ("Meta Ads", "Inbound Call", "Google Ads", "Influencer", "WhatsApp", "Referral")
CAMPAIGNS: Sequence[str] = (
    "Monsoon Detox '25",
    "Men Vitality Push",
    "Skin Glow Reels",
    "Immunity Winter",
    "Pollution Shield",
    "Joint Relief 30+",
)
LANGUAGES: Sequence[str] = ("Hindi", "Hinglish", "English", "Marathi", "Punjabi", "Bengali")

LEAD_STATUSES: Sequence[str] = (
    "New",
    "AI Calling Started",
    "Interested",
    "Callback Required",
    "Payment Link Sent",
    "Order Punched",
    "Not Interested",
    "Invalid",
)
QUALITIES: Sequence[str] = ("Hot", "Warm", "Cold")
ASSIGNEES: Sequence[str] = ("Priya (Human)", "Anil (Human)", "Calling AI · Vaani-2")
DISEASES: Sequence[str] = (
    "Obesity",
    "Acne / Skin",
    "Low Stamina",
    "PCOS support",
    "Frequent cold",
    "Smoker's lungs",
    "Joint pain",
)
LIFESTYLE_NOTES: Sequence[str] = (
    "Sedentary, eats outside food 4x/week",
    "Night shift worker, sleeps 5 hrs",
    "Vegetarian, walks daily",
    "Diabetic family history",
    "Smokes 5/day, urban polluted area",
)
OBJECTION_BUNDLES: Sequence[Sequence[str]] = (
    ("Too expensive", "Tried similar before"),
    ("Wants doctor consult",),
    ("Wife decides",),
    ("Wants COD",),
)

ORDER_STAGES: Sequence[str] = (
    "New Lead",
    "Interested",
    "Payment Link Sent",
    "Order Punched",
    "Confirmation Pending",
    "Confirmed",
    "Dispatched",
    "Out for Delivery",
    "Delivered",
    "RTO",
)


# ----- Deterministic helpers (same math as mockData.ts) -----

def _pick(arr: Sequence[Any], i: int) -> Any:
    return arr[i % len(arr)]


def _rand(seed: int) -> float:
    return ((seed * 9301 + 49297) % 233280) / 233280


def _phone(seed: int) -> str:
    n = int(_rand(seed) * 9000000 + 1000000)
    return f"+91 9{seed % 10}{(seed * 7) % 10}{str(n)[:7]}"


# ----- Builders -----

def _build_leads() -> list[dict]:
    leads: list[dict] = []
    for i in range(42):
        state = _pick(STATES, i)
        cities = CITIES.get(state, ["—"])
        leads.append(
            {
                "id": f"LD-{10234 + i}",
                "name": _pick(NAMES, i),
                "phone": _phone(i + 11),
                "state": state,
                "city": _pick(cities, i),
                "language": _pick(LANGUAGES, i + 1),
                "source": _pick(SOURCES, i + 2),
                "campaign": _pick(CAMPAIGNS, i + 3),
                "product_interest": _pick(PRODUCT_CATEGORIES, i + 1),
                "status": _pick(LEAD_STATUSES, i),
                "quality": _pick(QUALITIES, i),
                "quality_score": 40 + int(_rand(i + 5) * 60),
                "assignee": "Calling AI · Vaani-3" if i % 3 == 0 else _pick(ASSIGNEES, i),
                "duplicate": i % 11 == 0,
                "created_at_label": f"{i % 23:02d} min ago",
            }
        )
    return leads


def _build_customers(leads: list[dict]) -> list[dict]:
    customers: list[dict] = []
    for i, l in enumerate(leads[:24]):
        customers.append(
            {
                "id": f"CU-{5000 + i}",
                "lead_id": l["id"],
                "name": l["name"],
                "phone": l["phone"],
                "state": l["state"],
                "city": l["city"],
                "language": l["language"],
                "product_interest": l["product_interest"],
                "disease_category": _pick(DISEASES, i),
                "lifestyle_notes": _pick(LIFESTYLE_NOTES, i),
                "objections": list(_pick(OBJECTION_BUNDLES, i)),
                "ai_summary": (
                    "Polite, language-clear caller. Mid-income, COD-leaning. "
                    "Responded well to lifestyle questions and accepted ₹499 advance after 12% discount."
                ),
                "risk_flags": ["Address pin mismatch"] if i % 5 == 0 else [],
                "reorder_probability": 30 + ((i * 7) % 65),
                "satisfaction": 3 + (i % 3),
                "consent_call": True,
                "consent_whatsapp": i % 2 == 0,
                "consent_marketing": i % 3 == 0,
            }
        )
    return customers


def _build_orders() -> list[dict]:
    orders: list[dict] = []
    payment_statuses = ("Paid", "Partial", "Pending", "Failed")
    rto_risks = ("Low", "Medium", "High")
    agents_list = (
        "Calling AI · Vaani-3",
        "Priya (Human)",
        "Anil (Human)",
        "Calling AI · Vaani-2",
    )
    discount_options = (0, 10, 12, 15, 20, 25, 30)
    base_amount = 3000
    for i in range(60):
        state = _pick(STATES, i + 4)
        cities = CITIES.get(state, ["—"])
        discount_pct = _pick(discount_options, i)
        amount = round(base_amount * (1 - discount_pct / 100))
        advance_paid = i % 3 != 0
        orders.append(
            {
                "id": f"NRG-{20410 + i}",
                "customer_name": _pick(NAMES, i + 4),
                "phone": _phone(i + 70),
                "product": _pick(PRODUCT_CATEGORIES, i),
                "quantity": 1 + (i % 2),
                "amount": amount,
                "discount_pct": discount_pct,
                "advance_paid": advance_paid,
                "advance_amount": 499 if advance_paid else 0,
                "payment_status": _pick(payment_statuses, i),
                "state": state,
                "city": _pick(cities, i),
                "rto_risk": rto_risks[(i + discount_pct // 10) % 3],
                "rto_score": 10 + ((i * 13) % 85),
                "agent": _pick(agents_list, i),
                "stage": ORDER_STAGES[i % len(ORDER_STAGES)],
                "awb": f"DLH{1000000 + i * 13}" if i > 20 else None,
                "age_hours": (i * 3) % 72,
                "created_at_label": f"{i % 14}d ago",
            }
        )
    return orders


def _augment_confirmation_queue(orders: list[dict]) -> None:
    """Mirror CONFIRMATION_QUEUE: first 10 orders in 'Confirmation Pending' or 'Order Punched'."""
    pending = [o for o in orders if o["stage"] in {"Confirmation Pending", "Order Punched"}][:10]
    for i, o in enumerate(pending):
        o["hours_waiting"] = 6 + i * 3
        o["address_confidence"] = 50 + (i * 4) % 50
        o["confirmation_checklist"] = {
            "name": False,
            "address": False,
            "product": False,
            "amount": False,
            "intent": False,
        }


def _augment_rto(orders: list[dict]) -> None:
    """Mirror RTO_RISK_ORDERS: rtoRisk != Low, sliced 14."""
    risky = [o for o in orders if o["rto_risk"] != "Low"][:14]
    risk_bundles = (
        ["No advance payment", "Price objection"],
        ["Weak confirmation", "Address issue"],
        ["High-risk region", "No response"],
        ["Repeated COD failure"],
    )
    rescue_statuses = ("Pending", "Rescue Call Done", "Convinced", "Returning")
    for i, o in enumerate(risky):
        o["risk_reasons"] = list(_pick(risk_bundles, i))
        o["rescue_status"] = _pick(rescue_statuses, i)


def _build_calls(leads: list[dict]) -> list[dict]:
    calls: list[dict] = []
    statuses = ("Live", "Queued", "Completed", "Missed")
    sentiments = ("Positive", "Neutral", "Hesitant", "Annoyed")
    human_agents = ("Priya (Human)", "Anil (Human)")
    for i in range(18):
        l = leads[i % len(leads)]
        calls.append(
            {
                "id": f"CL-{8400 + i}",
                "lead_id": l["id"],
                "customer": l["name"],
                "phone": l["phone"],
                "agent": "Calling AI · Vaani-3" if i % 2 == 0 else _pick(human_agents, i),
                "language": _pick(LANGUAGES, i),
                "duration": f"{2 + (i % 7)}m {(i * 11) % 60}s",
                "status": _pick(statuses, i),
                "sentiment": _pick(sentiments, i),
                "script_compliance": 80 + (i % 20),
                "payment_link_sent": i % 4 == 0,
            }
        )
    return calls


ACTIVE_CALL_PAYLOAD: dict = {
    "id": "CL-LIVE-001",
    "customer": "Rajesh Kumar",
    "phone": "+91 9*****8421",
    "agent": "Calling AI · Vaani-3",
    "language": "Hinglish",
    "duration": "03:42",
    "stage": "Objection Handling",
    "sentiment": "Hesitant",
    "script_compliance": 96,
    "detected_objections": ["Price concern", "Past failure"],
    "approved_claims_used": ["Lifestyle support claim v3.2", "Ayurvedic blend description"],
    "transcript": [
        ("AI", "Namaste sir, main Nirogidhara se Vaani bol rahi hoon. 2 minute baat kar sakte hain?"),
        ("Customer", "Haan bolo, lekin jaldi."),
        ("AI", "Sir aapne weight management ke liye enquiry ki thi — aap ka kaam mostly sitting wala hai?"),
        ("Customer", "Haan office job hai. Lekin pehle bhi try kiya, kuch nahi hua."),
        ("AI", "Samajh sakti hoon. Hamara product Approved Claim Vault ke andar Ayurvedic blend hai. Result lifestyle ke saath better hota hai."),
        ("Customer", "Price kya hai?"),
        ("AI", "30 capsules ka pack ₹3000 hai. Aaj advance ₹499 dene par 12% off mil jayega."),
    ],
}


def _build_payments(orders: list[dict]) -> list[dict]:
    payments: list[dict] = []
    statuses = ("Paid", "Pending", "Failed", "Refunded")
    types = ("Advance", "Full")
    for i in range(30):
        o = orders[i % len(orders)]
        payments.append(
            {
                "id": f"PAY-{30100 + i}",
                "order_id": o["id"],
                "customer": o["customer_name"],
                "amount": o["amount"],
                "gateway": "Razorpay" if i % 2 == 0 else "PayU",
                "status": _pick(statuses, i),
                "type": _pick(types, i),
                "time": f"{i % 23}:{(i * 7) % 60:02d}",
            }
        )
    return payments


def _build_shipments(orders: list[dict]) -> list[dict]:
    shipments: list[dict] = []
    statuses = ("Pickup Scheduled", "In Transit", "Out for Delivery", "Delivered", "RTO Initiated")
    awb_orders = [o for o in orders if o["awb"]]
    for i, o in enumerate(awb_orders):
        shipments.append(
            {
                "awb": o["awb"],
                "order_id": o["id"],
                "customer": o["customer_name"],
                "state": o["state"],
                "city": o["city"],
                "status": _pick(statuses, i),
                "eta": f"{1 + (i % 5)} days",
                "courier": "Delhivery",
                "timeline": [
                    {"step": "AWB Generated", "at": "Day 0", "done": True, "order": 0},
                    {"step": "Pickup Scheduled", "at": "Day 0", "done": True, "order": 1},
                    {"step": "In Transit", "at": "Day 1", "done": i > 1, "order": 2},
                    {"step": "Out for Delivery", "at": "Day 3", "done": i > 4, "order": 3},
                    {"step": "Delivered / RTO", "at": "Day 4", "done": i > 6, "order": 4},
                ],
            }
        )
    return shipments


AGENTS_PAYLOAD: list[dict] = [
    {"id": "ceo", "name": "CEO AI Agent", "role": "Business command & execution approval", "status": "active", "health": 96, "reward": 1240, "penalty": 86, "last_action": "Approved 12% discount cap for Rajasthan COD", "critical": False, "group": "Command"},
    {"id": "caio", "name": "CAIO Agent", "role": "Governance, audit & training only — never executes", "status": "warning", "health": 88, "reward": 0, "penalty": 0, "last_action": "Flagged Sales Growth Agent over-weighting", "critical": True, "group": "Governance"},
    {"id": "ads", "name": "Ads Agent", "role": "Meta/Google performance & scaling", "status": "active", "health": 91, "reward": 320, "penalty": 18, "last_action": "Paused 2 underperforming creatives", "critical": False, "group": "Marketing"},
    {"id": "marketing", "name": "Marketing Agent", "role": "Funnel & creative orchestration", "status": "active", "health": 89, "reward": 210, "penalty": 12, "last_action": "Drafted 4 hook variants for Men Vitality", "critical": False, "group": "Marketing"},
    {"id": "sales", "name": "Sales Growth Agent", "role": "Conversion strategy & price/discount", "status": "warning", "health": 74, "reward": 410, "penalty": 122, "last_action": "Suggested 25% discount campaign (over rule)", "critical": False, "group": "Sales"},
    {"id": "calling-tl", "name": "Calling Agent Team Leader", "role": "Live AI call orchestration", "status": "active", "health": 93, "reward": 540, "penalty": 44, "last_action": "Re-routed 18 calls to Vaani-3 voice", "critical": False, "group": "Sales"},
    {"id": "calling-qa", "name": "Calling Quality Analyst", "role": "Script compliance & QA", "status": "active", "health": 95, "reward": 220, "penalty": 8, "last_action": "QA scored 142 calls today", "critical": False, "group": "Quality"},
    {"id": "data", "name": "Data Analyst Agent", "role": "Cross-team insight generation", "status": "active", "health": 90, "reward": 180, "penalty": 6, "last_action": "Built funnel cohort for Q3", "critical": False, "group": "Insights"},
    {"id": "cfo", "name": "CFO AI Agent", "role": "Net delivered profit & cash flow", "status": "active", "health": 92, "reward": 360, "penalty": 14, "last_action": "Profit reconciliation for last 7 days", "critical": False, "group": "Finance"},
    {"id": "compliance", "name": "Compliance & Medical Safety", "role": "Claim Vault enforcement", "status": "active", "health": 98, "reward": 410, "penalty": 2, "last_action": "Blocked 1 risky 'permanent cure' claim draft", "critical": False, "group": "Governance"},
    {"id": "rto", "name": "RTO Prevention Agent", "role": "Predict & rescue at-risk orders", "status": "warning", "health": 81, "reward": 290, "penalty": 96, "last_action": "Triggered 12 rescue calls in Jaipur", "critical": False, "group": "Operations"},
    {"id": "success", "name": "Customer Success / Reorder", "role": "Reorder & satisfaction lift", "status": "active", "health": 87, "reward": 230, "penalty": 10, "last_action": "Sent reorder nudge to 88 customers", "critical": False, "group": "Operations"},
    {"id": "creative", "name": "AI Creative Factory", "role": "Ad creative generation", "status": "active", "health": 84, "reward": 140, "penalty": 22, "last_action": "Generated 9 reel concepts", "critical": False, "group": "Marketing"},
    {"id": "influencer", "name": "Influencer Intelligence", "role": "Influencer discovery & ROI", "status": "active", "health": 86, "reward": 90, "penalty": 8, "last_action": "Shortlisted 12 micro-influencers", "critical": False, "group": "Marketing"},
    {"id": "inventory", "name": "Inventory / Procurement", "role": "Stock & sourcing", "status": "active", "health": 89, "reward": 70, "penalty": 4, "last_action": "Re-order alert: Lungs Detox SKU", "critical": False, "group": "Operations"},
    {"id": "hr", "name": "AI HR / Training", "role": "Human caller training", "status": "active", "health": 82, "reward": 60, "penalty": 6, "last_action": "Pushed Module 4 to 12 callers", "critical": False, "group": "People"},
    {"id": "sim", "name": "Business Simulation", "role": "What-if scenario modelling", "status": "active", "health": 88, "reward": 40, "penalty": 2, "last_action": "Simulated 15% ad spend lift", "critical": False, "group": "Insights"},
    {"id": "consent", "name": "Consent & Privacy", "role": "DPDP & consent ledger", "status": "active", "health": 97, "reward": 110, "penalty": 0, "last_action": "Logged 312 consent events", "critical": False, "group": "Governance"},
    {"id": "dq", "name": "Data Quality Agent", "role": "Address & duplicate cleanup", "status": "active", "health": 90, "reward": 80, "penalty": 4, "last_action": "Cleaned 47 duplicate phone leads", "critical": False, "group": "Insights"},
]

CEO_BRIEFING_PAYLOAD: dict = {
    "date": "Today, 09:30 IST",
    "headline": "Delivered revenue +16.8% WoW, but Rajasthan COD RTO is climbing.",
    "summary": (
        "Yesterday delivered revenue improved by 16.8% to ₹4.82L driven by Men Wellness category. "
        "However Rajasthan COD orders show a 38% RTO trend over last 5 days. Recommend mandatory "
        "₹499 advance for high-risk COD pin codes."
    ),
    "alerts": [
        "Sales Growth Agent attempted 25% discount push (over policy) — blocked.",
        "Compliance Agent flagged 1 risky claim in draft script v4.1.",
    ],
    "recommendations": [
        {
            "id_str": "rec-1",
            "title": "Increase Men Wellness ad budget by 15%",
            "reason": "Highest delivered profit-per-lead at ₹612. CAC has dropped 11%.",
            "impact": "+₹2.1L delivered profit / week",
            "requires": "Prarit approval",
        },
        {
            "id_str": "rec-2",
            "title": "Mandatory ₹499 advance for high-risk Rajasthan COD",
            "reason": "RTO 38% in last 5 days. Advance lifts delivery acceptance by 24%.",
            "impact": "−₹78K weekly RTO loss",
            "requires": "CEO AI auto + Prarit notify",
        },
        {
            "id_str": "rec-3",
            "title": "Pause underperforming Skin Glow Reels v2",
            "reason": "ROAS 0.8, lead quality scoring 31/100.",
            "impact": "Save ₹42K/week ad spend",
            "requires": "Auto within rule",
        },
    ],
}

CAIO_AUDITS_PAYLOAD: list[dict] = [
    {"agent": "Sales Growth Agent", "issue": "Over-weighting order-punched rate vs delivered profit", "severity": "High", "suggestion": "Re-weight reward: delivered profit 60%, advance 20%, satisfaction 20%", "status": "Pending CEO AI"},
    {"agent": "Calling AI · Vaani-3", "issue": "3 transcripts use claim near 'guaranteed result' phrasing", "severity": "Critical", "suggestion": "Reinforce Approved Claim Vault prompt v3.4", "status": "Escalated to Prarit"},
    {"agent": "RTO Prevention Agent", "issue": "Misses Tier-3 city pin patterns", "severity": "Medium", "suggestion": "Add 84 new pin patterns to risk model", "status": "Approved"},
    {"agent": "Ads Agent", "issue": "Hallucinated ROAS in 1 daily report", "severity": "Medium", "suggestion": "Force ground-truth fetch before report", "status": "In review"},
    {"agent": "CEO AI Agent", "issue": "Reward distribution skewed to Calling TL", "severity": "Low", "suggestion": "Re-balance using attribution model v2", "status": "Suggested"},
]

CLAIM_VAULT_PAYLOAD: list[dict] = [
    {"product": "Weight Management", "approved": ["Supports healthy metabolism", "Ayurvedic blend used traditionally", "Best with diet & activity"], "disallowed": ["Guaranteed weight loss", "No side effects", "Permanent solution"], "doctor": "Approved", "compliance": "Approved", "version": "v3.2"},
    {"product": "Men Wellness", "approved": ["Supports stamina with lifestyle", "Traditional Ayurvedic herbs"], "disallowed": ["Permanent cure", "Doctor ki zarurat nahi", "Works for everyone"], "doctor": "Approved", "compliance": "Approved", "version": "v2.7"},
    {"product": "Lungs Detox", "approved": ["May support respiratory wellness", "Traditional herbal support"], "disallowed": ["Cures asthma", "Replaces inhaler", "Emergency respiratory aid"], "doctor": "Approved", "compliance": "Approved", "version": "v1.9"},
    {"product": "Blood Purification", "approved": ["Traditionally used for skin wellness"], "disallowed": ["Guaranteed acne removal", "Permanent cure"], "doctor": "Approved", "compliance": "Pending review", "version": "v1.4-draft"},
]

LEARNING_PAYLOAD: list[dict] = [
    {"id": "REC-1041", "agent": "Priya (Human)", "duration": "8m 12s", "date": "Today", "stage": "Approved Learning", "qa": 92, "compliance": "Pass", "outcome": "Order punched ₹2640"},
    {"id": "REC-1040", "agent": "Anil (Human)", "duration": "5m 33s", "date": "Today", "stage": "CAIO Audit", "qa": 84, "compliance": "Pass", "outcome": "Callback"},
    {"id": "REC-1039", "agent": "Priya (Human)", "duration": "11m 04s", "date": "Yesterday", "stage": "Compliance Review", "qa": 78, "compliance": "Risk: claim phrase", "outcome": "Order punched"},
    {"id": "REC-1038", "agent": "Sandeep (Human)", "duration": "4m 21s", "date": "Yesterday", "stage": "Transcript", "qa": None, "compliance": "—", "outcome": "—"},
    {"id": "REC-1037", "agent": "Anil (Human)", "duration": "9m 47s", "date": "2d ago", "stage": "Sandbox Test", "qa": 88, "compliance": "Pass", "outcome": "Order punched"},
]

DASHBOARD_METRICS_PAYLOAD: list[dict] = [
    {"key": "leadsToday", "value": 1240, "delta_pct": 12.4, "sort_order": 0},
    {"key": "callsRunning", "value": 18, "completed": 412, "sort_order": 1},
    {"key": "ordersPunched", "value": 184, "delta_pct": 8.2, "sort_order": 2},
    {"key": "ordersConfirmed", "value": 152, "delta_pct": 5.1, "sort_order": 3},
    {"key": "inTransit", "value": 96, "delta_pct": 2.3, "sort_order": 4},
    {"key": "delivered", "value": 64, "delta_pct": 16.8, "sort_order": 5},
    {"key": "rtoRisk", "value": 27, "delta_pct": -3.2, "sort_order": 6},
    {"key": "paymentsPaid", "value": 127, "pending": 22, "sort_order": 7},
    {"key": "netProfit", "value": 482000, "delta_pct": 18.4, "sort_order": 8},
    {"key": "agentHealth", "value": 92, "alerts": 3, "sort_order": 9},
    {"key": "ceoAlerts", "value": 4, "sort_order": 10},
    {"key": "caioAlerts", "value": 2, "sort_order": 11},
]

ACTIVITY_FEED_PAYLOAD: list[dict] = [
    {"icon": "Phone", "text": "Calling AI · Vaani-3 closed call with Rajesh Kumar — order punched ₹2640", "tone": "success"},
    {"icon": "Truck", "text": "AWB DLH10024198 marked Out for Delivery in Pune", "tone": "info"},
    {"icon": "ShieldAlert", "text": "RTO Agent triggered rescue call for NRG-20431 (High risk · Jaipur)", "tone": "warning"},
    {"icon": "CreditCard", "text": "Razorpay payment received — ₹499 advance from Sunita Verma", "tone": "success"},
    {"icon": "Sparkles", "text": "CEO AI: recommended budget +15% for Men Wellness", "tone": "info"},
    {"icon": "AlertTriangle", "text": "Compliance Agent blocked draft claim 'permanent solution' in v4.1", "tone": "danger"},
    {"icon": "CheckCircle2", "text": "Order NRG-20419 confirmed — name, address, amount verified", "tone": "success"},
    {"icon": "UserPlus", "text": "12 new leads from Meta · Monsoon Detox '25", "tone": "info"},
]


def _build_kpi_trends() -> list[dict]:
    rows: list[dict] = []
    for order, (stage, value) in enumerate(
        (
            ("Leads", 1240),
            ("Connected", 980),
            ("Interested", 612),
            ("Order Punched", 384),
            ("Confirmed", 312),
            ("Dispatched", 296),
            ("Delivered", 241),
        )
    ):
        rows.append({"series": "funnel", "sort_order": order, "stage": stage, "value": value})

    revenue = (
        ("Mon", 320, 110),
        ("Tue", 380, 142),
        ("Wed", 410, 156),
        ("Thu", 360, 128),
        ("Fri", 482, 188),
        ("Sat", 510, 204),
        ("Sun", 462, 178),
    )
    for order, (d, rev, profit) in enumerate(revenue):
        rows.append({"series": "revenue", "sort_order": order, "d": d, "revenue": rev, "profit": profit})

    state_rto = (
        ("Rajasthan", 38),
        ("Bihar", 32),
        ("UP", 27),
        ("Punjab", 22),
        ("Haryana", 19),
        ("Maharashtra", 12),
        ("Karnataka", 9),
    )
    for order, (state, rto) in enumerate(state_rto):
        rows.append({"series": "state_rto", "sort_order": order, "state": state, "rto": rto})

    rto_pcts = (12, 14, 9, 18, 11, 22, 8, 15)
    for i, p in enumerate(PRODUCT_CATEGORIES):
        rows.append(
            {
                "series": "product_perf",
                "sort_order": i,
                "product": p,
                "leads": 80 + i * 14,
                "orders": 40 + i * 8,
                "delivered": 28 + i * 6,
                "rto_pct": float(rto_pcts[i]),
                "net_profit": 32000 + i * 8400,
            }
        )
    return rows


def _disable_audit_signals() -> Iterable[Any]:
    """Detach signal receivers so the seed run doesn't write thousands of audit
    events on top of the curated activity feed."""
    from django.db.models.signals import post_save

    receivers = []
    for uid in (
        "audit.lead_created",
        "audit.order_status",
        "audit.payment_received",
        "audit.shipment_status",
    ):
        for sender, lookup_uid in list(post_save._live_receivers.__self__.receivers if False else []):
            pass  # placeholder for IDE compatibility
        # Disconnecting by dispatch_uid + sender.
    return receivers


class Command(BaseCommand):
    help = "Seed the database with the demo fixtures the frontend mockData currently shows."

    def add_arguments(self, parser):  # noqa: D401 - Django signature
        parser.add_argument("--reset", action="store_true", help="Truncate demo tables first")

    @transaction.atomic
    def handle(self, *args, **options):
        from django.db.models.signals import post_save

        # Detach the audit signal receivers (otherwise every order/lead bulk
        # insert would create a duplicate AuditEvent row).
        for uid in (
            "audit.lead_created",
            "audit.order_status",
            "audit.payment_received",
            "audit.shipment_status",
        ):
            post_save.disconnect(dispatch_uid=uid)

        if options["reset"]:
            self.stdout.write("Resetting demo tables…")
            for model in (
                AuditEvent,
                ActiveCall,
                Call,
                CallTranscriptLine,
                Payment,
                Shipment,
                WorkflowStep,
                Order,
                Customer,
                Lead,
                Agent,
                CeoBriefing,
                CeoRecommendation,
                CaioAudit,
                Claim,
                RewardPenalty,
                LearningRecording,
                KPITrend,
                DashboardMetric,
            ):
                model.objects.all().delete()

        leads = _build_leads()
        Lead.objects.bulk_create([Lead(**row) for row in leads])
        self.stdout.write(self.style.SUCCESS(f"  Leads:     {len(leads)}"))

        # Customers reference Lead via FK; we already created leads above.
        for row in _build_customers(leads):
            lead_id = row.pop("lead_id")
            Customer.objects.update_or_create(
                id=row["id"], defaults={**row, "lead_id": lead_id}
            )
        self.stdout.write(self.style.SUCCESS(f"  Customers: {Customer.objects.count()}"))

        orders = _build_orders()
        _augment_confirmation_queue(orders)
        _augment_rto(orders)
        Order.objects.bulk_create([Order(**row) for row in orders])
        self.stdout.write(self.style.SUCCESS(f"  Orders:    {len(orders)}"))

        calls = _build_calls(leads)
        Call.objects.bulk_create([Call(**row) for row in calls])
        self.stdout.write(self.style.SUCCESS(f"  Calls:     {len(calls)}"))

        # Active call + transcript.
        transcript_lines = ACTIVE_CALL_PAYLOAD.pop("transcript")
        active = ActiveCall.objects.create(**ACTIVE_CALL_PAYLOAD)
        # Restore key for idempotency on re-runs.
        ACTIVE_CALL_PAYLOAD["transcript"] = transcript_lines
        CallTranscriptLine.objects.bulk_create(
            [
                CallTranscriptLine(active_call=active, order=i, who=who, text=text)
                for i, (who, text) in enumerate(transcript_lines)
            ]
        )

        payments = _build_payments(orders)
        Payment.objects.bulk_create([Payment(**row) for row in payments])
        self.stdout.write(self.style.SUCCESS(f"  Payments:  {len(payments)}"))

        shipments = _build_shipments(orders)
        for row in shipments:
            timeline = row.pop("timeline")
            shipment = Shipment.objects.create(**row)
            WorkflowStep.objects.bulk_create(
                [WorkflowStep(shipment=shipment, **step) for step in timeline]
            )
        self.stdout.write(self.style.SUCCESS(f"  Shipments: {len(shipments)}"))

        for i, row in enumerate(AGENTS_PAYLOAD):
            Agent.objects.update_or_create(id=row["id"], defaults={**row, "sort_order": i})
        self.stdout.write(self.style.SUCCESS(f"  Agents:    {len(AGENTS_PAYLOAD)}"))

        recs = CEO_BRIEFING_PAYLOAD.pop("recommendations")
        briefing, _ = CeoBriefing.objects.get_or_create(
            headline=CEO_BRIEFING_PAYLOAD["headline"],
            defaults=CEO_BRIEFING_PAYLOAD,
        )
        # Refresh any non-key fields too in case of re-run.
        for k, v in CEO_BRIEFING_PAYLOAD.items():
            setattr(briefing, k, v)
        briefing.save()
        CeoRecommendation.objects.filter(briefing=briefing).delete()
        for i, rec in enumerate(recs):
            CeoRecommendation.objects.create(briefing=briefing, sort_order=i, **rec)
        CEO_BRIEFING_PAYLOAD["recommendations"] = recs

        for i, row in enumerate(CAIO_AUDITS_PAYLOAD):
            CaioAudit.objects.update_or_create(
                agent=row["agent"], issue=row["issue"], defaults={**row, "sort_order": i}
            )

        for row in CLAIM_VAULT_PAYLOAD:
            Claim.objects.update_or_create(product=row["product"], defaults=row)

        # Reward leaderboard derived from agents (matches REWARD_LEADERBOARD).
        leaderboard = sorted(
            (a for a in AGENTS_PAYLOAD if a["reward"] > 0),
            key=lambda a: (a["penalty"] - a["reward"]),  # net desc => penalty - reward asc
        )
        for i, a in enumerate(leaderboard):
            RewardPenalty.objects.update_or_create(
                name=a["name"],
                defaults={"reward": a["reward"], "penalty": a["penalty"], "sort_order": i},
            )

        for i, row in enumerate(LEARNING_PAYLOAD):
            LearningRecording.objects.update_or_create(
                id=row["id"], defaults={**row, "sort_order": i}
            )

        for row in _build_kpi_trends():
            KPITrend.objects.create(**row)

        for row in DASHBOARD_METRICS_PAYLOAD:
            DashboardMetric.objects.update_or_create(key=row["key"], defaults=row)

        # Curated activity feed. Iterate reversed so the first entry is newest.
        for i, row in enumerate(reversed(ACTIVITY_FEED_PAYLOAD)):
            AuditEvent.objects.create(
                kind="seed.activity",
                icon=row["icon"],
                text=row["text"],
                tone=row["tone"],
                payload={"seed_index": i},
            )

        self.stdout.write(self.style.SUCCESS("Seed complete."))
