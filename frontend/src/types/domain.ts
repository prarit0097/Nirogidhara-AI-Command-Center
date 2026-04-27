export type RiskLevel = "Low" | "Medium" | "High" | "Critical";

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

export interface Lead {
  id: string;
  name: string;
  phone: string;
  state: string;
  city: string;
  language: string;
  source: string;
  campaign: string;
  productInterest: string;
  status: LeadStatus;
  quality: "Hot" | "Warm" | "Cold";
  qualityScore: number;
  assignee: string;
  duplicate: boolean;
  createdAt: string;
}

export interface Customer {
  id: string;
  leadId: string;
  name: string;
  phone: string;
  state: string;
  city: string;
  language: string;
  productInterest: string;
  diseaseCategory: string;
  lifestyleNotes: string;
  objections: string[];
  aiSummary: string;
  riskFlags: string[];
  reorderProbability: number;
  satisfaction: number;
  consent: { call: boolean; whatsapp: boolean; marketing: boolean };
}

export interface Order {
  id: string;
  customerName: string;
  phone: string;
  product: string;
  quantity: number;
  amount: number;
  discountPct: number;
  advancePaid: boolean;
  advanceAmount: number;
  paymentStatus: "Paid" | "Partial" | "Pending" | "Failed";
  state: string;
  city: string;
  rtoRisk: Exclude<RiskLevel, "Critical">;
  rtoScore: number;
  agent: string;
  stage: OrderStage;
  awb: string | null;
  ageHours: number;
  createdAt: string;
}

export interface CallTranscriptLine {
  who: "AI" | "Customer" | string;
  text: string;
}

export type CallProvider = "manual" | "vapi";

export type CallHandoffFlag =
  | "medical_emergency"
  | "side_effect_complaint"
  | "very_angry_customer"
  | "human_requested"
  | "low_confidence"
  | "legal_or_refund_threat";

export interface Call {
  id: string;
  leadId: string;
  customer: string;
  phone: string;
  agent: string;
  language: string;
  duration: string;
  status: "Live" | "Queued" | "Completed" | "Missed" | "Failed";
  sentiment: "Positive" | "Neutral" | "Hesitant" | "Annoyed";
  scriptCompliance: number;
  paymentLinkSent: boolean;
  /** "manual" for human callers, "vapi" for AI voice (Phase 2D). */
  provider?: CallProvider;
  /** Vapi external call id, used to correlate webhook events. */
  providerCallId?: string;
  /** Post-call summary populated by analysis.completed. */
  summary?: string;
  recordingUrl?: string;
  /** Compliance / safety triggers detected by Vapi or our analyser. */
  handoffFlags?: CallHandoffFlag[];
}

export interface CallTriggerPayload {
  leadId: string;
  /** Defaults to "sales_call" if omitted. */
  purpose?: string;
}

export interface CallTriggerResponse {
  callId: string;
  provider: CallProvider;
  status: string;
  leadId: string;
  providerCallId: string;
}

export interface ActiveCall {
  id: string;
  customer: string;
  phone: string;
  agent: string;
  language: string;
  duration: string;
  stage: string;
  sentiment: string;
  scriptCompliance: number;
  transcript: CallTranscriptLine[];
  detectedObjections: string[];
  approvedClaimsUsed: string[];
}

export interface Payment {
  id: string;
  orderId: string;
  customer: string;
  amount: number;
  gateway: "Razorpay" | "PayU";
  status: "Paid" | "Pending" | "Failed" | "Refunded" | "Cancelled" | "Expired" | "Partial";
  type: "Advance" | "Full";
  time: string;
  gatewayReferenceId?: string;
  paymentUrl?: string;
}

export interface Shipment {
  awb: string;
  orderId: string;
  customer: string;
  state: string;
  city: string;
  status: string;
  eta: string;
  courier: string;
  /** Customer-facing tracking URL — populated by Delhivery in test/live mode. */
  trackingUrl?: string;
  /** "NDR" / "RTO" surfaced on the RTO board when set by the tracking webhook. */
  riskFlag?: string;
  timeline: WorkflowStep[];
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  status: "active" | "warning" | "paused";
  health: number;
  reward: number;
  penalty: number;
  lastAction: string;
  critical: boolean;
  group: string;
}

export interface RewardPenalty {
  name: string;
  reward: number;
  penalty: number;
  net: number;
}

export interface Claim {
  product: string;
  approved: string[];
  disallowed: string[];
  doctor: string;
  compliance: string;
  version: string;
}

export interface LearningRecording {
  id: string;
  agent: string;
  duration: string;
  date: string;
  stage: string;
  qa: number | null;
  compliance: string;
  outcome: string;
}

export interface CaioAudit {
  agent: string;
  issue: string;
  severity: "Critical" | "High" | "Medium" | "Low";
  suggestion: string;
  status: string;
}

export interface CeoRecommendation {
  id: string;
  title: string;
  reason: string;
  impact: string;
  requires: string;
}

export interface CeoBriefing {
  date: string;
  headline: string;
  summary: string;
  recommendations: CeoRecommendation[];
  alerts: string[];
}

export interface DashboardMetric {
  value: number;
  deltaPct?: number;
  completed?: number;
  pending?: number;
  alerts?: number;
}

export type DashboardMetrics = Record<string, DashboardMetric>;

export interface ActivityEvent {
  time: string;
  icon: string;
  text: string;
  tone: "success" | "info" | "warning" | "danger";
}

export interface WorkflowStep {
  step: string;
  at?: string;
  done?: boolean;
}

export interface KPITrend {
  d?: string;
  stage?: string;
  state?: string;
  product?: string;
  value?: number;
  revenue?: number;
  profit?: number;
  leads?: number;
  orders?: number;
  delivered?: number;
  rtoPct?: number;
  rto?: number;
  netProfit?: number;
}

// ----- Phase 2A — write payloads + extra response shapes -----

export type RescueChannel = "AI Call" | "Human Call" | "WhatsApp" | "SMS";
export type RescueOutcome =
  | "Pending"
  | "Rescue Call Done"
  | "Convinced"
  | "Returning"
  | "No Response";

export interface RescueAttempt {
  id: string;
  orderId: string;
  channel: RescueChannel;
  outcome: RescueOutcome;
  notes: string;
  attemptedAt: string;
}

export type ConfirmationOutcome = "confirmed" | "rescue_needed" | "cancelled";

export interface PaymentLinkResponse {
  /** Razorpay/PayU plink id stored as Payment.gatewayReferenceId. */
  gatewayReferenceId: string;
  /** Short URL the customer opens to pay. */
  paymentUrl: string;
  /** New flat fields (Phase 2B). */
  paymentId: string;
  gateway: string;
  status: string;
  /** Phase 2A backwards-compat — full Payment row. */
  payment: Payment;
}

export interface CreateLeadPayload {
  name: string;
  phone: string;
  state: string;
  city: string;
  language?: string;
  source?: string;
  campaign?: string;
  productInterest?: string;
  quality?: "Hot" | "Warm" | "Cold";
  qualityScore?: number;
  assignee?: string;
  duplicate?: boolean;
}

export interface UpdateLeadPayload {
  name?: string;
  phone?: string;
  state?: string;
  city?: string;
  language?: string;
  source?: string;
  campaign?: string;
  productInterest?: string;
  status?: LeadStatus;
  quality?: "Hot" | "Warm" | "Cold";
  qualityScore?: number;
  assignee?: string;
  duplicate?: boolean;
}

export interface CustomerWritePayload {
  leadId?: string;
  name?: string;
  phone?: string;
  state?: string;
  city?: string;
  language?: string;
  productInterest?: string;
  diseaseCategory?: string;
  lifestyleNotes?: string;
  objections?: string[];
  aiSummary?: string;
  riskFlags?: string[];
  reorderProbability?: number;
  satisfaction?: number;
  consent?: { call?: boolean; whatsapp?: boolean; marketing?: boolean };
}

export interface CreateOrderPayload {
  customerName: string;
  phone: string;
  product: string;
  quantity?: number;
  amount?: number;
  discountPct?: number;
  advancePaid?: boolean;
  advanceAmount?: number;
  paymentStatus?: "Paid" | "Partial" | "Pending" | "Failed";
  state: string;
  city: string;
  rtoRisk?: "Low" | "Medium" | "High";
  rtoScore?: number;
  agent?: string;
  stage?: OrderStage;
}

export interface PaymentLinkPayload {
  orderId: string;
  amount: number;
  /** Defaults to "Razorpay" if omitted. */
  gateway?: "Razorpay" | "PayU";
  /** Defaults to "Advance" if omitted. */
  type?: "Advance" | "Full";
  customerName?: string;
  customerPhone?: string;
  customerEmail?: string;
}

export interface ShipmentCreatePayload {
  orderId: string;
}

export interface RescueAttemptCreatePayload {
  orderId: string;
  channel: RescueChannel;
  notes?: string;
}

export interface RescueAttemptUpdatePayload {
  outcome: RescueOutcome;
  notes?: string;
}
