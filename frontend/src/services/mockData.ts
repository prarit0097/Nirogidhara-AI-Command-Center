/**
 * Centralized mock data for Nirogidhara AI Command Center.
 * Replace import sites with real API calls when Django backend is wired up.
 * Endpoint contracts are documented in src/services/api.ts.
 */

export type LeadStatus =
  | "New"
  | "AI Calling Started"
  | "Interested"
  | "Callback Required"
  | "Payment Link Sent"
  | "Order Punched"
  | "Not Interested"
  | "Invalid";

export type OrderStage =
  | "New Lead"
  | "Interested"
  | "Payment Link Sent"
  | "Order Punched"
  | "Confirmation Pending"
  | "Confirmed"
  | "Dispatched"
  | "Out for Delivery"
  | "Delivered"
  | "RTO";

export const PRODUCT_CATEGORIES = [
  "Weight Management",
  "Blood Purification",
  "Men Wellness",
  "Women Wellness",
  "Immunity Booster",
  "Lungs Detox",
  "Body Detox",
  "Joint Care",
] as const;

export const STATES = [
  "Maharashtra", "Delhi", "Uttar Pradesh", "Rajasthan", "Gujarat",
  "Madhya Pradesh", "Bihar", "Karnataka", "Tamil Nadu", "Punjab",
  "Haryana", "West Bengal", "Telangana", "Odisha",
];

const NAMES = [
  "Rajesh Kumar", "Sunita Verma", "Amit Sharma", "Priya Singh", "Vikas Yadav",
  "Neha Gupta", "Mohammed Aslam", "Anita Devi", "Suresh Patel", "Kavita Joshi",
  "Arun Mehta", "Pooja Rani", "Dinesh Choudhary", "Manju Bisht", "Ravi Shankar",
  "Lakshmi Nair", "Sandeep Rathore", "Geeta Kumari", "Vivek Tiwari", "Shilpa Reddy",
  "Karan Malhotra", "Asha Pandey", "Naveen Kashyap", "Bharti Saxena", "Hemant Goswami",
  "Renu Bansal", "Tushar Khanna", "Sushma Iyer", "Pankaj Mishra", "Deepa Bhatia",
];

const CITIES: Record<string, string[]> = {
  Maharashtra: ["Mumbai", "Pune", "Nagpur", "Nashik"],
  Delhi: ["New Delhi", "Dwarka", "Rohini"],
  "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra"],
  Rajasthan: ["Jaipur", "Jodhpur", "Udaipur", "Kota"],
  Gujarat: ["Ahmedabad", "Surat", "Vadodara"],
  "Madhya Pradesh": ["Indore", "Bhopal", "Gwalior"],
  Bihar: ["Patna", "Gaya"],
  Karnataka: ["Bengaluru", "Mysuru"],
  "Tamil Nadu": ["Chennai", "Coimbatore"],
  Punjab: ["Ludhiana", "Amritsar"],
  Haryana: ["Gurgaon", "Faridabad"],
  "West Bengal": ["Kolkata", "Howrah"],
  Telangana: ["Hyderabad"],
  Odisha: ["Bhubaneswar", "Cuttack"],
};

const SOURCES = ["Meta Ads", "Inbound Call", "Google Ads", "Influencer", "WhatsApp", "Referral"];
const CAMPAIGNS = ["Monsoon Detox '25", "Men Vitality Push", "Skin Glow Reels", "Immunity Winter", "Pollution Shield", "Joint Relief 30+"];
const LANGUAGES = ["Hindi", "Hinglish", "English", "Marathi", "Punjabi", "Bengali"];

function pick<T>(arr: readonly T[], i: number) { return arr[i % arr.length]; }
function rand(seed: number) { return ((seed * 9301 + 49297) % 233280) / 233280; }
function phone(seed: number) {
  const n = Math.floor(rand(seed) * 9000000 + 1000000);
  return `+91 9${(seed % 10)}${(seed * 7) % 10}${String(n).slice(0, 7)}`;
}

/* ---------------- Leads ---------------- */
const LEAD_STATUSES: LeadStatus[] = [
  "New", "AI Calling Started", "Interested", "Callback Required",
  "Payment Link Sent", "Order Punched", "Not Interested", "Invalid",
];

export const LEADS = Array.from({ length: 42 }).map((_, i) => {
  const state = pick(STATES, i);
  const cities = CITIES[state] || ["—"];
  return {
    id: `LD-${10234 + i}`,
    name: pick(NAMES, i),
    phone: phone(i + 11),
    state,
    city: pick(cities, i),
    language: pick(LANGUAGES, i + 1),
    source: pick(SOURCES, i + 2),
    campaign: pick(CAMPAIGNS, i + 3),
    productInterest: pick(PRODUCT_CATEGORIES, i + 1),
    status: pick(LEAD_STATUSES, i),
    quality: ["Hot", "Warm", "Cold"][i % 3] as "Hot" | "Warm" | "Cold",
    qualityScore: 40 + Math.floor(rand(i + 5) * 60),
    assignee: i % 3 === 0 ? "Calling AI · Vaani-3" : pick(["Priya (Human)", "Anil (Human)", "Calling AI · Vaani-2"], i),
    duplicate: i % 11 === 0,
    createdAt: `${(i % 23).toString().padStart(2, "0")} min ago`,
  };
});

/* ---------------- Customers ---------------- */
export const CUSTOMERS = LEADS.slice(0, 24).map((l, i) => ({
  id: `CU-${5000 + i}`,
  leadId: l.id,
  name: l.name,
  phone: l.phone,
  state: l.state,
  city: l.city,
  language: l.language,
  productInterest: l.productInterest,
  diseaseCategory: pick(["Obesity", "Acne / Skin", "Low Stamina", "PCOS support", "Frequent cold", "Smoker's lungs", "Joint pain"], i),
  lifestyleNotes: pick([
    "Sedentary, eats outside food 4x/week",
    "Night shift worker, sleeps 5 hrs",
    "Vegetarian, walks daily",
    "Diabetic family history",
    "Smokes 5/day, urban polluted area",
  ], i),
  objections: pick([
    ["Too expensive", "Tried similar before"],
    ["Wants doctor consult"],
    ["Wife decides"],
    ["Wants COD"],
  ], i),
  aiSummary: "Polite, language-clear caller. Mid-income, COD-leaning. Responded well to lifestyle questions and accepted ₹499 advance after 12% discount.",
  riskFlags: i % 5 === 0 ? ["Address pin mismatch"] : [],
  reorderProbability: 30 + ((i * 7) % 65),
  satisfaction: 3 + (i % 3),
  consent: { call: true, whatsapp: i % 2 === 0, marketing: i % 3 === 0 },
}));

/* ---------------- Orders ---------------- */
const STAGES: OrderStage[] = [
  "New Lead", "Interested", "Payment Link Sent", "Order Punched",
  "Confirmation Pending", "Confirmed", "Dispatched", "Out for Delivery",
  "Delivered", "RTO",
];

export const ORDERS = Array.from({ length: 60 }).map((_, i) => {
  const state = pick(STATES, i + 4);
  const baseAmount = 3000;
  const discountPct = pick([0, 10, 12, 15, 20, 25, 30], i);
  const amount = Math.round(baseAmount * (1 - discountPct / 100));
  const advancePaid = i % 3 !== 0;
  return {
    id: `NRG-${20410 + i}`,
    customerName: pick(NAMES, i + 4),
    phone: phone(i + 70),
    product: pick(PRODUCT_CATEGORIES, i),
    quantity: 1 + (i % 2),
    amount,
    discountPct,
    advancePaid,
    advanceAmount: advancePaid ? 499 : 0,
    paymentStatus: pick(["Paid", "Partial", "Pending", "Failed"], i),
    state,
    city: pick(CITIES[state] || ["—"], i),
    rtoRisk: ["Low", "Medium", "High"][(i + Math.floor(discountPct / 10)) % 3] as "Low" | "Medium" | "High",
    rtoScore: 10 + ((i * 13) % 85),
    agent: pick(["Calling AI · Vaani-3", "Priya (Human)", "Anil (Human)", "Calling AI · Vaani-2"], i),
    stage: STAGES[i % STAGES.length],
    awb: i > 20 ? `DLH${1000000 + i * 13}` : null,
    ageHours: (i * 3) % 72,
    createdAt: `${i % 14}d ago`,
  };
});

/* ---------------- Calls ---------------- */
export const CALLS = Array.from({ length: 18 }).map((_, i) => ({
  id: `CL-${8400 + i}`,
  leadId: LEADS[i % LEADS.length].id,
  customer: LEADS[i % LEADS.length].name,
  phone: LEADS[i % LEADS.length].phone,
  agent: i % 2 === 0 ? "Calling AI · Vaani-3" : pick(["Priya (Human)", "Anil (Human)"], i),
  language: pick(LANGUAGES, i),
  duration: `${2 + (i % 7)}m ${(i * 11) % 60}s`,
  status: pick(["Live", "Queued", "Completed", "Missed"], i),
  sentiment: pick(["Positive", "Neutral", "Hesitant", "Annoyed"], i),
  scriptCompliance: 80 + (i % 20),
  paymentLinkSent: i % 4 === 0,
}));

export const ACTIVE_CALL = {
  id: "CL-LIVE-001",
  customer: "Rajesh Kumar",
  phone: "+91 9*****8421",
  agent: "Calling AI · Vaani-3",
  language: "Hinglish",
  duration: "03:42",
  stage: "Objection Handling",
  sentiment: "Hesitant",
  scriptCompliance: 96,
  transcript: [
    { who: "AI", text: "Namaste sir, main Nirogidhara se Vaani bol rahi hoon. 2 minute baat kar sakte hain?" },
    { who: "Customer", text: "Haan bolo, lekin jaldi." },
    { who: "AI", text: "Sir aapne weight management ke liye enquiry ki thi — aap ka kaam mostly sitting wala hai?" },
    { who: "Customer", text: "Haan office job hai. Lekin pehle bhi try kiya, kuch nahi hua." },
    { who: "AI", text: "Samajh sakti hoon. Hamara product Approved Claim Vault ke andar Ayurvedic blend hai. Result lifestyle ke saath better hota hai." },
    { who: "Customer", text: "Price kya hai?" },
    { who: "AI", text: "30 capsules ka pack ₹3000 hai. Aaj advance ₹499 dene par 12% off mil jayega." },
  ],
  detectedObjections: ["Price concern", "Past failure"],
  approvedClaimsUsed: ["Lifestyle support claim v3.2", "Ayurvedic blend description"],
};

/* ---------------- Confirmation queue ---------------- */
export const CONFIRMATION_QUEUE = ORDERS
  .filter((o) => o.stage === "Confirmation Pending" || o.stage === "Order Punched")
  .slice(0, 10)
  .map((o, i) => ({
    ...o,
    hoursWaiting: 6 + (i * 3),
    addressConfidence: 50 + (i * 4) % 50,
    checklist: { name: false, address: false, product: false, amount: false, intent: false },
  }));

/* ---------------- Payments ---------------- */
export const PAYMENTS = Array.from({ length: 30 }).map((_, i) => ({
  id: `PAY-${30100 + i}`,
  orderId: ORDERS[i % ORDERS.length].id,
  customer: ORDERS[i % ORDERS.length].customerName,
  amount: ORDERS[i % ORDERS.length].amount,
  gateway: i % 2 === 0 ? "Razorpay" : "PayU",
  status: pick(["Paid", "Pending", "Failed", "Refunded"], i),
  type: pick(["Advance", "Full"], i),
  time: `${i % 23}:${((i * 7) % 60).toString().padStart(2, "0")}`,
}));

/* ---------------- Shipments ---------------- */
export const SHIPMENTS = ORDERS
  .filter((o) => o.awb)
  .map((o, i) => ({
    awb: o.awb!,
    orderId: o.id,
    customer: o.customerName,
    state: o.state,
    city: o.city,
    status: pick(["Pickup Scheduled", "In Transit", "Out for Delivery", "Delivered", "RTO Initiated"], i),
    eta: `${1 + (i % 5)} days`,
    courier: "Delhivery",
    timeline: [
      { step: "AWB Generated", at: "Day 0", done: true },
      { step: "Pickup Scheduled", at: "Day 0", done: true },
      { step: "In Transit", at: "Day 1", done: i > 1 },
      { step: "Out for Delivery", at: "Day 3", done: i > 4 },
      { step: "Delivered / RTO", at: "Day 4", done: i > 6 },
    ],
  }));

/* ---------------- RTO risk ---------------- */
export const RTO_RISK_ORDERS = ORDERS
  .filter((o) => o.rtoRisk !== "Low")
  .slice(0, 14)
  .map((o, i) => ({
    ...o,
    riskReasons: pick([
      ["No advance payment", "Price objection"],
      ["Weak confirmation", "Address issue"],
      ["High-risk region", "No response"],
      ["Repeated COD failure"],
    ], i),
    rescueStatus: pick(["Pending", "Rescue Call Done", "Convinced", "Returning"], i),
  }));

/* ---------------- AI Agents ---------------- */
export const AGENTS = [
  { id: "ceo", name: "CEO AI Agent", role: "Business command & execution approval", status: "active", health: 96, reward: 1240, penalty: 86, lastAction: "Approved 12% discount cap for Rajasthan COD", critical: false, group: "Command" },
  { id: "caio", name: "CAIO Agent", role: "Governance, audit & training only — never executes", status: "warning", health: 88, reward: 0, penalty: 0, lastAction: "Flagged Sales Growth Agent over-weighting", critical: true, group: "Governance" },
  { id: "ads", name: "Ads Agent", role: "Meta/Google performance & scaling", status: "active", health: 91, reward: 320, penalty: 18, lastAction: "Paused 2 underperforming creatives", critical: false, group: "Marketing" },
  { id: "marketing", name: "Marketing Agent", role: "Funnel & creative orchestration", status: "active", health: 89, reward: 210, penalty: 12, lastAction: "Drafted 4 hook variants for Men Vitality", critical: false, group: "Marketing" },
  { id: "sales", name: "Sales Growth Agent", role: "Conversion strategy & price/discount", status: "warning", health: 74, reward: 410, penalty: 122, lastAction: "Suggested 25% discount campaign (over rule)", critical: false, group: "Sales" },
  { id: "calling-tl", name: "Calling Agent Team Leader", role: "Live AI call orchestration", status: "active", health: 93, reward: 540, penalty: 44, lastAction: "Re-routed 18 calls to Vaani-3 voice", critical: false, group: "Sales" },
  { id: "calling-qa", name: "Calling Quality Analyst", role: "Script compliance & QA", status: "active", health: 95, reward: 220, penalty: 8, lastAction: "QA scored 142 calls today", critical: false, group: "Quality" },
  { id: "data", name: "Data Analyst Agent", role: "Cross-team insight generation", status: "active", health: 90, reward: 180, penalty: 6, lastAction: "Built funnel cohort for Q3", critical: false, group: "Insights" },
  { id: "cfo", name: "CFO AI Agent", role: "Net delivered profit & cash flow", status: "active", health: 92, reward: 360, penalty: 14, lastAction: "Profit reconciliation for last 7 days", critical: false, group: "Finance" },
  { id: "compliance", name: "Compliance & Medical Safety", role: "Claim Vault enforcement", status: "active", health: 98, reward: 410, penalty: 2, lastAction: "Blocked 1 risky 'permanent cure' claim draft", critical: false, group: "Governance" },
  { id: "rto", name: "RTO Prevention Agent", role: "Predict & rescue at-risk orders", status: "warning", health: 81, reward: 290, penalty: 96, lastAction: "Triggered 12 rescue calls in Jaipur", critical: false, group: "Operations" },
  { id: "success", name: "Customer Success / Reorder", role: "Reorder & satisfaction lift", status: "active", health: 87, reward: 230, penalty: 10, lastAction: "Sent reorder nudge to 88 customers", critical: false, group: "Operations" },
  { id: "creative", name: "AI Creative Factory", role: "Ad creative generation", status: "active", health: 84, reward: 140, penalty: 22, lastAction: "Generated 9 reel concepts", critical: false, group: "Marketing" },
  { id: "influencer", name: "Influencer Intelligence", role: "Influencer discovery & ROI", status: "active", health: 86, reward: 90, penalty: 8, lastAction: "Shortlisted 12 micro-influencers", critical: false, group: "Marketing" },
  { id: "inventory", name: "Inventory / Procurement", role: "Stock & sourcing", status: "active", health: 89, reward: 70, penalty: 4, lastAction: "Re-order alert: Lungs Detox SKU", critical: false, group: "Operations" },
  { id: "hr", name: "AI HR / Training", role: "Human caller training", status: "active", health: 82, reward: 60, penalty: 6, lastAction: "Pushed Module 4 to 12 callers", critical: false, group: "People" },
  { id: "sim", name: "Business Simulation", role: "What-if scenario modelling", status: "active", health: 88, reward: 40, penalty: 2, lastAction: "Simulated 15% ad spend lift", critical: false, group: "Insights" },
  { id: "consent", name: "Consent & Privacy", role: "DPDP & consent ledger", status: "active", health: 97, reward: 110, penalty: 0, lastAction: "Logged 312 consent events", critical: false, group: "Governance" },
  { id: "dq", name: "Data Quality Agent", role: "Address & duplicate cleanup", status: "active", health: 90, reward: 80, penalty: 4, lastAction: "Cleaned 47 duplicate phone leads", critical: false, group: "Insights" },
] as const;

/* ---------------- CEO AI briefing ---------------- */
export const CEO_BRIEFING = {
  date: "Today, 09:30 IST",
  headline: "Delivered revenue +16.8% WoW, but Rajasthan COD RTO is climbing.",
  summary:
    "Yesterday delivered revenue improved by 16.8% to ₹4.82L driven by Men Wellness category. However Rajasthan COD orders show a 38% RTO trend over last 5 days. Recommend mandatory ₹499 advance for high-risk COD pin codes.",
  recommendations: [
    {
      id: "rec-1",
      title: "Increase Men Wellness ad budget by 15%",
      reason: "Highest delivered profit-per-lead at ₹612. CAC has dropped 11%.",
      impact: "+₹2.1L delivered profit / week",
      requires: "Prarit approval",
    },
    {
      id: "rec-2",
      title: "Mandatory ₹499 advance for high-risk Rajasthan COD",
      reason: "RTO 38% in last 5 days. Advance lifts delivery acceptance by 24%.",
      impact: "−₹78K weekly RTO loss",
      requires: "CEO AI auto + Prarit notify",
    },
    {
      id: "rec-3",
      title: "Pause underperforming Skin Glow Reels v2",
      reason: "ROAS 0.8, lead quality scoring 31/100.",
      impact: "Save ₹42K/week ad spend",
      requires: "Auto within rule",
    },
  ],
  alerts: [
    "Sales Growth Agent attempted 25% discount push (over policy) — blocked.",
    "Compliance Agent flagged 1 risky claim in draft script v4.1.",
  ],
};

/* ---------------- CAIO audits ---------------- */
export const CAIO_AUDITS = [
  { agent: "Sales Growth Agent", issue: "Over-weighting order-punched rate vs delivered profit", severity: "High", suggestion: "Re-weight reward: delivered profit 60%, advance 20%, satisfaction 20%", status: "Pending CEO AI" },
  { agent: "Calling AI · Vaani-3", issue: "3 transcripts use claim near 'guaranteed result' phrasing", severity: "Critical", suggestion: "Reinforce Approved Claim Vault prompt v3.4", status: "Escalated to Prarit" },
  { agent: "RTO Prevention Agent", issue: "Misses Tier-3 city pin patterns", severity: "Medium", suggestion: "Add 84 new pin patterns to risk model", status: "Approved" },
  { agent: "Ads Agent", issue: "Hallucinated ROAS in 1 daily report", severity: "Medium", suggestion: "Force ground-truth fetch before report", status: "In review" },
  { agent: "CEO AI Agent", issue: "Reward distribution skewed to Calling TL", severity: "Low", suggestion: "Re-balance using attribution model v2", status: "Suggested" },
];

/* ---------------- Reward / Penalty ---------------- */
export const REWARD_LEADERBOARD = AGENTS
  .filter((a) => a.reward > 0)
  .map((a) => ({
    name: a.name,
    reward: a.reward,
    penalty: a.penalty,
    net: a.reward - a.penalty,
    agentId: a.id,
    agentType: a.group?.toLowerCase?.() ?? "",
    rewardedOrders: Math.max(0, Math.round(a.reward / 30)),
    penalizedOrders: Math.max(0, Math.round(a.penalty / 30)),
    lastCalculatedAt: null,
  }))
  .sort((a, b) => b.net - a.net);

/* Phase 4B per-order scoring events (mock fallback). Engine writes camelCase
 * keys; frontend renders them verbatim. */
export const REWARD_PENALTY_EVENTS = [
  {
    id: "phase4b_engine:NRG-20410:ceo:reward",
    orderId: "NRG-20410",
    orderIdSnapshot: "NRG-20410",
    agentId: "ceo",
    agentName: "CEO AI Agent",
    agentType: "command",
    eventType: "reward",
    rewardScore: 70,
    penaltyScore: 0,
    netScore: 70,
    components: [
      { code: "ceo_net_accountability_reward", label: "CEO AI net accountability (delivered order)", points: 70 },
    ],
    missingData: ["customer_satisfaction", "reorder_potential"],
    attribution: { rule: "ceo_ai_net_accountability", stage: "Delivered" },
    source: "phase4b_engine",
    triggeredBy: "manual-sweep",
    calculatedAt: new Date().toISOString(),
    metadata: { stage: "Delivered", rto_risk: "Low", discount_pct: 12 },
    uniqueKey: "phase4b_engine:NRG-20410:ceo:reward",
  },
  {
    id: "phase4b_engine:NRG-20431:ceo:penalty",
    orderId: "NRG-20431",
    orderIdSnapshot: "NRG-20431",
    agentId: "ceo",
    agentName: "CEO AI Agent",
    agentType: "command",
    eventType: "penalty",
    rewardScore: 0,
    penaltyScore: 50,
    netScore: -50,
    components: [
      { code: "ceo_net_accountability_penalty", label: "CEO AI net accountability (failed order)", points: -50 },
    ],
    missingData: ["customer_satisfaction", "reorder_potential"],
    attribution: { rule: "ceo_ai_net_accountability", stage: "RTO" },
    source: "phase4b_engine",
    triggeredBy: "manual-sweep",
    calculatedAt: new Date().toISOString(),
    metadata: { stage: "RTO", rto_risk: "High", discount_pct: 22 },
    uniqueKey: "phase4b_engine:NRG-20431:ceo:penalty",
  },
  {
    id: "phase4b_engine:NRG-20431:rto:penalty",
    orderId: "NRG-20431",
    orderIdSnapshot: "NRG-20431",
    agentId: "rto",
    agentName: "RTO Prevention Agent",
    agentType: "operations",
    eventType: "penalty",
    rewardScore: 0,
    penaltyScore: 30,
    netScore: -30,
    components: [
      { code: "rto_after_dispatch", label: "Order RTO after dispatch", points: -30 },
    ],
    missingData: [],
    attribution: { rule: "phase4b_failed_attribution", agent_id: "rto" },
    source: "phase4b_engine",
    triggeredBy: "manual-sweep",
    calculatedAt: new Date().toISOString(),
    metadata: { stage: "RTO", rto_risk: "High", discount_pct: 22 },
    uniqueKey: "phase4b_engine:NRG-20431:rto:penalty",
  },
] as const;

/* Phase 4C — Approval Matrix Middleware mock fixtures. */
export const APPROVAL_REQUESTS = [
  {
    id: "APR-90001",
    action: "discount.11_to_20",
    mode: "approval_required",
    approver: "admin",
    status: "pending",
    requestedBy: "ops",
    requestedByAgent: "",
    targetApp: "orders",
    targetModel: "Order",
    targetObjectId: "NRG-20410",
    proposedPayload: { discount: 18, reason: "VIP customer" },
    policySnapshot: {
      action: "discount.11_to_20",
      approver: "admin",
      mode: "approval_required",
    },
    reason: "VIP customer — Mumbai",
    decisionNote: "",
    decidedBy: "",
    decidedAt: null,
    expiresAt: null,
    createdAt: new Date(Date.now() - 90 * 60_000).toISOString(),
    updatedAt: new Date(Date.now() - 90 * 60_000).toISOString(),
    metadata: { actor_role: "operations" },
    decisionLogs: [],
  },
  {
    id: "APR-90002",
    action: "discount.above_20",
    mode: "director_override",
    approver: "director",
    status: "pending",
    requestedBy: "admin_user",
    requestedByAgent: "",
    targetApp: "orders",
    targetModel: "Order",
    targetObjectId: "NRG-20431",
    proposedPayload: { discount: 25, reason: "festival promo" },
    policySnapshot: {
      action: "discount.above_20",
      approver: "director",
      mode: "director_override",
    },
    reason: "Festival weekend",
    decisionNote: "",
    decidedBy: "",
    decidedAt: null,
    expiresAt: null,
    createdAt: new Date(Date.now() - 30 * 60_000).toISOString(),
    updatedAt: new Date(Date.now() - 30 * 60_000).toISOString(),
    metadata: { actor_role: "admin" },
    decisionLogs: [],
  },
  {
    id: "APR-90003",
    action: "complaint.medical_emergency",
    mode: "human_escalation",
    approver: "human",
    status: "escalated",
    requestedBy: "ops",
    requestedByAgent: "calling-tl",
    targetApp: "calls",
    targetModel: "Call",
    targetObjectId: "CL-LIVE-014",
    proposedPayload: { transcript_excerpt: "..." },
    policySnapshot: {
      action: "complaint.medical_emergency",
      approver: "human",
      mode: "human_escalation",
    },
    reason: "Customer reported chest pain",
    decisionNote: "",
    decidedBy: "",
    decidedAt: null,
    expiresAt: null,
    createdAt: new Date(Date.now() - 12 * 60_000).toISOString(),
    updatedAt: new Date(Date.now() - 12 * 60_000).toISOString(),
    metadata: { actor_role: "operations", actor_agent: "calling-tl" },
    decisionLogs: [],
  },
  {
    id: "APR-90004",
    action: "payment.link.advance_499",
    mode: "auto",
    approver: "auto",
    status: "auto_approved",
    requestedBy: "ops",
    requestedByAgent: "",
    targetApp: "payments",
    targetModel: "Order",
    targetObjectId: "NRG-20415",
    proposedPayload: { orderId: "NRG-20415", amount: 499, type: "Advance" },
    policySnapshot: {
      action: "payment.link.advance_499",
      approver: "auto",
      mode: "auto",
    },
    reason: "auto-approved by approval matrix",
    decisionNote: "",
    decidedBy: "",
    decidedAt: null,
    expiresAt: null,
    createdAt: new Date(Date.now() - 240 * 60_000).toISOString(),
    updatedAt: new Date(Date.now() - 240 * 60_000).toISOString(),
    metadata: { actor_role: "operations" },
    decisionLogs: [],
  },
] as const;

export const REWARD_PENALTY_SUMMARY = {
  evaluatedOrders: 2,
  totalReward: 70,
  totalPenalty: 80,
  netScore: -10,
  lastSweepAt: null,
  lastSweepPayload: null,
  missingDataWarnings: [
    "NRG-20410:customer_satisfaction",
    "NRG-20410:reorder_potential",
    "NRG-20431:customer_satisfaction",
  ],
  agentLeaderboard: REWARD_LEADERBOARD,
};

/* ---------------- Claim Vault ---------------- */
export const CLAIM_VAULT = [
  { product: "Weight Management", approved: ["Supports healthy metabolism", "Ayurvedic blend used traditionally", "Best with diet & activity"], disallowed: ["Guaranteed weight loss", "No side effects", "Permanent solution"], doctor: "Approved", compliance: "Approved", version: "v3.2" },
  { product: "Men Wellness", approved: ["Supports stamina with lifestyle", "Traditional Ayurvedic herbs"], disallowed: ["Permanent cure", "Doctor ki zarurat nahi", "Works for everyone"], doctor: "Approved", compliance: "Approved", version: "v2.7" },
  { product: "Lungs Detox", approved: ["May support respiratory wellness", "Traditional herbal support"], disallowed: ["Cures asthma", "Replaces inhaler", "Emergency respiratory aid"], doctor: "Approved", compliance: "Approved", version: "v1.9" },
  { product: "Blood Purification", approved: ["Traditionally used for skin wellness"], disallowed: ["Guaranteed acne removal", "Permanent cure"], doctor: "Approved", compliance: "Pending review", version: "v1.4-draft" },
];

/* ---------------- Human Call Learning ---------------- */
export const LEARNING_RECORDINGS = [
  { id: "REC-1041", agent: "Priya (Human)", duration: "8m 12s", date: "Today", stage: "Approved Learning", qa: 92, compliance: "Pass", outcome: "Order punched ₹2640" },
  { id: "REC-1040", agent: "Anil (Human)", duration: "5m 33s", date: "Today", stage: "CAIO Audit", qa: 84, compliance: "Pass", outcome: "Callback" },
  { id: "REC-1039", agent: "Priya (Human)", duration: "11m 04s", date: "Yesterday", stage: "Compliance Review", qa: 78, compliance: "Risk: claim phrase", outcome: "Order punched" },
  { id: "REC-1038", agent: "Sandeep (Human)", duration: "4m 21s", date: "Yesterday", stage: "Transcript", qa: null, compliance: "—", outcome: "—" },
  { id: "REC-1037", agent: "Anil (Human)", duration: "9m 47s", date: "2d ago", stage: "Sandbox Test", qa: 88, compliance: "Pass", outcome: "Order punched" },
];

/* ---------------- Activity feed ---------------- */
export const ACTIVITY_FEED = [
  { time: "now", icon: "Phone", text: "Calling AI · Vaani-3 closed call with Rajesh Kumar — order punched ₹2640", tone: "success" },
  { time: "1m", icon: "Truck", text: "AWB DLH10024198 marked Out for Delivery in Pune", tone: "info" },
  { time: "2m", icon: "ShieldAlert", text: "RTO Agent triggered rescue call for NRG-20431 (High risk · Jaipur)", tone: "warning" },
  { time: "4m", icon: "CreditCard", text: "Razorpay payment received — ₹499 advance from Sunita Verma", tone: "success" },
  { time: "6m", icon: "Sparkles", text: "CEO AI: recommended budget +15% for Men Wellness", tone: "info" },
  { time: "9m", icon: "AlertTriangle", text: "Compliance Agent blocked draft claim 'permanent solution' in v4.1", tone: "danger" },
  { time: "12m", icon: "CheckCircle2", text: "Order NRG-20419 confirmed — name, address, amount verified", tone: "success" },
  { time: "15m", icon: "UserPlus", text: "12 new leads from Meta · Monsoon Detox '25", tone: "info" },
];

/* ---------------- Analytics ---------------- */
export const FUNNEL = [
  { stage: "Leads", value: 1240 },
  { stage: "Connected", value: 980 },
  { stage: "Interested", value: 612 },
  { stage: "Order Punched", value: 384 },
  { stage: "Confirmed", value: 312 },
  { stage: "Dispatched", value: 296 },
  { stage: "Delivered", value: 241 },
];

export const REVENUE_TREND = [
  { d: "Mon", revenue: 320, profit: 110 },
  { d: "Tue", revenue: 380, profit: 142 },
  { d: "Wed", revenue: 410, profit: 156 },
  { d: "Thu", revenue: 360, profit: 128 },
  { d: "Fri", revenue: 482, profit: 188 },
  { d: "Sat", revenue: 510, profit: 204 },
  { d: "Sun", revenue: 462, profit: 178 },
];

export const PRODUCT_PERFORMANCE = PRODUCT_CATEGORIES.map((p, i) => ({
  product: p,
  leads: 80 + i * 14,
  orders: 40 + i * 8,
  delivered: 28 + i * 6,
  rtoPct: [12, 14, 9, 18, 11, 22, 8, 15][i],
  netProfit: 32000 + i * 8400,
}));

export const STATE_RTO = [
  { state: "Rajasthan", rto: 38 },
  { state: "Bihar", rto: 32 },
  { state: "UP", rto: 27 },
  { state: "Punjab", rto: 22 },
  { state: "Haryana", rto: 19 },
  { state: "Maharashtra", rto: 12 },
  { state: "Karnataka", rto: 9 },
];

/* ---------------- Settings ---------------- */
export const APPROVAL_MATRIX = [
  { action: "Lead call", policy: "Auto", approver: "—" },
  { action: "Payment link send", policy: "Auto", approver: "—" },
  { action: "Discount up to 10%", policy: "Auto within rule", approver: "—" },
  { action: "Discount 11–20%", policy: "Auto within rule", approver: "Calling TL" },
  { action: "Discount 21–30%", policy: "Approval required", approver: "CEO AI" },
  { action: "New medical claim", policy: "Approval required", approver: "Doctor + Compliance" },
  { action: "New ad creative", policy: "Approval required", approver: "CEO AI / Prarit" },
  { action: "Ad budget increase", policy: "Approval required", approver: "Prarit" },
  { action: "Refund", policy: "Approval required", approver: "Human / Prarit" },
  { action: "Emergency medical case", policy: "Hard handoff", approver: "Doctor / Human" },
];

export const INTEGRATIONS = [
  { name: "Vapi", purpose: "AI calling voice", status: "Not connected", group: "AI" },
  { name: "Razorpay", purpose: "Payment gateway", status: "Not connected", group: "Payments" },
  { name: "PayU", purpose: "Payment gateway", status: "Not connected", group: "Payments" },
  { name: "Delhivery", purpose: "Courier & tracking", status: "Not connected", group: "Logistics" },
  { name: "Meta Ads", purpose: "Lead source & creative", status: "Not connected", group: "Marketing" },
  { name: "Madgicx", purpose: "Ad analytics", status: "Not connected", group: "Marketing" },
  { name: "WhatsApp Business", purpose: "Customer messaging", status: "Planned", group: "Messaging" },
];

/* ---------------- Dashboard KPIs ---------------- */
export const DASHBOARD_METRICS = {
  leadsToday: { value: 1240, deltaPct: 12.4 },
  callsRunning: { value: 18, completed: 412 },
  ordersPunched: { value: 184, deltaPct: 8.2 },
  ordersConfirmed: { value: 152, deltaPct: 5.1 },
  inTransit: { value: 96, deltaPct: 2.3 },
  delivered: { value: 64, deltaPct: 16.8 },
  rtoRisk: { value: 27, deltaPct: -3.2 },
  paymentsPaid: { value: 127, pending: 22 },
  netProfit: { value: 482000, deltaPct: 18.4 },
  agentHealth: { value: 92, alerts: 3 },
  ceoAlerts: { value: 4 },
  caioAlerts: { value: 2 },
};

/* ---------------- Phase 5A — WhatsApp mock fallbacks ---------------- */
export const WHATSAPP_PROVIDER_STATUS = {
  provider: "mock",
  configured: true,
  healthy: true,
  detail: "mock provider always healthy",
  connection: {
    id: "WAC-MOCK-1",
    displayName: "Nirogidhara WhatsApp (mock)",
    phoneNumber: "+91 90000 99999",
    phoneNumberId: "**…**",
    businessAccountId: "**…**",
    status: "connected",
    lastConnectedAt: null,
    lastHealthCheckAt: null,
  },
  accessTokenSet: false,
  verifyTokenSet: false,
  appSecretSet: false,
  apiVersion: "v20.0",
  devProviderEnabled: false,
  metadata: { mode: "mock" },
};

export const WHATSAPP_CONNECTIONS = [
  {
    id: "WAC-MOCK-1",
    provider: "mock",
    displayName: "Nirogidhara WhatsApp (mock)",
    phoneNumber: "+91 90000 99999",
    phoneNumberId: "",
    businessAccountId: "",
    status: "connected",
    lastConnectedAt: null,
    lastHealthCheckAt: null,
    lastError: "",
    metadata: {},
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

export const WHATSAPP_TEMPLATES = [
  {
    id: "WAT-MOCK-1",
    connectionId: "WAC-MOCK-1",
    name: "nrg_payment_reminder",
    language: "hi",
    category: "UTILITY",
    status: "APPROVED",
    bodyComponents: [
      { type: "BODY", text: "Hi {{1}}, your payment for {{2}} is pending." },
    ],
    variablesSchema: {
      required: ["customer_name", "context"],
      order: ["customer_name", "context"],
    },
    actionKey: "whatsapp.payment_reminder",
    claimVaultRequired: false,
    isActive: true,
    lastSyncedAt: null,
    metadata: { seeded: true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "WAT-MOCK-2",
    connectionId: "WAC-MOCK-1",
    name: "nrg_delivery_reminder",
    language: "hi",
    category: "UTILITY",
    status: "APPROVED",
    bodyComponents: [
      { type: "BODY", text: "Hi {{1}}, your order arrives today." },
    ],
    variablesSchema: { required: ["customer_name"], order: ["customer_name"] },
    actionKey: "whatsapp.delivery_reminder",
    claimVaultRequired: false,
    isActive: true,
    lastSyncedAt: null,
    metadata: { seeded: true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "WAT-MOCK-3",
    connectionId: "WAC-MOCK-1",
    name: "nrg_usage_explanation",
    language: "hi",
    category: "UTILITY",
    status: "APPROVED",
    bodyComponents: [
      { type: "BODY", text: "{{1}}'s usage instructions" },
    ],
    variablesSchema: { required: ["customer_name"], order: ["customer_name"] },
    actionKey: "whatsapp.usage_explanation",
    claimVaultRequired: true,
    isActive: true,
    lastSyncedAt: null,
    metadata: { seeded: true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

export const WHATSAPP_CONVERSATIONS: Array<Record<string, unknown>> = [];

export const WHATSAPP_MESSAGES: Array<Record<string, unknown>> = [];

// ---------- Phase 5F-Gate Auto-Reply Monitoring Dashboard mocks ----------
// Deterministic, safe defaults so the dashboard renders without a backend.

export const WHATSAPP_MONITORING_OVERVIEW: Record<string, unknown> = {
  windowHours: 2,
  generatedAt: new Date().toISOString(),
  status: "safe_off",
  nextAction: "ready_to_enable_limited_auto_reply_flag",
  rollbackReady: true,
  gate: {
    provider: "meta_cloud",
    limitedTestMode: true,
    autoReplyEnabled: false,
    allowedListSize: 1,
    allowedNumbersMasked: ["+91*****99001"],
    wabaSubscription: {
      checked: true,
      active: true,
      subscribedAppCount: 1,
      warning: "",
      error: "",
    },
    finalSendGuardActive: true,
    consentRequired: true,
    claimVaultRequired: true,
    blockedPhraseFilterActive: true,
    medicalSafetyActive: true,
    callHandoffEnabled: false,
    lifecycleEnabled: false,
    rescueDiscountEnabled: false,
    rtoRescueEnabled: false,
    reorderEnabled: false,
    campaignsLocked: true,
    readyForLimitedAutoReply: true,
    blockers: [],
    warnings: [],
    nextAction: "ready_to_enable_limited_auto_reply_flag",
  },
  activity: {
    windowHours: 2,
    since: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    now: new Date().toISOString(),
    allowedListSize: 1,
    inboundMessageCount: 0,
    outboundMessageCount: 0,
    inboundAiRunStartedCount: 0,
    replyAutoSentCount: 0,
    replyBlockedCount: 0,
    suggestionStoredCount: 0,
    handoffRequiredCount: 0,
    deterministicBuilderUsedCount: 0,
    deterministicBuilderBlockedCount: 0,
    objectionReplyUsedCount: 0,
    objectionReplyBlockedCount: 0,
    autoReplyFlagPathUsedCount: 0,
    autoReplyGuardBlockedCount: 0,
    safetyDowngradedCount: 0,
    messageDeliveredCount: 0,
    messageReadCount: 0,
    sendBlockedCount: 0,
    unexpectedNonAllowedSendsCount: 0,
    unexpectedNonAllowedSendSuffixes: [],
    ordersCreatedInWindow: 0,
    paymentsCreatedInWindow: 0,
    shipmentsCreatedInWindow: 0,
    discountOfferLogsCreatedInWindow: 0,
    warnings: [],
    nextAction: "no_recent_ai_activity_in_window",
  },
  cohort: {
    provider: "meta_cloud",
    limitedTestMode: true,
    autoReplyEnabled: false,
    callHandoffEnabled: false,
    lifecycleEnabled: false,
    rescueDiscountEnabled: false,
    rtoRescueEnabled: false,
    reorderEnabled: false,
    allowedListSize: 1,
    cohort: [
      {
        maskedPhone: "+91*****99001",
        suffix: "9001",
        customerFound: true,
        customerId: "NRG-CUST-MOCK-001",
        customerPhoneMasked: "+91*****99001",
        consentFound: true,
        consentState: "granted",
        consentSource: "internal_cohort_test",
        conversationFound: true,
        latestInboundId: "WAM-MOCK-IN-1",
        latestInboundAt: new Date().toISOString(),
        latestOutboundId: "WAM-MOCK-OUT-1",
        latestOutboundStatus: "read",
        latestOutboundAt: new Date().toISOString(),
        latestAuditAt: new Date().toISOString(),
        readyForControlledTest: true,
        missingSetup: [],
      },
    ],
    wabaSubscription: {
      checked: true,
      active: true,
      subscribedAppCount: 1,
      warning: "",
      error: "",
    },
    warnings: [],
    errors: [],
    nextAction: "cohort_ready_for_manual_scenario_tests",
  },
  pilot: {
    windowHours: 2,
    generatedAt: new Date().toISOString(),
    totalPilotMembers: 2,
    approvedCount: 1,
    pendingCount: 1,
    pausedCount: 0,
    consentMissingCount: 1,
    readyForPilotCount: 1,
    members: [
      {
        customerId: "NRG-CUST-MOCK-001",
        customerName: "Approved Pilot Customer",
        maskedPhone: "+91*****99011",
        phoneSuffix: "9011",
        status: "approved",
        consentRequired: true,
        consentVerified: true,
        source: "approved_customer_pilot",
        approvedAt: new Date().toISOString(),
        dailyCap: 3,
        lastInboundAt: new Date().toISOString(),
        lastOutboundAt: new Date().toISOString(),
        latestStatus: "read",
        phoneAllowedInLimitedMode: true,
        recentSafetyIssue: false,
        ready: true,
        blockers: [],
      },
      {
        customerId: "NRG-CUST-MOCK-002",
        customerName: "Pending Consent Customer",
        maskedPhone: "+91*****99002",
        phoneSuffix: "9002",
        status: "pending",
        consentRequired: true,
        consentVerified: false,
        source: "approved_customer_pilot",
        approvedAt: null,
        dailyCap: 3,
        lastInboundAt: null,
        lastOutboundAt: null,
        latestStatus: "",
        phoneAllowedInLimitedMode: true,
        recentSafetyIssue: false,
        ready: false,
        blockers: ["consent_not_verified", "status_pending"],
      },
    ],
    blockers: [],
    nextAction: "verify_customer_consent_before_pilot",
    safety: {
      autoReplyEnabled: false,
      limitedTestMode: true,
      campaignsLocked: true,
      broadcastLocked: true,
      callHandoffEnabled: false,
      lifecycleEnabled: false,
      rescueDiscountEnabled: false,
      rtoRescueEnabled: false,
      reorderEnabled: false,
      allowedListSize: 1,
      unexpectedNonAllowedSendsCount: 0,
      mutationCounts: {
        ordersCreatedInWindow: 0,
        paymentsCreatedInWindow: 0,
        shipmentsCreatedInWindow: 0,
        discountOfferLogsCreatedInWindow: 0,
      },
      mutationTotal: 0,
      dashboardAvailable: true,
    },
    saasGuardrails: {
      mode: "single_tenant_current",
      organizationModelExists: false,
      tenantModelExists: false,
      branchModelExists: false,
      userRolesExist: true,
      auditOrgBranchContextExists: false,
      featureFlagsPerOrgExist: false,
      whatsappSettingsPerOrgExist: false,
      safeInterfacesAdded: [
        "get_single_tenant_saas_guardrail_audit",
        "get_whatsapp_pilot_readiness_summary",
      ],
      deferred: [
        "Do not introduce Organization/Tenant/Branch migrations during this pilot gate.",
      ],
      nextAction: "document_saas_gaps_before_multi_tenant_build",
    },
  },
  mutationSafety: {
    windowHours: 2,
    since: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    now: new Date().toISOString(),
    ordersCreatedInWindow: 0,
    paymentsCreatedInWindow: 0,
    shipmentsCreatedInWindow: 0,
    discountOfferLogsCreatedInWindow: 0,
    lifecycleEventsInWindow: 0,
    handoffEventsInWindow: 0,
    totalMutations: 0,
    allClean: true,
  },
  unexpectedOutbound: {
    windowHours: 2,
    since: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    now: new Date().toISOString(),
    unexpectedSendsCount: 0,
    breakdown: [],
    rollbackRecommended: false,
  },
};

export const WHATSAPP_MONITORING_AUDIT: Record<string, unknown> = {
  windowHours: 2,
  since: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
  now: new Date().toISOString(),
  limit: 100,
  count: 0,
  events: [],
};

// ---------- Phase 6A — SaaS Foundation mocks ----------

const SAAS_DEFAULT_ORG: Record<string, unknown> = {
  id: 1,
  code: "nirogidhara",
  name: "Nirogidhara Private Limited",
  legalName: "Nirogidhara Private Limited",
  status: "active",
  timezone: "Asia/Kolkata",
  country: "IN",
  defaultBranch: {
    id: 1,
    code: "main",
    name: "Main Branch",
    status: "active",
  },
  userOrgRole: "owner",
  createdAt: new Date().toISOString(),
};

export const SAAS_CURRENT_ORGANIZATION: Record<string, unknown> = {
  organization: SAAS_DEFAULT_ORG,
  membershipSummary: {
    total: 1,
    active: 1,
    byRole: { owner: 1 },
  },
  settings: {},
  featureFlags: {},
};

export const SAAS_MY_ORGANIZATIONS: Record<string, unknown> = {
  count: 1,
  organizations: [SAAS_DEFAULT_ORG],
};

export const SAAS_FEATURE_FLAGS: Record<string, unknown> = {
  organization: SAAS_DEFAULT_ORG,
  featureFlags: {},
};

export const SAAS_DATA_COVERAGE: Record<string, unknown> = {
  defaultOrganizationExists: true,
  defaultOrganizationCode: "nirogidhara",
  defaultBranchExists: true,
  defaultBranchCode: "main",
  globalTenantFilteringEnabled: false,
  safeToStartPhase6C: true,
  models: [
    {
      model: "crm.Lead",
      totalRows: 43,
      withOrganization: 43,
      withoutOrganization: 0,
      organizationCoveragePercent: 100.0,
      hasBranchField: true,
      withBranch: 43,
      withoutBranch: 0,
      branchCoveragePercent: 100.0,
    },
    {
      model: "crm.Customer",
      totalRows: 25,
      withOrganization: 25,
      withoutOrganization: 0,
      organizationCoveragePercent: 100.0,
      hasBranchField: true,
      withBranch: 25,
      withoutBranch: 0,
      branchCoveragePercent: 100.0,
    },
    {
      model: "orders.Order",
      totalRows: 65,
      withOrganization: 65,
      withoutOrganization: 0,
      organizationCoveragePercent: 100.0,
      hasBranchField: true,
      withBranch: 65,
      withoutBranch: 0,
      branchCoveragePercent: 100.0,
    },
  ],
  totals: {
    totalRows: 133,
    totalWithOrganization: 133,
    totalWithoutOrganization: 0,
    totalWithBranch: 133,
    totalWithoutBranch: 0,
    organizationCoveragePercent: 100.0,
    branchCoveragePercent: 100.0,
  },
  blockers: [],
  warnings: [],
  nextAction: "ready_for_phase_6c_org_scoped_api_filtering_plan",
};

export const SAAS_WRITE_PATH_READINESS: Record<string, unknown> = {
  defaultOrganizationExists: true,
  defaultBranchExists: true,
  writeContextHelpersAvailable: true,
  enforcementMode: "safe_enforced",
  auditAutoOrgContextEnabled: true,
  coveredSafeCreatePaths: [
    "crm.Lead.create",
    "crm.Customer.create",
    "orders.Order.create",
    "orders.DiscountOfferLog.create",
    "payments.Payment.create",
    "shipments.Shipment.create",
    "calls.Call.create",
    "whatsapp.WhatsAppConsent.create",
    "whatsapp.WhatsAppConversation.create",
    "whatsapp.WhatsAppMessage.create",
    "whatsapp.WhatsAppLifecycleEvent.create",
    "whatsapp.WhatsAppHandoffToCall.create",
    "whatsapp.WhatsAppPilotCohortMember.create",
    "audit.AuditEvent.write_event (via Phase 6C auto-org)",
  ],
  safeCreatePathsCovered: [
    "crm.Lead.create",
    "crm.Customer.create",
    "orders.Order.create",
    "orders.DiscountOfferLog.create",
    "payments.Payment.create",
    "shipments.Shipment.create",
    "calls.Call.create",
    "whatsapp.WhatsAppConsent.create",
    "whatsapp.WhatsAppConversation.create",
    "whatsapp.WhatsAppMessage.create",
    "whatsapp.WhatsAppLifecycleEvent.create",
    "whatsapp.WhatsAppHandoffToCall.create",
    "whatsapp.WhatsAppPilotCohortMember.create",
    "audit.AuditEvent.write_event (via Phase 6C auto-org)",
  ],
  deferredCreatePaths: [
    "crm.MetaLeadEvent.create (webhook ingest log)",
    "whatsapp.WhatsAppConnection.create (system provider config)",
    "whatsapp.WhatsAppTemplate.create (registry)",
    "whatsapp.WhatsAppMessageAttachment.create (child of message)",
    "whatsapp.WhatsAppMessageStatusEvent.create (child of message)",
    "whatsapp.WhatsAppWebhookEvent.create (webhook ingest log)",
    "whatsapp.WhatsAppSendLog.create (send-attempt log)",
    "whatsapp.WhatsAppInternalNote.create (operator note)",
    "calls.ActiveCall.create (transient singleton)",
    "calls.CallTranscriptLine.create (child of call)",
    "calls.WebhookEvent.create (webhook ingest log)",
    "payments.WebhookEvent.create (webhook ingest log)",
    "shipments.WorkflowStep.create (child of shipment)",
    "shipments.RescueAttempt.create (child of shipment)",
  ],
  systemGlobalExceptions: [
    "whatsapp.WhatsAppConnection.create (system provider config)",
    "whatsapp.WhatsAppTemplate.create (Meta registry)",
    "crm.MetaLeadEvent.create (webhook ingest log)",
    "whatsapp.WhatsAppWebhookEvent.create (webhook ingest log)",
    "payments.WebhookEvent.create (webhook ingest log)",
    "calls.WebhookEvent.create (webhook ingest log)",
  ],
  modelsWithOrgBranch: [
    "crm.Lead",
    "crm.Customer",
    "orders.Order",
    "orders.DiscountOfferLog",
    "payments.Payment",
    "shipments.Shipment",
    "calls.Call",
    "whatsapp.WhatsAppConsent",
    "whatsapp.WhatsAppConversation",
    "whatsapp.WhatsAppMessage",
    "whatsapp.WhatsAppLifecycleEvent",
    "whatsapp.WhatsAppHandoffToCall",
    "whatsapp.WhatsAppPilotCohortMember",
  ],
  recentUnscopedWritesLast24h: 0,
  recentUnscopedWriteDetails: {
    windowHours: 24,
    totalWithoutOrganization: 0,
    totalWithoutBranch: 0,
    rows: [],
  },
  recentRowsWithoutOrganizationLast24h: 0,
  recentRowsWithoutBranchLast24h: 0,
  globalTenantFilteringEnabled: false,
  safeToStartPhase6E: true,
  safeToStartPhase6F: true,
  blockers: [],
  warnings: [],
  nextAction: "ready_for_phase_6f_per_org_runtime_integration_routing_plan",
};

export const SAAS_ORG_SCOPE_READINESS: Record<string, unknown> = {
  defaultOrganizationExists: true,
  defaultOrganizationCode: "nirogidhara",
  defaultBranchExists: true,
  defaultBranchCode: "main",
  organizationCoveragePercent: 99.85,
  branchCoveragePercent: 100.0,
  scopedModels: [
    "crm.Lead",
    "crm.Customer",
    "orders.Order",
    "orders.DiscountOfferLog",
    "payments.Payment",
    "shipments.Shipment",
    "calls.Call",
    "whatsapp.WhatsAppConsent",
    "whatsapp.WhatsAppConversation",
    "whatsapp.WhatsAppMessage",
    "whatsapp.WhatsAppLifecycleEvent",
    "whatsapp.WhatsAppHandoffToCall",
    "whatsapp.WhatsAppPilotCohortMember",
    "audit.AuditEvent",
  ],
  unscopedModels: [],
  scopedApis: [],
  unscopedApis: [],
  auditAutoOrgContextEnabled: true,
  globalTenantFilteringEnabled: false,
  safeToStartPhase6D: true,
  blockers: [],
  warnings: [],
  nextAction: "ready_for_phase_6d_write_path_org_assignment",
};

const SAAS_INTEGRATION_PROVIDERS = [
  "whatsapp_meta",
  "razorpay",
  "payu",
  "delhivery",
  "vapi",
  "openai",
] as const;

export const SAAS_INTEGRATION_SETTINGS: Record<string, unknown> = {
  organization: SAAS_DEFAULT_ORG,
  settings: [],
  runtimeUsesPerOrgSettings: false,
};

export const SAAS_INTEGRATION_READINESS: Record<string, unknown> = {
  organization: {
    id: 1,
    code: "nirogidhara",
    name: "Nirogidhara Private Limited",
  },
  providers: SAAS_INTEGRATION_PROVIDERS.map((providerType) => ({
    providerType,
    providerLabel:
      providerType === "whatsapp_meta"
        ? "WhatsApp Meta"
        : providerType.charAt(0).toUpperCase() + providerType.slice(1),
    status: "missing",
    configured: false,
    isActive: false,
    secretRefsPresent: false,
    missingSecretRefs: ["secret_ref"],
    validationStatus: "not_checked",
    validationMessage: "",
    runtimeEnabled: false,
    runtimeUsesPerOrgSettings: false,
    setting: null,
    warnings: ["No per-org integration setting configured."],
    nextAction: "configure_secret_refs_before_phase_6f",
  })),
  providersConfigured: [],
  providersMissing: SAAS_INTEGRATION_PROVIDERS,
  secretRefsMissing: SAAS_INTEGRATION_PROVIDERS,
  integrationSettingsCount: 0,
  runtimeUsesPerOrgSettings: false,
  safeToStartPhase6F: true,
  warnings: [
    "Per-org provider routing is deferred; runtime still uses env/config.",
  ],
  nextAction: "phase_6f_per_org_runtime_integration_routing_plan",
};

export const SAAS_ADMIN_OVERVIEW: Record<string, unknown> = {
  defaultOrganizationExists: true,
  defaultBranchExists: true,
  organization: {
    ...SAAS_DEFAULT_ORG,
    membershipSummary: { total: 1, active: 1, byRole: { owner: 1 } },
    featureFlags: {},
    integrationSettingsCount: 0,
  },
  orgScopeReadiness: SAAS_ORG_SCOPE_READINESS,
  writePathReadiness: SAAS_WRITE_PATH_READINESS,
  integrationReadiness: SAAS_INTEGRATION_READINESS,
  integrationSettings: [],
  integrationSettingsCount: 0,
  providersConfigured: [],
  providersMissing: SAAS_INTEGRATION_PROVIDERS,
  secretRefsMissing: SAAS_INTEGRATION_PROVIDERS,
  safetyLocks: {
    whatsappAutoReplyEnabled: false,
    whatsappAutoReplyOff: true,
    limitedTestMode: true,
    campaignsLocked: true,
    broadcastLocked: true,
    callHandoffEnabled: false,
    lifecycleAutomationEnabled: false,
    rescueDiscountEnabled: false,
    rtoRescueEnabled: false,
    reorderDay20Enabled: false,
    runtimeUsesPerOrgSettings: false,
  },
  runtimeUsesPerOrgSettings: false,
  auditTimeline: [],
  safeToStartPhase6F: true,
  blockers: [],
  warnings: [
    "Per-org provider routing is deferred; runtime still uses env/config.",
  ],
  nextAction: "phase_6f_per_org_runtime_integration_routing_plan",
};

export const SAAS_ADMIN_ORGANIZATIONS: Record<string, unknown> = {
  count: 1,
  organizations: [
    {
      ...SAAS_DEFAULT_ORG,
      membershipSummary: { total: 1, active: 1, byRole: { owner: 1 } },
      featureFlags: {},
      integrationSettingsCount: 0,
    },
  ],
};

// Phase 6F — Runtime integration routing readiness preview.
const _PROVIDER_PREVIEW_TEMPLATE = (
  providerType: string,
  providerLabel: string,
  expectedRefs: string[],
) => ({
  providerType,
  providerLabel,
  integrationSettingExists: false,
  settingStatus: "missing",
  isActive: false,
  runtimeSource: "env_config" as const,
  perOrgRuntimeEnabled: false as const,
  secretRefsPresent: false,
  secretRefsResolvablePreview: { perRef: {}, anyMissingEnv: true },
  missingSecretRefs: expectedRefs,
  configPresent: false,
  envKeyStatus: {},
  expectedSecretRefKeys: expectedRefs,
  setting: null,
  blockers: [],
  warnings: ["No per-org integration setting configured."],
  nextAction: "configure_org_integration_settings_before_runtime_routing",
});

export const SAAS_RUNTIME_ROUTING_READINESS: Record<string, unknown> = {
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  runtimeUsesPerOrgSettings: false,
  perOrgRuntimeEnabled: false,
  providers: [
    _PROVIDER_PREVIEW_TEMPLATE("whatsapp_meta", "WhatsApp Meta", [
      "access_token",
      "app_secret",
      "verify_token",
    ]),
    _PROVIDER_PREVIEW_TEMPLATE("razorpay", "Razorpay", ["key_secret"]),
    _PROVIDER_PREVIEW_TEMPLATE("payu", "PayU", ["merchant_key", "salt"]),
    _PROVIDER_PREVIEW_TEMPLATE("delhivery", "Delhivery", ["api_token"]),
    _PROVIDER_PREVIEW_TEMPLATE("vapi", "Vapi", ["api_key"]),
    _PROVIDER_PREVIEW_TEMPLATE("openai", "OpenAI", ["api_key"]),
  ],
  global: {
    safeToStartPhase6G: false,
    blockers: [],
    warnings: [
      "At least one provider has no per-org integration setting; Phase 6G dry-run is blocked until every provider is configured.",
    ],
    nextAction: "configure_org_integration_settings_before_runtime_routing",
  },
  warnings: [],
  blockers: [],
  nextAction: "configure_org_integration_settings_before_runtime_routing",
};

// ---------- Phase 6G — Controlled Runtime Routing Dry Run fixtures ----------

const _RUNTIME_OPS: Array<{
  operationType: string;
  providerType: string;
  providerLabel: string;
  sideEffectRisk: "none" | "low" | "medium" | "high";
  envKeys: string[];
}> = [
  {
    operationType: "whatsapp.send_text",
    providerType: "whatsapp_meta",
    providerLabel: "WhatsApp Meta",
    sideEffectRisk: "high",
    envKeys: [
      "META_WA_ACCESS_TOKEN",
      "META_WA_PHONE_NUMBER_ID",
      "META_WA_BUSINESS_ACCOUNT_ID",
      "META_WA_VERIFY_TOKEN",
      "META_WA_APP_SECRET",
    ],
  },
  {
    operationType: "whatsapp.send_template",
    providerType: "whatsapp_meta",
    providerLabel: "WhatsApp Meta",
    sideEffectRisk: "high",
    envKeys: [
      "META_WA_ACCESS_TOKEN",
      "META_WA_PHONE_NUMBER_ID",
      "META_WA_BUSINESS_ACCOUNT_ID",
      "META_WA_VERIFY_TOKEN",
      "META_WA_APP_SECRET",
    ],
  },
  {
    operationType: "razorpay.create_order",
    providerType: "razorpay",
    providerLabel: "Razorpay",
    sideEffectRisk: "high",
    envKeys: ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"],
  },
  {
    operationType: "razorpay.create_payment_link",
    providerType: "razorpay",
    providerLabel: "Razorpay",
    sideEffectRisk: "high",
    envKeys: ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"],
  },
  {
    operationType: "payu.create_payment",
    providerType: "payu",
    providerLabel: "PayU",
    sideEffectRisk: "high",
    envKeys: ["PAYU_KEY", "PAYU_SECRET"],
  },
  {
    operationType: "delhivery.create_shipment",
    providerType: "delhivery",
    providerLabel: "Delhivery",
    sideEffectRisk: "high",
    envKeys: ["DELHIVERY_API_TOKEN"],
  },
  {
    operationType: "vapi.place_call",
    providerType: "vapi",
    providerLabel: "Vapi",
    sideEffectRisk: "high",
    envKeys: ["VAPI_API_KEY", "VAPI_PHONE_NUMBER_ID", "VAPI_WEBHOOK_SECRET"],
  },
  {
    operationType: "openai.agent_completion",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "low",
    envKeys: ["OPENAI_API_KEY"],
  },
  {
    operationType: "ai.reports_summary",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "none",
    envKeys: ["NVIDIA_API_KEY", "NVIDIA_API_BASE_URL", "AI_MAX_TOKENS_REPORTS"],
  },
  {
    operationType: "ai.ceo_planning",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "none",
    envKeys: ["NVIDIA_API_KEY", "NVIDIA_API_BASE_URL", "AI_MAX_TOKENS_CEO"],
  },
  {
    operationType: "ai.caio_compliance",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "none",
    envKeys: [
      "NVIDIA_API_KEY",
      "NVIDIA_API_BASE_URL",
      "AI_MAX_TOKENS_COMPLIANCE",
    ],
  },
  {
    operationType: "ai.customer_hinglish_chat",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "medium",
    envKeys: [
      "NVIDIA_API_KEY",
      "NVIDIA_API_BASE_URL",
      "AI_MAX_TOKENS_CUSTOMER_CHAT",
    ],
  },
  {
    operationType: "ai.critical_fallback",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "low",
    envKeys: ["OPENAI_API_KEY"],
  },
  {
    operationType: "ai.smoke_test",
    providerType: "openai",
    providerLabel: "OpenAI",
    sideEffectRisk: "none",
    envKeys: ["NVIDIA_API_KEY", "AI_MAX_TOKENS_SMOKE"],
  },
];

const _AI_TASK_FIXTURES = [
  {
    taskType: "reports_summaries",
    primaryModel: "minimaxai/minimax-m2.7",
    fallbackModel: "gpt-4o-mini",
    maxTokens: 3000,
    maxTokensSource: "AI_MAX_TOKENS_REPORTS",
    safetyWrappersRequired: false,
    safetyNotes: [],
  },
  {
    taskType: "ceo_planning",
    primaryModel: "moonshotai/kimi-k2.6",
    fallbackModel: "gpt-4o",
    maxTokens: 2048,
    maxTokensSource: "AI_MAX_TOKENS_CEO",
    safetyWrappersRequired: false,
    safetyNotes: [],
  },
  {
    taskType: "caio_compliance",
    primaryModel: "mistralai/mistral-medium-3.5-128b",
    fallbackModel: "gpt-4o",
    maxTokens: 1024,
    maxTokensSource: "AI_MAX_TOKENS_COMPLIANCE",
    safetyWrappersRequired: true,
    safetyNotes: [
      "Low-confidence compliance findings must escalate to the existing human-review CAIO workflow.",
    ],
  },
  {
    taskType: "hinglish_customer_chat",
    primaryModel: "google/gemma-4-31b-it",
    fallbackModel: "gpt-4o-mini",
    maxTokens: 512,
    maxTokensSource: "AI_MAX_TOKENS_CUSTOMER_CHAT",
    safetyWrappersRequired: true,
    safetyNotes: [
      "Customer-facing drafts must still pass through Claim Vault, blocked phrase filter, safety stack, and approval matrix before any live send.",
    ],
  },
  {
    taskType: "critical_fallback",
    primaryModel: "mistralai/mistral-medium-3.5-128b",
    fallbackModel: "gpt-4o",
    maxTokens: 1024,
    maxTokensSource: "AI_MAX_TOKENS_COMPLIANCE",
    safetyWrappersRequired: false,
    safetyNotes: [],
  },
  {
    taskType: "smoke_test",
    primaryModel: "google/gemma-4-31b-it",
    fallbackModel: "gpt-4o-mini",
    maxTokens: 32,
    maxTokensSource: "AI_MAX_TOKENS_SMOKE",
    safetyWrappersRequired: false,
    safetyNotes: [],
  },
];

const _AI_TASK_PREVIEWS = _AI_TASK_FIXTURES.map((task) => ({
  taskType: task.taskType,
  primaryProvider: "nvidia",
  primaryModel: task.primaryModel,
  primaryModelSource: "default",
  expectedPrimaryModel: task.primaryModel,
  fallbackProvider: "openai",
  fallbackModel: task.fallbackModel,
  fallbackModelSource: "default",
  fallbackConfigured: false,
  anthropicFallbackConfigured: false,
  runtimeMode: "preview",
  maxTokens: task.maxTokens,
  maxTokensSource: task.maxTokensSource,
  maxTokensFromEnv: false,
  apiBaseUrlPresent: false,
  apiKeyPresent: false,
  openaiKeyPresent: false,
  liveCallWillBeMade: false,
  dryRun: true,
  safetyWrappersRequired: task.safetyWrappersRequired,
  safetyNotes: task.safetyNotes,
  blockers: ["NVIDIA_API_KEY is not set"],
  warnings: [
    "NVIDIA_API_BASE_URL is not set; the adapter will use its built-in default.",
    "OPENAI_API_KEY is not set; the OpenAI fallback path will be unavailable.",
    ...task.safetyNotes,
  ],
  nextAction: "fix_ai_provider_env_before_dry_run",
  valid: true,
}));

export const SAAS_AI_PROVIDER_ROUTING_PREVIEW: Record<string, unknown> = {
  runtime: {
    runtimeMode: "preview",
    primaryProvider: "nvidia",
    fallbackProvider: "openai",
    envKeyPresence: {
      NVIDIA_API_KEY: false,
      NVIDIA_API_BASE_URL: false,
      OPENAI_API_KEY: false,
      OPENAI_API_BASE_URL: false,
      ANTHROPIC_API_KEY: false,
      AI_PROVIDER_RUNTIME_MODE: false,
      AI_PRIMARY_PROVIDER: false,
      AI_FALLBACK_PROVIDER: false,
    },
  },
  tasks: _AI_TASK_PREVIEWS,
  safeToStartAiDryRun: false,
  blockers: ["NVIDIA_API_KEY is not set"],
  warnings: [],
  nextAction: "fix_ai_provider_env_before_dry_run",
  dryRun: true,
  liveCallWillBeMade: false,
};

const _OP_DRY_RUN_DECISIONS = _RUNTIME_OPS.map((op) => {
  const aiTaskMap: Record<string, string> = {
    "ai.reports_summary": "reports_summaries",
    "ai.ceo_planning": "ceo_planning",
    "ai.caio_compliance": "caio_compliance",
    "ai.customer_hinglish_chat": "hinglish_customer_chat",
    "ai.critical_fallback": "critical_fallback",
    "ai.smoke_test": "smoke_test",
  };
  const aiTaskName = aiTaskMap[op.operationType] ?? "";
  const aiPreview = aiTaskName
    ? (_AI_TASK_PREVIEWS.find((t) => t.taskType === aiTaskName) ?? null)
    : null;
  const warnings: string[] = [
    "No per-org integration setting configured. Runtime stays on env / config.",
  ];
  if (op.providerType === "payu" || op.providerType === "delhivery") {
    warnings.push(
      `${op.providerType} env keys missing — deferred provider; live execution remains blocked.`,
    );
  } else if (op.providerType === "vapi") {
    warnings.push(
      "Vapi env partially configured — phone_number_id and webhook_secret are still missing; live calls remain blocked.",
    );
  } else if (op.envKeys.length) {
    warnings.push(
      `Required env keys missing for ${op.operationType}: ${op.envKeys.join(", ")}`,
    );
  }
  const blockers = aiPreview?.blockers ?? [];
  return {
    operationType: op.operationType,
    operationDefinition: {
      operationType: op.operationType,
      providerType: op.providerType,
      sideEffectRisk: op.sideEffectRisk,
      dryRunAllowed: true,
      liveAllowedInPhase6G: false,
      requiredOrg: true,
      requiredSecretRefs: [],
      requiredEnvKeys: op.envKeys,
      requiredConfigKeys: [],
      readinessNotes: "",
      nextPhaseForLiveExecution:
        op.providerType === "payu"
          ? "deferred_until_payu_credentials_available"
          : op.providerType === "delhivery"
            ? "deferred_until_delhivery_credentials_available"
            : "phase_6h_controlled_live_execution_audit",
    },
    organization: {
      id: SAAS_DEFAULT_ORG.id,
      code: SAAS_DEFAULT_ORG.code,
      name: SAAS_DEFAULT_ORG.name,
    },
    branch: null,
    providerType: op.providerType,
    providerLabel: op.providerLabel,
    runtimeSource: "env_config",
    perOrgRuntimeEnabled: false,
    dryRun: true,
    liveExecutionAllowed: false,
    externalCallWillBeMade: false,
    sideEffectRisk: op.sideEffectRisk,
    providerSettingExists: false,
    settingStatus: "not_configured",
    secretRefsStatus: {},
    envKeyStatus: Object.fromEntries(op.envKeys.map((key) => [key, false])),
    configStatus: {},
    providerRuntimePreview: {
      secretRefsPresent: false,
      missingSecretRefs: [],
      configPresent: false,
    },
    aiProviderRoute: aiPreview,
    blockers,
    warnings,
    nextAction:
      blockers.length > 0
        ? "fix_runtime_routing_blockers"
        : "ready_for_phase_6h_controlled_runtime_live_audit",
    auditKind: "saas.runtime_dry_run.previewed",
  };
});

export const SAAS_RUNTIME_DRY_RUN_REPORT: Record<string, unknown> = {
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  runtimeUsesPerOrgSettings: false,
  perOrgRuntimeEnabled: false,
  runtimeSource: "env_config",
  dryRun: true,
  liveExecutionAllowed: false,
  operations: _OP_DRY_RUN_DECISIONS,
  aiProviderRoutes: SAAS_AI_PROVIDER_ROUTING_PREVIEW,
  global: {
    safeToStartPhase6H: false,
    blockers: ["NVIDIA_API_KEY is not set"],
    warnings: [],
    nextAction: "fix_runtime_routing_blockers",
  },
  blockers: ["NVIDIA_API_KEY is not set"],
  warnings: [],
  nextAction: "fix_runtime_routing_blockers",
};

export const SAAS_CONTROLLED_RUNTIME_READINESS: Record<string, unknown> = {
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  runtimeUsesPerOrgSettings: false,
  dryRun: true,
  liveExecutionAllowed: false,
  operationCount: _RUNTIME_OPS.length,
  aiTaskCount: _AI_TASK_FIXTURES.length,
  safeToStartPhase6H: false,
  blockers: ["NVIDIA_API_KEY is not set"],
  warnings: [],
  nextAction: "fix_runtime_routing_blockers",
};

// ---------- Phase 6H - Controlled Runtime Live Audit Gate fixtures ----------

const _LIVE_GATE_OPS = [
  "whatsapp.send_text",
  "whatsapp.send_template",
  "razorpay.create_order",
  "razorpay.create_payment_link",
  "payu.create_payment",
  "delhivery.create_shipment",
  "vapi.place_call",
  "ai.customer_hinglish_chat",
  "ai.caio_compliance",
  "ai.ceo_planning",
  "ai.reports_summary",
  "ai.critical_fallback",
  "ai.smoke_test",
];

const _LIVE_GATE_POLICY_FIXTURES = _LIVE_GATE_OPS.map((operationType) => {
  const runtimeOp = _RUNTIME_OPS.find((op) => op.operationType === operationType);
  const providerType =
    operationType === "ai.smoke_test"
      ? "nvidia"
      : runtimeOp?.providerType ??
        (operationType.startsWith("ai.") ? "openai" : "other");
  const riskLevel =
    operationType === "vapi.place_call" ||
    operationType === "ai.customer_hinglish_chat"
      ? "critical"
      : operationType.includes("payment_link") ||
          operationType.includes("shipment") ||
          operationType.startsWith("whatsapp.")
        ? "high"
        : operationType.includes("create_order") ||
            operationType.includes("create_payment")
          ? "medium"
          : "low";
  return {
    operationType,
    providerType,
    riskLevel,
    liveAllowedByDefault: false,
    approvalRequired: true,
    caioReviewRequired:
      operationType === "whatsapp.send_text" ||
      operationType.includes("customer_hinglish") ||
      operationType.includes("caio"),
    consentRequired:
      operationType.startsWith("whatsapp.") || operationType === "vapi.place_call",
    claimVaultRequired:
      operationType === "whatsapp.send_text" ||
      operationType === "ai.customer_hinglish_chat",
    webhookRequired:
      operationType.includes("razorpay") ||
      operationType.includes("delhivery") ||
      operationType.includes("vapi"),
    idempotencyRequired: true,
    auditRequired: true,
    killSwitchCanBlock: true,
    allowedInPhase6H: false,
    nextPhaseForLiveTest: operationType.includes("payu")
      ? "deferred_until_payu_credentials_available"
      : operationType.includes("delhivery")
        ? "deferred_until_delhivery_credentials_available"
        : "phase_6i_single_internal_live_gate_simulation",
    templateApprovalRequired: operationType === "whatsapp.send_template",
    paymentApprovalRequired: operationType.includes("razorpay") || operationType.includes("payu"),
    customerIntentRequired: operationType === "razorpay.create_payment_link",
    addressValidationRequired: operationType === "delhivery.create_shipment",
    providerDeferred: operationType.includes("payu") || operationType.includes("delhivery"),
    humanApprovalRequired: operationType === "ai.customer_hinglish_chat",
    requiredEnvKeys: runtimeOp?.envKeys ?? [],
    requiredConfigKeys: [],
    policyVersion: "phase6h.v1",
    currentGateDecision: "blocked_by_default",
    liveAllowedNow: false,
    blockers: ["runtime_kill_switch_active:global", "phase_6h_live_execution_disabled"],
    warnings: [],
    nextAction: "keep_live_execution_blocked",
    metadata: {},
  };
});

export const SAAS_RUNTIME_LIVE_GATE: Record<string, unknown> = {
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  killSwitch: {
    globalEnabled: true,
    orgEnabled: false,
    providerEnabled: false,
    operationEnabled: false,
    active: true,
    activeBlockers: ["global"],
  },
  operationPolicies: _LIVE_GATE_POLICY_FIXTURES,
  recentLiveExecutionRequests: [],
  approvalQueue: {
    approvalPendingCount: 0,
    approvedButNotExecutedCount: 0,
    blockedCount: 0,
    rejectedCount: 0,
  },
  approvalPendingCount: 0,
  approvedButNotExecutedCount: 0,
  blockedCount: 0,
  rejectedCount: 0,
  recentGateAuditEvents: [],
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  runtimeUsesPerOrgSettings: false,
  defaultDryRun: true,
  defaultLiveExecutionAllowed: false,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
  safeToStartPhase6I: true,
  blockers: [],
  warnings: [
    "PayU deferred.",
    "Delhivery deferred.",
    "Vapi missing phone_number_id/webhook_secret until env is configured.",
    "WhatsApp auto-reply OFF; campaigns/broadcast locked.",
    "AI customer send requires Claim Vault + CAIO + approval.",
    "Approving in Phase 6H does not execute external calls.",
  ],
  nextAction: "ready_for_phase_6i_single_internal_live_gate_simulation",
};

export const SAAS_RUNTIME_LIVE_GATE_POLICIES: Record<string, unknown> = {
  policies: _LIVE_GATE_POLICY_FIXTURES,
  dryRun: true,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
};

export const SAAS_RUNTIME_LIVE_GATE_KILL_SWITCH: Record<string, unknown> = {
  scope: "global",
  enabled: true,
  reason: "Phase 6H default global live execution block.",
  dryRun: true,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
  killSwitchActive: true,
  approvalStatus: "",
  gateDecision: "blocked_by_kill_switch",
  blockers: ["global_runtime_kill_switch_enabled"],
  warnings: ["Phase 6H does not execute external calls even when disabled."],
  nextAction: "keep_live_execution_blocked",
};

const _LIVE_GATE_REQUEST = {
  id: 1,
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  branch: null,
  operationType: "razorpay.create_order",
  providerType: "razorpay",
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  dryRun: true,
  liveExecutionRequested: true,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
  approvalRequired: true,
  approvalStatus: "pending",
  requestedBy: null,
  approvedBy: null,
  rejectedBy: null,
  requestedAt: new Date().toISOString(),
  approvedAt: null,
  rejectedAt: null,
  expiresAt: null,
  riskLevel: "medium",
  payloadHash: "mockhash",
  safePayloadSummary: { amount: 499, phone: "+91******1234" },
  blockers: ["runtime_kill_switch_active:global", "phase_6h_live_execution_disabled"],
  warnings: ["Approving in Phase 6H does not execute external calls."],
  gateDecision: "blocked_by_default",
  idempotencyKey: "mock-idempotency-key",
  auditEventId: null,
  metadata: { phase: "6H", no_provider_call: true },
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  killSwitchActive: true,
  nextAction: "keep_live_execution_blocked",
};

export const SAAS_RUNTIME_LIVE_GATE_REQUESTS: Record<string, unknown> = {
  count: 1,
  requests: [_LIVE_GATE_REQUEST],
  dryRun: true,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
};

export const SAAS_RUNTIME_LIVE_GATE_PREVIEW: Record<string, unknown> = {
  operationType: "whatsapp.send_text",
  providerType: "whatsapp_meta",
  valid: true,
  policy: _LIVE_GATE_POLICY_FIXTURES[0],
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  branch: null,
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  dryRun: true,
  liveExecutionRequested: false,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
  approvalRequired: true,
  approvalStatus: "not_required",
  killSwitchActive: true,
  riskLevel: "high",
  payloadHash: "",
  safePayloadSummary: {},
  blockers: [],
  warnings: ["dry_run_preview_only"],
  gateDecision: "dry_run_allowed",
  nextAction: "dry_run_preview_only",
};

const _LIVE_GATE_SIMULATION = {
  id: 1,
  organization: {
    id: SAAS_DEFAULT_ORG.id,
    code: SAAS_DEFAULT_ORG.code,
    name: SAAS_DEFAULT_ORG.name,
  },
  branch: null,
  liveExecutionRequestId: null,
  operationType: "razorpay.create_order",
  providerType: "razorpay",
  status: "prepared",
  approvalStatus: "not_required",
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  dryRun: true,
  liveExecutionRequested: false,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
  externalCallWasMade: false,
  providerCallAttempted: false,
  killSwitchActive: true,
  riskLevel: "medium",
  payloadHash: "mock-phase6i-hash",
  safePayloadSummary: {
    simulation: true,
    internalOnly: true,
    idempotencyKey: "phase6i:razorpay.create_order:mock",
    amountInPaise: 100,
    currency: "INR",
  },
  blockers: [
    "runtime_kill_switch_active:global",
    "phase_6h_live_execution_disabled",
  ],
  warnings: [
    "Phase 6I simulation never calls providers or creates external side effects.",
  ],
  gateDecision: "blocked_by_default",
  idempotencyKey: "phase6i:razorpay.create_order:mock",
  simulationResult: {
    passed: false,
    externalCallWasMade: false,
    providerCallAttempted: false,
  },
  preparedBy: null,
  approvalRequestedBy: null,
  approvedBy: null,
  rejectedBy: null,
  runBy: null,
  rolledBackBy: null,
  preparedAt: new Date().toISOString(),
  approvalRequestedAt: null,
  approvedAt: null,
  rejectedAt: null,
  runAt: null,
  rolledBackAt: null,
  metadata: {
    phase: "6I",
    noProviderCall: true,
  },
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  nextAction: "request_internal_approval_before_simulation_run",
};

export const SAAS_RUNTIME_LIVE_GATE_SIMULATIONS: Record<string, unknown> = {
  count: 1,
  simulations: [_LIVE_GATE_SIMULATION],
  allowedOperations: [
    "razorpay.create_order",
    "whatsapp.send_text",
    "ai.smoke_test",
  ],
  defaultOperation: "razorpay.create_order",
  dryRun: true,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
  externalCallWasMade: false,
  providerCallAttempted: false,
  killSwitchActive: true,
  summary: {
    organization: {
      id: SAAS_DEFAULT_ORG.id,
      code: SAAS_DEFAULT_ORG.code,
      name: SAAS_DEFAULT_ORG.name,
    },
    allowedOperations: [
      "razorpay.create_order",
      "whatsapp.send_text",
      "ai.smoke_test",
    ],
    defaultOperation: "razorpay.create_order",
    simulationCount: 1,
    approvalPendingCount: 0,
    approvedCount: 0,
    simulatedCount: 0,
    latestSimulation: _LIVE_GATE_SIMULATION,
    dryRun: true,
    liveExecutionAllowed: false,
    externalCallWillBeMade: false,
    externalCallWasMade: false,
    providerCallAttempted: false,
    killSwitchActive: true,
    runtimeSource: "env_config",
    perOrgRuntimeEnabled: false,
    safeToPreparePhase6ISimulation: true,
    safeToRunInternalSimulation: true,
    blockers: [],
    warnings: [
      "Phase 6I simulation never calls providers or creates external side effects.",
      "Default operation is razorpay.create_order but no Razorpay API call is made.",
    ],
    nextAction: "request_internal_approval_before_simulation_run",
  },
};

// ---------- Phase 6J - Single Internal Provider Test Plan ----------

const _PROVIDER_TEST_PLAN: Record<string, unknown> = {
  id: 1,
  planId: "ptp_demo_phase6j",
  organization: { id: 1, code: "nirogidhara", name: "Nirogidhara Private Limited" },
  branch: { id: 1, code: "main", name: "Main Branch" },
  providerType: "razorpay",
  operationType: "razorpay.create_order",
  providerEnvironment: "test",
  status: "prepared",
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  dryRun: true,
  providerCallAllowed: false,
  externalCallWillBeMade: false,
  externalCallWasMade: false,
  providerCallAttempted: false,
  realCustomerDataAllowed: false,
  realMoney: false,
  amountPaise: 100,
  currency: "INR",
  idempotencyKey: "phase6j_internal_test_plan_ptp_demo_phase6j",
  payloadHash: "demohashphase6jzz",
  safePayloadSummary: {
    operationType: "razorpay.create_order",
    amount: 100,
    currency: "INR",
    receipt: "phase6j_internal_test_plan_ptp_demo_phase6j",
    notes: {
      purpose: "internal_test_plan_only",
      external_call: false,
      real_customer_data: false,
      phase: "6J",
    },
  },
  envReadiness: {
    providerType: "razorpay",
    envPresence: {
      RAZORPAY_KEY_ID: false,
      RAZORPAY_KEY_SECRET: false,
      RAZORPAY_WEBHOOK_SECRET: false,
    },
    secretRefStatus: {
      key_id: { valid: true, source: "env", maskedRef: "ENV:RAZ***Y_ID", present: false, canResolveAtRuntime: false, reason: "" },
      key_secret: { valid: true, source: "env", maskedRef: "ENV:RAZ***CRET", present: false, canResolveAtRuntime: false, reason: "" },
      webhook_secret: { valid: true, source: "env", maskedRef: "ENV:RAZ***CRET", present: false, canResolveAtRuntime: false, reason: "" },
    },
    maskedSecretRefs: {
      key_id: "ENV:RAZ***Y_ID",
      key_secret: "ENV:RAZ***CRET",
      webhook_secret: "ENV:RAZ***CRET",
    },
    envReady: false,
    webhookReady: false,
  },
  secretRefReadiness: {},
  gateRequirements: {
    liveGateRequired: true,
    killSwitchMustRemainEnabled: true,
    approvalRequired: true,
    idempotencyRequired: true,
    webhookRequiredForFutureExecution: true,
    providerCallAllowedInPhase6J: false,
    externalProviderCallAllowedInPhase6J: false,
  },
  approvalRequirements: {
    approvalRequired: true,
    approverRoles: ["admin", "director", "superuser"],
    rejectionAllowed: true,
    archiveAllowed: true,
    approvalUnlocksLiveExecutionInPhase6J: false,
    approvalUnlocksFutureExecutionInPhase6K: true,
  },
  rollbackPlan: {
    rollbackRequired: true,
    noExternalRollbackInPhase6J: true,
    rollbackSteps: [
      "Phase 6J never calls the provider — no provider-side state to rollback.",
      "Archive plan ptp_demo_phase6j via archive_single_provider_test_plan.",
      "Audit trail is preserved in AuditEvent rows.",
    ],
    executionPhaseRollback:
      "Phase 6K execution gate will own provider-side rollback when it ships.",
  },
  abortCriteria: [
    "any_raw_secret_exposure",
    "provider_call_attempted_true",
    "external_call_will_be_made_true",
    "live_execution_allowed_true",
    "real_customer_data_allowed_true",
    "amount_paise_exceeds_max_100",
    "missing_idempotency_key",
    "kill_switch_disabled_unexpectedly",
    "real_money_true",
  ],
  verificationChecklist: [
    { key: "dryRun", expected: true },
    { key: "providerCallAllowed", expected: false },
    { key: "externalCallWillBeMade", expected: false },
    { key: "externalCallWasMade", expected: false },
    { key: "providerCallAttempted", expected: false },
    { key: "realMoney", expected: false },
    { key: "realCustomerDataAllowed", expected: false },
    { key: "amountPaiseAtMost", expected: 100 },
    { key: "idempotencyKeyPresent", expected: true },
    { key: "payloadHashPresent", expected: true },
    { key: "killSwitchActive", expected: true },
  ],
  blockers: [],
  warnings: [
    "Phase 6J never calls a provider, never mutates business records, and never exposes raw secrets.",
  ],
  nextPhase: "phase_6k_single_internal_razorpay_test_mode_execution_gate",
  requestedBy: null,
  approvedBy: null,
  rejectedBy: null,
  archivedBy: null,
  approvedAt: null,
  rejectedAt: null,
  archivedAt: null,
  metadata: {
    phase: "6J",
    reason: "demo",
    implementationTargetInPhase6J: true,
  },
  createdAt: "2026-05-02T13:00:00.000000+00:00",
  updatedAt: "2026-05-02T13:00:00.000000+00:00",
  nextAction: "validate_provider_test_plan",
};

export const SAAS_PROVIDER_TEST_PLAN_READINESS: Record<string, unknown> = {
  organization: { id: 1, code: "nirogidhara", name: "Nirogidhara Private Limited" },
  policyVersion: "phase6j.v1",
  phase6jImplementationTargets: ["razorpay.create_order"],
  policies: [
    {
      operationType: "razorpay.create_order",
      providerType: "razorpay",
      providerEnvironment: "test",
      realMoney: false,
      realCustomerDataAllowed: false,
      externalProviderCallAllowedInPhase6J: false,
      providerCallAllowed: false,
      approvalRequired: true,
      liveGateRequired: true,
      killSwitchMustRemainEnabled: true,
      idempotencyRequired: true,
      webhookRequiredForFutureExecution: true,
      syntheticPayloadRequired: true,
      safeAmountOnly: true,
      maxTestAmountPaise: 100,
      currency: "INR",
      nextPhaseForExecution:
        "phase_6k_single_internal_razorpay_test_mode_execution_gate",
      rollbackRequired: true,
      auditRequired: true,
      implementationTargetInPhase6J: true,
      notes:
        "Razorpay test-mode create_order is the Phase 6J target. Phase 6J only prepares + validates the plan; no Razorpay API call is made.",
      requiredEnvKeys: ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"],
      optionalEnvKeys: ["RAZORPAY_WEBHOOK_SECRET"],
      requiredConfigKeys: [],
      policyVersion: "phase6j.v1",
      metadata: {},
    },
  ],
  planCount: 1,
  preparedCount: 1,
  validatedCount: 0,
  approvedCount: 0,
  archivedCount: 0,
  blockedCount: 0,
  providerCallAttemptedCount: 0,
  externalCallMadeCount: 0,
  latestPlan: _PROVIDER_TEST_PLAN,
  plans: [_PROVIDER_TEST_PLAN],
  killSwitchActive: true,
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  dryRun: true,
  providerCallAllowed: false,
  externalCallWillBeMade: false,
  externalCallWasMade: false,
  providerCallAttempted: false,
  safeToStartPhase6K: false,
  blockers: [],
  warnings: [
    "Phase 6J never calls a provider, never mutates business records, and never exposes raw secrets.",
    "Razorpay test-mode credentials must be present before Phase 6K can open.",
  ],
  nextAction: "validate_provider_test_plan",
};

// ---------- Phase 6K - Single Internal Razorpay Test-Mode Execution Gate ----------

export const SAAS_PROVIDER_EXECUTION_READINESS: Record<string, unknown> = {
  organization: { id: 1, code: "nirogidhara", name: "Nirogidhara Private Limited" },
  policyVersion: "phase6k.v1",
  envReadiness: {
    envFlag: "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
    envFlagPresent: false,
    envFlagEnabled: false,
    razorpayKeyIdPresent: false,
    razorpayKeyMode: "missing",
    razorpayKeyIdMasked: "",
    razorpayKeySecretPresent: false,
    razorpayWebhookSecretPresent: false,
    isTestKey: false,
    isLiveKey: false,
  },
  killSwitchActive: true,
  latestApprovedPlan: null,
  executionAttemptCount: 0,
  successfulExecutionCount: 0,
  failedExecutionCount: 0,
  blockedExecutionCount: 0,
  rolledBackExecutionCount: 0,
  archivedExecutionCount: 0,
  providerCallAttemptedCount: 0,
  externalCallMadeCount: 0,
  businessMutationCount: 0,
  latestAttempt: null,
  attempts: [],
  policy: {
    operationType: "razorpay.create_order",
    providerType: "razorpay",
    providerEnvironment: "test",
    allowedInPhase6K: true,
    amountPaise: 100,
    currency: "INR",
    realMoney: false,
    realCustomerDataAllowed: false,
    syntheticPayloadRequired: true,
    approvedProviderTestPlanRequired: true,
    idempotencyRequired: true,
    explicitCliConfirmationRequired: true,
    envFlagRequired: true,
    envFlagName: "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
    apiExecutionAllowed: false,
    frontendExecutionAllowed: false,
    maxExecutionsPerApprovedPlan: 1,
    safeResponseSummaryOnly: true,
    businessMutationAllowed: false,
    paymentLinkCreationAllowed: false,
    captureAllowed: false,
    customerNotificationAllowed: false,
    requiredEnvKeys: ["PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"],
    nextPhaseAfterSuccess: "phase_6l_razorpay_test_execution_audit_review_and_webhook_readiness",
    notes:
      "Razorpay test-mode create_order is the ONLY Phase 6K execution target. Synthetic synthetic payload, no customer data, no payment link, no capture, no business mutation.",
    policyVersion: "phase6k.v1",
  },
  runtimeSource: "env_config",
  perOrgRuntimeEnabled: false,
  safeToRunPhase6KExecution: false,
  blockers: [
    "no_approved_provider_test_plan_available",
    "env_flag_PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED_must_be_true",
  ],
  warnings: [
    "Phase 6K runs at most ONE Razorpay test create_order per approved plan. No customer data, no payment link, no capture, no business mutation.",
    "Razorpay test order remains in the test dashboard; no real money / customer impact.",
  ],
  nextAction: "fix_provider_execution_blockers",
};

// ---------- Phase 6L - Razorpay Test Execution Audit Review + Webhook Readiness ----------

export const SAAS_RAZORPAY_AUDIT_REVIEW: Record<string, unknown> = {
  passed: true,
  executionId: "pex_demo_phase6l",
  planId: "ptp_demo_phase6j",
  providerType: "razorpay",
  operationType: "razorpay.create_order",
  providerEnvironment: "test",
  status: "rolled_back",
  providerObjectId: "order_demo_phase6l",
  providerStatus: "created",
  amountPaise: 100,
  currency: "INR",
  rollbackStatus: "completed",
  envSnapshot: {
    envFlagEnabled: false,
    razorpayKeyMode: "test",
    razorpayKeyIdMasked: "rzp_test_***demo",
    razorpayWebhookSecretPresent: true,
  },
  invariantResults: [
    { key: "providerCallAttempted", expected: true, actual: true, passed: true },
    { key: "externalCallWasMade", expected: true, actual: true, passed: true },
    { key: "businessMutationWasMade", expected: false, actual: false, passed: true },
    { key: "paymentLinkCreated", expected: false, actual: false, passed: true },
    { key: "paymentCaptured", expected: false, actual: false, passed: true },
    { key: "customerNotificationSent", expected: false, actual: false, passed: true },
    { key: "realMoney", expected: false, actual: false, passed: true },
    { key: "realCustomerDataAllowed", expected: false, actual: false, passed: true },
    { key: "rollbackStatus", expected: "completed", actual: "completed", passed: true },
    { key: "providerObjectIdPresent", expected: true, actual: true, passed: true },
  ],
  auditEventCount: 4,
  auditEvents: [
    {
      id: 1001,
      kind: "runtime.provider_execution.prepared",
      tone: "info",
      createdAt: "2026-05-03T10:00:00.000000+00:00",
      text: "Provider execution prepared",
      payloadKeys: ["execution_id", "plan_id", "status"],
    },
    {
      id: 1002,
      kind: "runtime.provider_execution.started",
      tone: "info",
      createdAt: "2026-05-03T10:01:00.000000+00:00",
      text: "Provider execution started",
      payloadKeys: ["execution_id", "plan_id", "status"],
    },
    {
      id: 1003,
      kind: "runtime.provider_execution.succeeded",
      tone: "success",
      createdAt: "2026-05-03T10:01:05.000000+00:00",
      text: "Provider execution succeeded",
      payloadKeys: ["execution_id", "plan_id", "provider_object_id", "status"],
    },
    {
      id: 1004,
      kind: "runtime.provider_execution.rolled_back",
      tone: "warning",
      createdAt: "2026-05-03T10:05:00.000000+00:00",
      text: "Provider execution rolled back",
      payloadKeys: ["execution_id", "plan_id", "status"],
    },
  ],
  safeResponseSummary: {
    id: "order_demo_phase6l",
    status: "created",
    amount: 100,
    currency: "INR",
    receipt: "phase6k_pex_demo_phase6l",
  },
  rawSecretLeakDetected: false,
  blockers: [],
  warnings: [
    "Phase 6L is read-only audit + webhook planning. NEVER calls Razorpay, NEVER mutates business records, NEVER exposes raw secrets.",
  ],
  nextAction: "ready_for_phase_6l_webhook_readiness_planning",
};

export const SAAS_RAZORPAY_WEBHOOK_READINESS: Record<string, unknown> = {
  razorpayKeyMode: "test",
  razorpayKeyIdMasked: "rzp_test_***demo",
  razorpayKeyIdPresent: true,
  razorpayKeySecretPresent: true,
  razorpayWebhookSecretPresent: true,
  envFlagEnabled: false,
  isTestKey: true,
  isLiveKey: false,
  latestSucceededExecutionId: "pex_demo_phase6l",
  latestSucceededProviderObjectId: "order_demo_phase6l",
  latestSucceededRollbackStatus: "completed",
  latestPhase6KArtefactExecutionId: "pex_demo_phase6l",
  phase6KSucceededExecutionCount: 1,
  blockers: [],
  warnings: [
    "Phase 6L is read-only audit + webhook planning. NEVER calls Razorpay, NEVER mutates business records, NEVER exposes raw secrets.",
  ],
  safeToPlanWebhookReadiness: true,
  nextAction: "ready_to_plan_razorpay_webhook_readiness",
};

export const SAAS_RAZORPAY_WEBHOOK_PLAN: Record<string, unknown> = {
  phase: "6L",
  policyVersion: "phase6l.v1",
  summary:
    "Phase 6L Razorpay webhook readiness plan. Test-mode only. No payment / order status mutation in Phase 6L. The actual webhook handler ships in Phase 6M.",
  preconditions: {
    razorpayWebhookSecretMustBePresent: true,
    razorpayKeyMustBeTestMode: true,
    phase6KExecutionMustExist: true,
    phase6KSucceededExecutionMustBeRolledBack: false,
  },
  envReadiness: SAAS_RAZORPAY_WEBHOOK_READINESS,
  endpointDesign: {
    path: "/api/webhooks/razorpay/test/",
    method: "POST",
    csrfExempt: true,
    authentication: "none (Razorpay-IP allowlist + signature)",
    phase6LRegistration: false,
    phase6MRegistration: true,
  },
  signatureVerificationDesign: {
    algorithm: "HMAC-SHA256",
    secretSource: "env: RAZORPAY_WEBHOOK_SECRET",
    header: "X-Razorpay-Signature",
    rawBodyMustBeUsed: true,
    constantTimeCompare: true,
    rejectOnMissingHeader: true,
    rejectOnEmptySecret: true,
    implementationReference:
      "apps.payments.integrations.razorpay_client.verify_webhook_signature",
  },
  idempotencyDesign: {
    key: "x_razorpay_event_id",
    fallbackKey: "sha256(rawBody)",
    storage: "RuntimeWebhookEvent (Phase 6M model — not yet created)",
    uniqueConstraint: true,
    duplicateBehaviour: "ignore_with_audit_log; never re-mutate",
  },
  eventAllowlist: [
    "order.paid",
    "order.notification.delivered",
    "order.notification.failed",
    "payment.authorized",
    "payment.captured",
    "payment.failed",
    "refund.created",
    "refund.processed",
    "refund.failed",
  ],
  eventDenylist: [
    "subscription.activated",
    "subscription.cancelled",
    "subscription.charged",
    "settlement.processed",
    "virtual_account.credited",
    "qr_code.credited",
    "fund_account.validation.completed",
    "payout.processed",
    "payout.failed",
  ],
  replayProtection: {
    windowSeconds: 300,
    rejectOlderThanWindow: true,
    useEventCreatedAt: true,
    audit: "runtime.razorpay_webhook.replay_rejected",
  },
  auditLoggingPlan: {
    kindsToAdd: [
      "runtime.razorpay_webhook.received",
      "runtime.razorpay_webhook.signature_failed",
      "runtime.razorpay_webhook.duplicate_ignored",
      "runtime.razorpay_webhook.replay_rejected",
      "runtime.razorpay_webhook.event_allowed",
      "runtime.razorpay_webhook.event_denied",
      "runtime.razorpay_webhook.processed",
      "runtime.razorpay_webhook.failed",
    ],
    phase6LAuditMutationAllowed: false,
    phase6MAuditMutationAllowed: true,
    payloadHandling: {
      storeRawBody: false,
      storePayloadHash: true,
      storePayloadKeysOnly: true,
      sensitiveKeysToScrub: [
        "card",
        "vpa",
        "upi",
        "bank_account",
        "wallet",
        "email",
        "contact",
        "customer_id",
        "customer",
        "phone",
        "mobile",
        "address",
      ],
    },
  },
  testModeOnlyValidationPlan: {
    razorpayKeyModeMustBeTest: true,
    envFlagPattern: "PHASE6M_RAZORPAY_WEBHOOK_TEST_MODE_ENABLED",
    phase6MWebhookHandlerEnabledByDefault: false,
    phase6MMaxEventsPerRun: 50,
    phase6MEventCanMutateBusinessTables: false,
  },
  businessMutationPolicy: {
    phase6LAllowOrderUpdate: false,
    phase6LAllowPaymentUpdate: false,
    phase6LAllowShipmentUpdate: false,
    phase6LAllowDiscountOfferUpdate: false,
    phase6LAllowCustomerNotification: false,
  },
  blockers: [],
  warnings: [
    "Phase 6L is read-only audit + webhook planning. NEVER calls Razorpay, NEVER mutates business records, NEVER exposes raw secrets.",
  ],
  nextAction: "ready_for_phase_6m_razorpay_webhook_handler_implementation",
  nextPhase: "phase_6m_razorpay_webhook_handler_implementation_test_mode",
};

// ---------- Phase 6M-0 - MCP Gateway Foundation ----------

export const MCP_GATEWAY_READINESS: Record<string, unknown> = {
  mcpEnabled: false,
  transport: "streamable_http",
  publicBaseUrlConfigured: false,
  requireAuth: true,
  readOnlyMode: true,
  writeToolsEnabled: false,
  providerToolsEnabled: false,
  auditEnabled: true,
  maskPii: true,
  tokenTtlSeconds: 3600,
  maxToolCallsPerMinute: 30,
  maxOutputChars: 12000,
  exposeResources: false,
  exposePrompts: false,
  toolCount: 10,
  enabledToolCount: 10,
  writeToolEnabledCount: 0,
  providerToolEnabledCount: 0,
  forbiddenToolsRegisteredCount: 0,
  resourceCount: 7,
  promptCount: 6,
  activeClientCount: 0,
  registeredClientCount: 0,
  recentInvocationCount: 0,
  rawSecretExposureCount: 0,
  fullPiiExposureCount: 0,
  providerCallAttemptedCount: 0,
  businessMutationAttemptedCount: 0,
  enabledScopes: [
    "mcp:system.read",
    "mcp:saas.read",
    "mcp:audit.read",
    "mcp:whatsapp.read",
    "mcp:razorpay.read",
    "mcp:dashboard.read",
    "mcp:agents.read",
    "mcp:tools.invoke.readonly",
  ],
  futureDisabledScopes: [
    "mcp:tools.invoke.write",
    "mcp:tools.invoke.provider",
    "mcp:razorpay.write",
    "mcp:whatsapp.write",
    "mcp:payments.write",
    "mcp:shipments.write",
    "mcp:vapi.write",
    "mcp:campaigns.write",
  ],
  forbiddenTools: [
    "razorpay.create_order",
    "razorpay.capture_payment",
    "razorpay.create_payment_link",
    "whatsapp.send_message",
    "delhivery.create_shipment",
    "vapi.place_call",
    "campaign.start",
    "payment.execute",
    "order.create_live",
    "crm.bulk_update",
    "system.shell",
    "system.sql",
    "system.http_fetch",
  ],
  blockers: [],
  warnings: [],
  safeToEnableReadOnlyMcp: true,
  safeToStartPhase6M: true,
  nextAction: "ready_to_enable_read_only_mcp_when_authorized",
};

export const MCP_SECURITY_POSTURE: Record<string, unknown> = {
  forbiddenToolsRegistered: false,
  writeToolsEnabled: false,
  providerToolsEnabled: false,
  writeToolEnabledCount: 0,
  providerToolEnabledCount: 0,
  authRequired: true,
  rawSecretExposureCount: 0,
  piiExposureCount: 0,
  providerCallAttemptedCount: 0,
  businessMutationAttemptedCount: 0,
  blockers: [],
  warnings: [],
  safe: true,
  nextAction: "phase_6m_0_security_posture_clean",
};

const _MCP_TOOL_FIXTURES = [
  {
    name: "system.get_phase_status",
    title: "Get current phase status",
    category: "system",
    riskLevel: "low",
  },
  {
    name: "system.get_health",
    title: "Get system health summary",
    category: "system",
    riskLevel: "low",
  },
  {
    name: "saas.get_current_org",
    title: "Get masked current organization context",
    category: "saas",
    riskLevel: "low",
  },
  {
    name: "audit.search_events_masked",
    title: "Search recent audit events (masked)",
    category: "audit",
    riskLevel: "medium",
  },
  {
    name: "whatsapp.inspect_auto_reply_gate",
    title: "Inspect WhatsApp auto-reply gate (read-only)",
    category: "whatsapp",
    riskLevel: "medium",
  },
  {
    name: "razorpay.inspect_test_execution_audit",
    title: "Inspect Razorpay Phase 6K execution audit",
    category: "razorpay",
    riskLevel: "medium",
  },
  {
    name: "razorpay.inspect_webhook_readiness",
    title: "Inspect Razorpay webhook readiness",
    category: "razorpay",
    riskLevel: "low",
  },
  {
    name: "razorpay.plan_webhook_readiness",
    title: "Get Razorpay webhook readiness plan",
    category: "razorpay",
    riskLevel: "low",
  },
  {
    name: "dashboard.get_kpis",
    title: "Get safe high-level KPIs (aggregated)",
    category: "dashboard",
    riskLevel: "low",
  },
  {
    name: "agents.get_agent_status",
    title: "Get agent status summary",
    category: "agents",
    riskLevel: "low",
  },
];

export const MCP_TOOLS: Record<string, unknown> = {
  count: _MCP_TOOL_FIXTURES.length,
  readOnlyMode: true,
  writeToolsEnabled: false,
  providerToolsEnabled: false,
  tools: _MCP_TOOL_FIXTURES.map((tool, index) => ({
    id: index + 1,
    name: tool.name,
    title: tool.title,
    description: "Phase 6M-0 read-only tool. No provider call, no mutation.",
    category: tool.category,
    handlerKey: tool.name,
    enabled: true,
    readOnly: true,
    riskLevel: tool.riskLevel,
    requiresAuth: true,
    requiresOrgContext: true,
    requiresHumanApproval: false,
    providerCallAllowed: false,
    businessMutationAllowed: false,
    piiExposureLevel: "none",
    requiredScopes: ["mcp:tools.invoke.readonly"],
    tags: ["phase6m0", "readonly"],
    createdAt: "2026-05-03T17:00:00.000000+00:00",
    updatedAt: "2026-05-03T17:00:00.000000+00:00",
  })),
};

export const MCP_RESOURCES: Record<string, unknown> = {
  count: 1,
  resources: [
    {
      id: 1,
      uri: "nirogidhara://phase/current-status",
      name: "current_phase_status",
      title: "Current phase status",
      description: "Phase 6M-0 read-only resource.",
      mimeType: "application/json",
      enabled: true,
      readOnly: true,
      requiresAuth: true,
      requiredScopes: ["mcp:system.read"],
      piiExposureLevel: "none",
      handlerKey: "system.get_phase_status",
    },
  ],
};

export const MCP_PROMPTS: Record<string, unknown> = {
  count: 1,
  prompts: [
    {
      id: 1,
      name: "ceo_daily_briefing",
      title: "CEO daily briefing prompt",
      description: "Phase 6M-0 read-only prompt template.",
      templatePreview: "You are the Nirogidhara CEO AI briefing assistant…",
      variablesSchema: { type: "object", properties: {} },
      enabled: true,
      requiresAuth: true,
      requiredScopes: ["mcp:dashboard.read", "mcp:audit.read"],
      riskLevel: "low",
    },
  ],
};

export const MCP_INVOCATIONS: Record<string, unknown> = {
  count: 0,
  limit: 25,
  invocations: [],
  providerCallAttempted: false,
  businessMutationAttempted: false,
};

export const MCP_SIMULATION_RESULT: Record<string, unknown> = {
  passed: true,
  status: "succeeded",
  toolName: "system.get_phase_status",
  invocationId: "mcp_inv_demo_phase6m0",
  readOnly: true,
  providerCallAttempted: false,
  businessMutationAttempted: false,
  rawSecretExposed: false,
  fullPiiExposed: false,
  outputTruncated: false,
  durationMs: 12,
  result: {
    currentPhase: "Phase 6M-0 — MCP Gateway Foundation",
    productionUrl: "https://ai.nirogidhara.com",
    mcpEnabled: false,
    readOnlyMode: true,
    writeToolsEnabled: false,
    providerToolsEnabled: false,
  },
  blockers: [],
  warnings: ["Phase 6M-0 read-only foundation."],
  nextAction: "ready_for_phase_6m_1_external_client_auth",
};

// ---------- Phase 6M - Razorpay Webhook Handler (test-mode) ----------

export const SAAS_RAZORPAY_WEBHOOK_HANDLER_READINESS: Record<string, unknown> = {
  phase: "6M",
  webhookTestModeEnabled: false,
  webhookSecretPresent: true,
  businessMutationEnabled: false,
  customerNotificationEnabled: false,
  storeRawPayload: false,
  allowTestEventsOnly: true,
  replayWindowSeconds: 300,
  allowedEvents: [
    "payment.authorized",
    "payment.captured",
    "payment.failed",
    "order.paid",
    "refund.created",
    "refund.processed",
    "payment_link.paid",
    "payment_link.cancelled",
    "payment_link.expired",
  ],
  deniedEvents: [
    "payment.dispute.created",
    "payment.dispute.won",
    "payment.dispute.lost",
    "transfer.processed",
    "payout.processed",
    "subscription.charged",
    "invoice.paid",
    "virtual_account.credited",
    "qr_code.closed",
  ],
  eventCount: 0,
  verifiedEventCount: 0,
  duplicateEventCount: 0,
  blockedEventCount: 0,
  businessMutationCount: 0,
  customerNotificationCount: 0,
  rawSecretExposureCount: 0,
  fullPiiExposureCount: 0,
  safeToReceiveTestWebhooks: false,
  safeToStartPhase6N: false,
  blockers: ["razorpay_webhook_test_mode_disabled"],
  warnings: [],
  nextAction: "fix_razorpay_webhook_handler_blockers",
};

export const SAAS_RAZORPAY_WEBHOOK_EVENTS: Record<string, unknown> = {
  count: 0,
  limit: 25,
  events: [],
  businessMutationWasMade: false,
  customerNotificationSent: false,
  providerCallAttempted: false,
};

// ---------- Phase 6Q — Payment → Order Workflow Safety Gate ----------

const PHASE_6Q_CONTRACT_FIXTURES: Record<string, [string, string, string, string]> = {
  "payment_link.paid": [
    "advance_paid_candidate",
    "payment_reviewed",
    "advance_received_candidate",
    "gate_payment_link_paid_to_order_advance_review",
  ],
  "payment.captured": [
    "captured_candidate",
    "payment_verified",
    "payment_verified_candidate",
    "gate_payment_captured_to_order_payment_verified",
  ],
  "payment.failed": [
    "failed_candidate",
    "payment_failed",
    "payment_failed_candidate",
    "gate_payment_failed_to_order_followup_needed",
  ],
  "payment.authorized": [
    "authorized_candidate",
    "payment_authorized",
    "payment_authorized_candidate",
    "gate_payment_authorized_to_order_review",
  ],
  "order.paid": [
    "paid_candidate",
    "paid",
    "paid_candidate",
    "gate_order_paid_to_order_paid_candidate",
  ],
  "payment_link.cancelled": [
    "cancelled_candidate",
    "payment_link_cancelled",
    "payment_link_cancelled_candidate",
    "gate_payment_link_cancelled_to_order_followup_needed",
  ],
  "payment_link.expired": [
    "expired_candidate",
    "payment_link_expired",
    "payment_link_expired_candidate",
    "gate_payment_link_expired_to_order_followup_needed",
  ],
  "refund.created": [
    "refund_pending_candidate",
    "refund_review",
    "refund_review_candidate",
    "gate_refund_created_to_refund_review",
  ],
  "refund.processed": [
    "refunded_candidate",
    "refund_processed",
    "refund_processed_candidate",
    "gate_refund_processed_to_order_refunded_candidate",
  ],
};

const PHASE_6Q_FORBIDDEN_ACTIONS = [
  "mutate_real_order_status",
  "mutate_real_payment_status",
  "create_or_update_real_shipment",
  "create_or_update_real_discount_offer",
  "mutate_real_customer",
  "mutate_real_lead",
  "send_whatsapp_template",
  "place_vapi_call",
  "call_razorpay_api",
  "create_payment_link",
  "execute_workflow_via_frontend",
  "execute_workflow_via_api_endpoint",
  "approve_gate_via_api_endpoint",
];

const PHASE_6Q_GATE_COUNTS = {
  draft: 0,
  pendingManualReview: 0,
  approvedForFuturePhase6R: 0,
  rejected: 0,
  archived: 0,
  blocked: 0,
  realOrderMutationWasMade: 0,
  realPaymentMutationWasMade: 0,
  shipmentMutationWasMade: 0,
  discountMutationWasMade: 0,
  customerNotificationSent: 0,
  providerCallAttempted: 0,
};

export const SAAS_RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_READINESS: Record<
  string,
  unknown
> = {
  phase: "6Q",
  status: "audit_gate_only",
  latestCompletedPhase: "6P",
  nextPhase: "6R",
  razorpayPaymentOrderWorkflowGateEnabled: false,
  businessMutationEnabled: false,
  customerNotificationEnabled: false,
  providerCallAttempted: false,
  rawPayloadStorageEnabled: false,
  phase6PExecutedCount: 0,
  phase6PRolledBackCount: 0,
  gateCounts: PHASE_6Q_GATE_COUNTS,
  workflowContract: Object.entries(PHASE_6Q_CONTRACT_FIXTURES).map(
    ([eventName, [paymentStatus, orderStatus, orderEffect, action]]) => ({
      razorpayEventName: eventName,
      futurePaymentStatus: paymentStatus,
      futureOrderStatusCandidate: orderStatus,
      futureOrderEffect: orderEffect,
      workflowAction: action,
      workflowMutationAllowedInPhase6Q: false,
      mutationAllowedInFuturePhase6R:
        "only_if_gate_approved_director_signed_off_and_kill_switch_allows",
      manualReviewRequired: true,
      customerNotificationAllowed: false,
      shipmentEffectAllowed: false,
      discountEffectAllowed: false,
      providerCallAllowed: false,
      idempotencyRequired: true,
      rollbackRequired: true,
      blockers: ["phase_6q_audit_gate_only_no_real_business_mutation"],
      notes: [
        "Phase 6Q records the contract; no production-side action fires here.",
      ],
    }),
  ),
  safetyInvariants: {
    realOrderMutationAllowed: false,
    realPaymentMutationAllowed: false,
    shipmentMutationAllowed: false,
    discountOfferMutationAllowed: false,
    customerMutationAllowed: false,
    leadMutationAllowed: false,
    whatsappSendAllowed: false,
    vapiCallAllowed: false,
    razorpayApiInvocationAllowed: false,
    envFlagFlipAllowed: false,
    frontendCanExecutePhase6Q: false,
    apiEndpointCanExecutePhase6Q: false,
    apiEndpointCanApprovePhase6Q: false,
    phase6QRespectsKillSwitch: true,
    phase6QApprovalApplyRealMutation: false,
  },
  manualReviewChecklist: [
    {
      key: "verifyPhase6PSandboxProof",
      description:
        "Phase 6P attempt has executed + rolled_back via CLI; ledger row exists and was restored.",
      automated: true,
    },
    {
      key: "verifyPhase6PSafetyCountersZero",
      description:
        "Phase 6P attempt has all safety counters False (real_order, real_payment, business, notification, provider).",
      automated: true,
    },
    {
      key: "verifyDirectorSignOff",
      description:
        "Manual reviewer sign-off (reason text) recorded on the gate row before approval.",
      automated: false,
    },
  ],
  rollbackPlan: {
    phase: "6Q",
    rollbackTriggers: [
      "approval_observed_to_mutate_real_business_table",
      "real_order_payment_shipment_or_discount_mutation_observed",
    ],
    rollbackSteps: [
      {
        order: 1,
        action: "set_RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED_to_false",
        owner: "operator",
        phase6QEnforced: true,
      },
    ],
    rollbackVerification: [
      "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED == false",
    ],
    phase6QCanExecuteRollback: false,
    rollbackOwnedByOperatorOnly: true,
    rollbackNeverInvokesProviderApi: true,
  },
  forbiddenActions: PHASE_6Q_FORBIDDEN_ACTIONS,
  executionPath: "cli_only",
  frontendCanExecute: false,
  apiEndpointCanExecute: false,
  apiEndpointCanApprove: false,
  maxSafeAmountPaise: 100,
  safeToStartPhase6R: false,
  blockers: [],
  warnings: [
    "Phase 6Q is an audit-only Payment → Order workflow safety gate. It NEVER mutates real Order / Payment / Shipment / DiscountOfferLog / Customer / Lead / WhatsAppMessage rows. It NEVER calls Razorpay, NEVER sends a customer notification, NEVER flips an env flag.",
  ],
  nextAction:
    "complete_at_least_one_phase_6p_execute_and_rollback_cycle",
  recentGates: [],
};

export const SAAS_RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATES: Record<
  string,
  unknown
> = {
  phase: "6Q",
  limit: 25,
  counts: PHASE_6Q_GATE_COUNTS,
  items: [],
  executionPath: "cli_only",
  frontendCanExecute: false,
  apiEndpointCanExecute: false,
  apiEndpointCanApprove: false,
  realOrderMutationWasMade: false,
  realPaymentMutationWasMade: false,
  shipmentMutationWasMade: false,
  discountMutationWasMade: false,
  customerNotificationSent: false,
  providerCallAttempted: false,
};

// ---------- Phase 6P — Controlled Internal Paid-Status Mutation Test ----------

const PHASE_6P_EVENT_MAPPING_FIXTURES: Record<string, [string, string]> = {
  "payment_link.paid": ["paid", "advance_paid_candidate"],
  "payment.captured": ["captured", "payment_verified_candidate"],
  "payment.failed": ["failed", "payment_failed_candidate"],
  "payment.authorized": ["authorized", "payment_authorized_candidate"],
  "order.paid": ["paid", "paid_candidate"],
  "payment_link.cancelled": ["cancelled", "payment_link_cancelled_candidate"],
  "payment_link.expired": ["expired", "payment_link_expired_candidate"],
  "refund.created": ["refund_pending", "refund_review_candidate"],
  "refund.processed": ["refunded", "refund_processed_candidate"],
};

const PHASE_6P_FORBIDDEN_ACTIONS = [
  "mutate_real_order_status",
  "mutate_real_payment_status",
  "create_or_update_real_shipment",
  "create_or_update_real_discount_offer",
  "mutate_real_customer",
  "mutate_real_lead",
  "send_whatsapp_template",
  "send_freeform_whatsapp",
  "place_vapi_call",
  "call_razorpay_api",
  "create_payment_link",
  "capture_razorpay_payment",
  "refund_razorpay_payment",
  "execute_webhook_replay",
  "enable_business_mutation_env_flag",
  "execute_phase_6p_via_frontend",
  "execute_phase_6p_via_api_endpoint",
];

const PHASE_6P_ATTEMPT_COUNTS = {
  prepared: 0,
  blocked: 0,
  executed: 0,
  rolledBack: 0,
  failed: 0,
  archived: 0,
  everExecuted: 0,
  everRolledBack: 0,
  businessMutationWasMade: 0,
  realOrderMutationWasMade: 0,
  realPaymentMutationWasMade: 0,
  customerNotificationSent: 0,
  providerCallAttempted: 0,
};

const PHASE_6P_LEDGER_COUNTS = {
  totalLedgers: 0,
  rolledBackLedgers: 0,
  businessMutationWasMade: 0,
  realOrderMutationWasMade: 0,
  realPaymentMutationWasMade: 0,
  customerNotificationSent: 0,
  providerCallAttempted: 0,
};

export const SAAS_RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_READINESS: Record<
  string,
  unknown
> = {
  phase: "6P",
  status: "sandbox_ledger_only",
  latestCompletedPhase: "6O",
  nextPhase: "6Q",
  razorpaySandboxPaidStatusMutationEnabled: false,
  businessMutationEnabled: false,
  customerNotificationEnabled: false,
  providerCallAttempted: false,
  rawPayloadStorageEnabled: false,
  approvedPhase6OReviewCount: 0,
  attemptCounts: PHASE_6P_ATTEMPT_COUNTS,
  ledgerCounts: PHASE_6P_LEDGER_COUNTS,
  eventMappings: Object.entries(PHASE_6P_EVENT_MAPPING_FIXTURES).map(
    ([eventName, [paymentStatus, orderEffect]]) => ({
      razorpayEventName: eventName,
      sandboxPaymentStatus: paymentStatus,
      sandboxOrderEffect: orderEffect,
      realOrderMutationAllowedInPhase6P: false,
      realPaymentMutationAllowedInPhase6P: false,
      customerNotificationAllowed: false,
      providerCallAllowed: false,
      shipmentEffectAllowed: false,
      discountEffectAllowed: false,
      idempotencyRequired: true,
      rollbackRequired: true,
      executionPath: "cli_only",
      blockers: ["phase_6p_sandbox_ledger_only"],
    }),
  ),
  safetyInvariants: {
    realOrderMutationAllowed: false,
    realPaymentMutationAllowed: false,
    shipmentMutationAllowed: false,
    discountOfferMutationAllowed: false,
    customerMutationAllowed: false,
    leadMutationAllowed: false,
    whatsappSendAllowed: false,
    vapiCallAllowed: false,
    razorpayApiInvocationAllowed: false,
    envFlagFlipAllowed: false,
    frontendCanExecutePhase6P: false,
    apiEndpointCanExecutePhase6P: false,
    phase6PRespectsKillSwitch: true,
    phase6PApprovalApplyRealMutation: false,
  },
  forbiddenActions: PHASE_6P_FORBIDDEN_ACTIONS,
  executionPath: "cli_only",
  frontendCanExecute: false,
  apiEndpointCanExecute: false,
  maxSafeAmountPaise: 100,
  safeToStartPhase6Q: false,
  blockers: [],
  warnings: [
    "Phase 6P is a controlled, sandbox-only paid-status mutation test. It NEVER mutates real Order / Payment / Shipment / DiscountOfferLog / Customer / Lead / WhatsAppMessage rows. It NEVER calls Razorpay, NEVER sends a customer notification, NEVER flips an env flag. Execution is CLI-only — no frontend or API endpoint can dispatch a Phase 6P mutation.",
  ],
  nextAction: "approve_at_least_one_phase6o_review_before_running_phase_6p",
  recentAttempts: [],
  recentLedgers: [],
};

export const SAAS_RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ATTEMPTS: Record<
  string,
  unknown
> = {
  phase: "6P",
  limit: 25,
  counts: PHASE_6P_ATTEMPT_COUNTS,
  items: [],
  ledgerCounts: PHASE_6P_LEDGER_COUNTS,
  ledgerItems: [],
  executionPath: "cli_only",
  frontendCanExecute: false,
  apiEndpointCanExecute: false,
  businessMutationWasMade: false,
  realOrderMutationWasMade: false,
  realPaymentMutationWasMade: false,
  customerNotificationSent: false,
  providerCallAttempted: false,
};

// ---------- Phase 6O — Razorpay Sandbox Status Mapping + Manual Review ----------

const PHASE_6O_EVENT_NAMES = [
  "payment_link.paid",
  "payment.captured",
  "payment.failed",
  "payment.authorized",
  "order.paid",
  "payment_link.cancelled",
  "payment_link.expired",
  "refund.created",
  "refund.processed",
];

const PHASE_6O_FORBIDDEN_ACTIONS = [
  "mark_order_paid",
  "mark_payment_captured",
  "create_payment_link",
  "capture_razorpay_payment",
  "refund_razorpay_payment",
  "send_whatsapp_template",
  "send_freeform_whatsapp",
  "place_vapi_call",
  "create_or_update_shipment",
  "create_or_update_discount_offer",
  "execute_webhook_replay",
  "enable_business_mutation_env_flag",
];

const PHASE_6O_REVIEW_COUNTS = {
  proposed: 0,
  pendingManualReview: 0,
  approvedForFuturePhase6P: 0,
  rejected: 0,
  archived: 0,
  blocked: 0,
  businessMutationWasMade: 0,
  customerNotificationSent: 0,
  providerCallAttempted: 0,
};

export const SAAS_RAZORPAY_SANDBOX_STATUS_MAPPING_READINESS: Record<
  string,
  unknown
> = {
  phase: "6O",
  status: "sandbox_review_only",
  latestCompletedPhase: "6N",
  nextPhase: "6P",
  businessMutationEnabled: false,
  customerNotificationEnabled: false,
  providerCallAttempted: false,
  rawPayloadStorageEnabled: false,
  razorpaySandboxStatusMappingEnabled: false,
  phase6MWebhookTestModeEnabled: false,
  phase6MVerifiedEventCount: 0,
  phase6MBusinessMutationCount: 0,
  phase6MCustomerNotificationCount: 0,
  phase6MRawSecretExposureCount: 0,
  phase6MFullPiiExposureCount: 0,
  reviewCounts: PHASE_6O_REVIEW_COUNTS,
  eventMappings: PHASE_6O_EVENT_NAMES.map((name) => ({
    razorpayEventName: name,
    futureSandboxPaymentStatus: "pending",
    futureSandboxOrderEffect: "no_change",
    proposedReviewAction: `review_${name.replace(".", "_")}_for_synthetic_order`,
    manualReviewRequired: true,
    mutationAllowedInPhase6O: false,
    mutationAllowedInFuturePhase6P:
      "only_if_synthetic_review_approved_and_director_signed_off",
    customerNotificationAllowed: false,
    shipmentEffectAllowed: false,
    discountEffectAllowed: false,
    idempotencyRequired: true,
    rollbackRequired: true,
    blockers: ["phase_6o_sandbox_review_only_no_mutation_path"],
    notes: ["Sandbox-only acknowledgement; production rows stay untouched."],
  })),
  safetyInvariants: {
    businessMutationEnabled: false,
    customerNotificationEnabled: false,
    rawPayloadStorageEnabled: false,
    providerCallAllowed: false,
    razorpayApiInvocationAllowed: false,
    whatsappSendAllowed: false,
    vapiCallAllowed: false,
    envFlagFlipAllowed: false,
    phase6OPathCanMutateProductionRecord: false,
    phase6OPathCanCreateShipment: false,
    phase6OPathCanCreateDiscountOffer: false,
    phase6OPathCanSendCustomerNotification: false,
    phase6OPathCanCallRazorpay: false,
    phase6OPathCanFlipEnvFlag: false,
    phase6OPathCanWriteToOrderTable: false,
    phase6OPathCanWriteToPaymentTable: false,
    phase6OPathRespectsKillSwitch: true,
    approvalAppliesMutation: false,
  },
  manualReviewChecklist: [
    {
      key: "verifyPhase6MEventIsVerifiedAndSafe",
      description:
        "Source RazorpayWebhookEvent has signature_valid=True, replay_window_valid=True, idempotency_status=first_seen, safety counters all zero.",
      automated: true,
    },
    {
      key: "verifyEnvFlagsLockedOff",
      description:
        "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED, RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED and RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD all remain false.",
      automated: true,
    },
    {
      key: "verifySyntheticReferenceOnly",
      description:
        "Provider order/payment/payment-link ids are synthetic test markers. Amount must be ≤ 100 paise.",
      automated: true,
    },
    {
      key: "verifyDirectorSignOff",
      description:
        "Written Director sign-off recorded in the Master Event Ledger before any Phase 6P sandbox mutation is rehearsed.",
      automated: false,
    },
  ],
  rollbackPlan: {
    phase: "6O",
    rollbackTriggers: [
      "approval_button_click_observed_to_mutate_business_table",
      "any_real_order_payment_shipment_or_discount_mutation_observed",
    ],
    rollbackSteps: [
      {
        order: 1,
        action: "set_RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED_to_false",
        owner: "operator",
        phase6OEnforced: true,
      },
      {
        order: 2,
        action: "mark_open_reviews_archived_with_rollback_reason",
        owner: "operator",
        phase6OEnforced: true,
      },
    ],
    rollbackVerification: [
      "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED == false",
    ],
    phase6OCanExecuteRollback: false,
    rollbackOwnedByOperatorOnly: true,
    rollbackNeverInvokesProviderApi: true,
  },
  forbiddenActions: PHASE_6O_FORBIDDEN_ACTIONS,
  maxSafeAmountPaise: 100,
  safeToStartPhase6P: false,
  blockers: [],
  warnings: [
    "Phase 6O is sandbox-review-only. NEVER mutates Order/Payment/Shipment/DiscountOfferLog, NEVER sends customer notification, NEVER calls Razorpay, NEVER flips env flags. Approving a review only marks it approved_for_future_phase6p — Phase 6P will own any sandbox-only mutation against synthetic test orders.",
  ],
  nextAction: "approve_at_least_one_phase6o_review_for_future_phase6p",
  recentReviews: [],
};

export const SAAS_RAZORPAY_SANDBOX_STATUS_REVIEWS: Record<string, unknown> = {
  phase: "6O",
  limit: 25,
  counts: PHASE_6O_REVIEW_COUNTS,
  items: [],
  businessMutationWasMade: false,
  customerNotificationSent: false,
  providerCallAttempted: false,
};

// ---------- Phase 6N — Razorpay Business-Mutation Sandbox Plan ----------

const PHASE_6N_EVENT_NAMES = [
  "payment_link.paid",
  "payment.captured",
  "payment.failed",
  "payment.authorized",
  "order.paid",
  "payment_link.cancelled",
  "payment_link.expired",
  "refund.created",
  "refund.processed",
];

const PHASE_6N_FORBIDDEN_ACTIONS = [
  "call_razorpay_api",
  "create_razorpay_payment_link",
  "capture_razorpay_payment",
  "refund_razorpay_payment",
  "mutate_order_status",
  "mutate_payment_status",
  "create_or_update_shipment",
  "create_or_update_discount_offer",
  "send_whatsapp_template",
  "send_freeform_whatsapp",
  "place_vapi_call",
  "enable_business_mutation_env_flag",
  "enable_customer_notification_env_flag",
  "enable_raw_payload_storage_env_flag",
];

export const SAAS_RAZORPAY_BUSINESS_MUTATION_SANDBOX_READINESS: Record<
  string,
  unknown
> = {
  phase: "6N",
  status: "planning_only",
  latestCompletedPhase: "6M",
  nextPhase: "6O",
  businessMutationEnabled: false,
  customerNotificationEnabled: false,
  rawPayloadStorageEnabled: false,
  phase6MWebhookTestModeEnabled: false,
  phase6MVerifiedEventCount: 0,
  phase6MBusinessMutationCount: 0,
  phase6MCustomerNotificationCount: 0,
  phase6MRawSecretExposureCount: 0,
  phase6MFullPiiExposureCount: 0,
  planComplete: true,
  eventMappingCount: 9,
  manualReviewChecklistSize: 8,
  rollbackStepCount: 7,
  safetyCountersZero: true,
  phase6MFlagsLockedOff: true,
  safeToStartPhase6O: true,
  blockers: [],
  warnings: [
    "Phase 6N is planning-only. NEVER calls Razorpay, NEVER mutates Order / Payment / Shipment / DiscountOfferLog, NEVER notifies a customer, NEVER changes env flags.",
  ],
  nextAction:
    "ready_for_phase_6o_sandbox_payment_status_mapping_and_manual_review",
  requiredEnvDefaults: {
    RAZORPAY_WEBHOOK_TEST_MODE_ENABLED: false,
    RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED: false,
    RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED: false,
    RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD: false,
  },
  forbiddenActions: PHASE_6N_FORBIDDEN_ACTIONS,
};

export const SAAS_RAZORPAY_BUSINESS_MUTATION_SANDBOX_PLAN: Record<
  string,
  unknown
> = {
  phase: "6N",
  policyVersion: "phase6n.v1",
  status: "planning_only",
  latestCompletedPhase: "6M",
  nextPhase: "6O",
  businessMutationEnabled: false,
  customerNotificationEnabled: false,
  rawPayloadStorageEnabled: false,
  safeToStartPhase6O: true,
  blockers: [],
  warnings: [
    "Phase 6N is planning-only. NEVER calls Razorpay, NEVER mutates Order / Payment / Shipment / DiscountOfferLog, NEVER notifies a customer, NEVER changes env flags.",
  ],
  nextAction:
    "ready_for_phase_6o_sandbox_payment_status_mapping_and_manual_review",
  summary:
    "Phase 6N is the planning + readiness layer for a future Phase 6O sandbox-only mutation path against synthetic test orders.",
  eventMappings: PHASE_6N_EVENT_NAMES.map((name) => ({
    razorpayEventName: name,
    futureSandboxPaymentStatus: "pending",
    futureSandboxOrderEffect: "no_change",
    mutationAllowedInPhase6N: false,
    mutationAllowedInFuturePhase6O: "only_if_synthetic_and_approved",
    manualReviewRequired: true,
    customerNotificationAllowed: false,
    shipmentEffectAllowed: false,
    discountEffectAllowed: false,
    idempotencyRequired: true,
    rollbackRequired: true,
    blockers: ["phase_6n_planning_only_no_mutation_path"],
    notes: "Sandbox-only acknowledgement; production rows stay untouched.",
  })),
  syntheticEligibilityPolicy: {
    providerEnvironmentMustBeTest: true,
    razorpayKeyModeMustBeTest: true,
    eventMustComeFromPhase6MVerifiedHandler: true,
    sourceEventIdRequired: true,
    signatureValidRequired: true,
    replayWindowValidRequired: true,
    idempotencyFirstSeenRequired: true,
    eventMustBeAllowlisted: true,
    eventMustNotBeDenylisted: true,
    orderPaymentPaymentLinkReferenceMustBeSynthetic: true,
    noRealCustomerData: true,
    noFullPhoneEmailAddressInPayload: true,
    noCustomerNotification: true,
    noShipmentCreation: true,
    noDiscountMutation: true,
    manualReviewBeforeMutation: true,
    rollbackPathDefined: true,
    auditRequiredBeforeAndAfterFutureMutation: true,
  },
  manualReviewChecklist: [
    {
      key: "verifyPhase6MHandlerSafetyCountersZero",
      description:
        "Confirm business_mutation_count and customer_notification_count are 0 across every RazorpayWebhookEvent.",
      automated: true,
    },
    {
      key: "verifyEnvFlagsLockedOff",
      description:
        "Confirm RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED, RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED, RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD are all false.",
      automated: true,
    },
    {
      key: "verifyTestKeyMode",
      description:
        "Razorpay key id must start with rzp_test. Live credentials disqualify Phase 6N and Phase 6O.",
      automated: true,
    },
    {
      key: "verifySyntheticReferenceOnly",
      description:
        "Every webhook event reviewed must reference a synthetic order id; real production order ids must be refused.",
      automated: false,
    },
    {
      key: "verifyDirectorSignOff",
      description:
        "Written Director sign-off recorded in the Master Event Ledger before any Phase 6O sandbox mutation.",
      automated: false,
    },
  ],
  rollbackPlan: {
    phase: "6N",
    rollbackTriggers: [
      "any_real_order_payment_shipment_or_discount_mutation_observed",
      "any_customer_notification_observed",
      "raw_secret_or_full_pii_exposure_observed",
    ],
    rollbackSteps: [
      {
        order: 1,
        action: "set_RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED_to_false",
        owner: "operator",
        phase6NEnforced: true,
      },
      {
        order: 2,
        action: "set_RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED_to_false",
        owner: "operator",
        phase6NEnforced: true,
      },
      {
        order: 3,
        action: "recreate_backend_worker_beat_containers_to_pickup_envs",
        owner: "operator",
        phase6NEnforced: false,
      },
    ],
    rollbackVerification: [
      "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED == false",
      "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED == false",
      "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD == false",
    ],
    phase6NCanExecuteRollback: false,
    rollbackOwnedByOperatorOnly: true,
    rollbackNeverInvokesProviderApi: true,
  },
  safetyInvariants: {
    businessMutationEnabled: false,
    customerNotificationEnabled: false,
    rawPayloadStorageEnabled: false,
    providerCallAllowed: false,
    razorpayApiInvocationAllowed: false,
    whatsappSendAllowed: false,
    vapiCallAllowed: false,
    envFlagFlipAllowed: false,
    phase6NPathCanMutateProductionRecord: false,
    phase6NPathCanCreateShipment: false,
    phase6NPathCanCreateDiscountOffer: false,
    phase6NPathCanSendCustomerNotification: false,
    phase6NPathCanCallRazorpay: false,
    phase6NPathCanFlipEnvFlag: false,
    phase6NPathRespectsKillSwitch: true,
  },
  forbiddenActions: PHASE_6N_FORBIDDEN_ACTIONS,
  requiredEnvDefaults: {
    RAZORPAY_WEBHOOK_TEST_MODE_ENABLED: false,
    RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED: false,
    RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED: false,
    RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD: false,
  },
  auditPlan: [
    {
      kind: "razorpay.sandbox_plan.inspected",
      tone: "info",
      emittedBy: "manage.py inspect_razorpay_business_mutation_sandbox_plan",
      payloadKeys: [
        "phase",
        "status",
        "eventMappingCount",
        "manualReviewChecklistSize",
        "businessMutationEnabled",
      ],
      neverIncludes: [
        "razorpayKeySecret",
        "razorpayWebhookSecret",
        "rawWebhookPayload",
        "customerEmail",
        "customerPhone",
      ],
    },
    {
      kind: "razorpay.sandbox_readiness.inspected",
      tone: "info",
      emittedBy:
        "manage.py inspect_razorpay_business_mutation_sandbox_readiness",
      payloadKeys: ["phase", "safeToStartPhase6O", "nextAction"],
      neverIncludes: ["razorpayKeySecret", "razorpayWebhookSecret"],
    },
  ],
};
