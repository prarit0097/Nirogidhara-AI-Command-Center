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
  .map((a) => ({ name: a.name, reward: a.reward, penalty: a.penalty, net: a.reward - a.penalty }))
  .sort((a, b) => b.net - a.net);

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