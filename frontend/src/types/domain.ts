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
  /** Meta Lead Ads provenance — populated when ingested via /api/webhooks/meta/leads/. */
  metaLeadgenId?: string;
  metaPageId?: string;
  metaFormId?: string;
  metaAdId?: string;
  metaCampaignId?: string;
  /** Free-text breadcrumb (e.g. ad id or form id) used for attribution. */
  sourceDetail?: string;
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

// ----- Phase 3A — AgentRun -----

export type AgentName =
  | "ceo"
  | "caio"
  | "ads"
  | "rto"
  | "sales_growth"
  | "marketing"
  | "cfo"
  | "compliance";

export type AgentRunStatus = "pending" | "success" | "failed" | "skipped";

export interface ProviderAttempt {
  provider: string;
  model: string;
  status: AgentRunStatus | string;
  error?: string;
  latencyMs?: number;
  promptTokens?: number | null;
  completionTokens?: number | null;
  totalTokens?: number | null;
  costUsd?: number | null;
}

export interface AgentRun {
  id: string;
  agent: AgentName;
  promptVersion: string;
  inputPayload: Record<string, unknown>;
  outputPayload: Record<string, unknown>;
  status: AgentRunStatus;
  provider: string;
  model: string;
  latencyMs: number;
  costUsd: string | null;
  errorMessage: string;
  dryRun: boolean;
  triggeredBy: string;
  createdAt: string;
  completedAt: string | null;
  /** Phase 3C — token usage + fallback bookkeeping. */
  promptTokens?: number | null;
  completionTokens?: number | null;
  totalTokens?: number | null;
  providerAttempts?: ProviderAttempt[];
  fallbackUsed?: boolean;
  pricingSnapshot?: Record<string, unknown>;
}

export interface AgentRunCreatePayload {
  agent: AgentName;
  input?: Record<string, unknown>;
  /** Phase 3A coerces this to true server-side; kept on the wire for forward-compat. */
  dryRun?: boolean;
}

// ----- Phase 3B — Agent runtime status -----

export interface AgentRuntimeStatus {
  phase: "3B";
  dryRunOnly: true;
  agents: AgentName[];
  /** Last AgentRun per agent (null when an agent has never been run). */
  lastRuns: Record<AgentName, AgentRun | null>;
}

// ----- Phase 3C — Celery scheduler + cost tracking status -----

export interface AiSchedulerSlot {
  hour: number;
  minute: number;
}

export interface AiSchedulerStatus {
  celeryConfigured: boolean;
  celeryEagerMode: boolean;
  redisConfigured: boolean;
  /** Broker URL with credentials redacted. */
  brokerUrl: string;
  timezone: string;
  morningSchedule: AiSchedulerSlot;
  eveningSchedule: AiSchedulerSlot;
  lastDailyBriefingRun: AgentRun | null;
  lastCaioSweepRun: AgentRun | null;
  aiProvider: string;
  primaryModel: string;
  fallbacks: string[];
  /** Latest successful AgentRun's cost_usd (string from DecimalField). */
  lastCostUsd: string | null;
  lastFallbackUsed: boolean;
}

// ----- Phase 3D — sandbox + prompt versioning + budget guards -----

export type PromptVersionStatus =
  | "draft"
  | "sandbox"
  | "active"
  | "rolled_back"
  | "archived";

export interface PromptVersion {
  id: string;
  agent: AgentName;
  version: string;
  title: string;
  systemPolicy: string;
  rolePrompt: string;
  instructionPayload: Record<string, unknown>;
  isActive: boolean;
  status: PromptVersionStatus;
  createdBy: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  activatedAt: string | null;
  rolledBackAt: string | null;
  rollbackReason: string;
}

export interface PromptVersionCreatePayload {
  agent: AgentName;
  version: string;
  title?: string;
  systemPolicy?: string;
  rolePrompt?: string;
  instructionPayload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface AgentBudget {
  id: number;
  agent: AgentName;
  dailyBudgetUsd: string;
  monthlyBudgetUsd: string;
  isEnforced: boolean;
  alertThresholdPct: number;
  createdAt: string;
  updatedAt: string;
  /** Decorated by the API — current period's spend (USD). */
  dailySpendUsd?: string;
  monthlySpendUsd?: string;
}

export interface AgentBudgetWritePayload {
  agent: AgentName;
  dailyBudgetUsd: string | number;
  monthlyBudgetUsd: string | number;
  isEnforced?: boolean;
  alertThresholdPct?: number;
}

export interface SandboxState {
  isEnabled: boolean;
  note: string;
  updatedBy: string;
  updatedAt: string;
}

export interface SandboxPatchPayload {
  isEnabled: boolean;
  note?: string;
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
  // Phase 4B fields (optional for backward compat with mock fixtures).
  agentId?: string;
  agentType?: string;
  rewardedOrders?: number;
  penalizedOrders?: number;
  lastCalculatedAt?: string | null;
}

// Phase 4B — per-order, per-AI-agent scoring event.
export interface RewardPenaltyEventComponent {
  code: string;
  label: string;
  points: number;
}

export interface RewardPenaltyEvent {
  id: string;
  orderId: string | null;
  orderIdSnapshot: string;
  agentId: string | null;
  agentName: string;
  agentType: string;
  eventType: "reward" | "penalty" | "mixed";
  rewardScore: number;
  penaltyScore: number;
  netScore: number;
  components: RewardPenaltyEventComponent[];
  missingData: string[];
  attribution: Record<string, unknown>;
  source: string;
  triggeredBy: string;
  calculatedAt: string;
  metadata: Record<string, unknown>;
  uniqueKey: string;
}

export interface RewardPenaltySummary {
  evaluatedOrders: number;
  totalReward: number;
  totalPenalty: number;
  netScore: number;
  lastSweepAt: string | null;
  lastSweepPayload: Record<string, unknown> | null;
  missingDataWarnings: string[];
  agentLeaderboard: RewardPenalty[];
}

export interface RewardPenaltySweepPayload {
  startDate?: string | null;
  endDate?: string | null;
  orderId?: string;
  dryRun?: boolean;
}

export interface RewardPenaltySweepResult {
  evaluatedOrders: number;
  createdEvents: number;
  updatedEvents: number;
  skippedOrders: number;
  totalReward: number;
  totalPenalty: number;
  netScore: number;
  dryRun: boolean;
  leaderboardUpdated: boolean;
  missingDataWarnings: string[];
}

// Phase 4C — Approval Matrix Middleware.
export type ApprovalRequestStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "auto_approved"
  | "blocked"
  | "escalated"
  | "expired";

export type ApprovalRequestMode =
  | "auto"
  | "auto_with_consent"
  | "approval_required"
  | "director_override"
  | "human_escalation";

export interface ApprovalDecisionLog {
  id: number;
  oldStatus: string;
  newStatus: string;
  decidedBy: string;
  note: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export type ApprovalExecutionStatus = "executed" | "failed" | "skipped";

export interface ApprovalExecutionLog {
  id: number;
  approvalRequestId: string;
  action: string;
  status: ApprovalExecutionStatus;
  executedBy: string;
  executedAt: string;
  result: Record<string, unknown>;
  errorMessage: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface ApprovalRequest {
  id: string;
  action: string;
  mode: ApprovalRequestMode;
  approver: string;
  status: ApprovalRequestStatus;
  requestedBy: string;
  requestedByAgent: string;
  targetApp: string;
  targetModel: string;
  targetObjectId: string;
  proposedPayload: Record<string, unknown>;
  policySnapshot: Record<string, unknown>;
  reason: string;
  decisionNote: string;
  decidedBy: string;
  decidedAt: string | null;
  expiresAt: string | null;
  createdAt: string;
  updatedAt: string;
  metadata: Record<string, unknown>;
  decisionLogs: ApprovalDecisionLog[];
  // Phase 4D — execution status surfaces.
  executionLogs?: ApprovalExecutionLog[];
  latestExecutionStatus?: ApprovalExecutionStatus | null;
  latestExecutionAt?: string | null;
  latestExecutionResult?: Record<string, unknown>;
  latestExecutionError?: string;
}

export interface ExecuteApprovalPayload {
  payloadOverride?: Record<string, unknown>;
  note?: string;
}

export interface ExecuteApprovalResponse {
  approvalRequestId: string;
  action: string;
  executionStatus: ApprovalExecutionStatus;
  executedAt: string | null;
  executedBy: string;
  result: Record<string, unknown>;
  errorMessage: string;
  message: string;
  alreadyExecuted: boolean;
}

export interface ApprovalEvaluationResult {
  action: string;
  mode: ApprovalRequestMode | "unknown";
  approver: string;
  status: ApprovalRequestStatus | "unknown";
  allowed: boolean;
  requiresHuman: boolean;
  reason: string;
  policy: Record<string, unknown>;
  approvalRequestId: string | null;
  notes: string[];
}

export interface ApprovalEvaluatePayload {
  action: string;
  actorRole?: string;
  actorAgent?: string;
  payload?: Record<string, unknown>;
  target?: Record<string, unknown>;
  persist?: boolean;
  reason?: string;
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
  // Phase 4A — present on live WebSocket frames (and optional on the
  // legacy polling response for backward compat).
  id?: number;
  kind?: string;
  payload?: Record<string, unknown>;
  createdAt?: string;
}

// Phase 4A — Realtime AuditEvent stream connection states.
export type RealtimeStatus = "connecting" | "live" | "reconnecting" | "offline";

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

// ---------- Phase 5A — WhatsApp Live Sender Foundation ----------

export type WhatsAppProvider = "mock" | "meta_cloud" | "baileys_dev";
export type WhatsAppConnectionStatus = "connected" | "disconnected" | "error";
export type WhatsAppTemplateCategory =
  | "AUTHENTICATION"
  | "MARKETING"
  | "UTILITY";
export type WhatsAppTemplateStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "DISABLED";
export type WhatsAppConsentState =
  | "unknown"
  | "granted"
  | "revoked"
  | "opted_out";
export type WhatsAppConversationStatus =
  | "open"
  | "pending"
  | "resolved"
  | "escalated_to_human";
export type WhatsAppConversationAiStatus =
  | "disabled"
  | "suggest"
  | "pending_approval"
  | "auto_after_approval";
export type WhatsAppMessageDirection = "inbound" | "outbound";
export type WhatsAppMessageStatus =
  | "queued"
  | "sent"
  | "delivered"
  | "read"
  | "failed";
export type WhatsAppMessageType =
  | "text"
  | "template"
  | "image"
  | "document"
  | "audio"
  | "location"
  | "interactive"
  | "system";

export interface WhatsAppConnection {
  id: string;
  provider: WhatsAppProvider;
  displayName: string;
  phoneNumber: string;
  phoneNumberId: string;
  businessAccountId: string;
  status: WhatsAppConnectionStatus;
  lastConnectedAt: string | null;
  lastHealthCheckAt: string | null;
  lastError: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface WhatsAppTemplate {
  id: string;
  connectionId: string;
  name: string;
  language: string;
  category: WhatsAppTemplateCategory;
  status: WhatsAppTemplateStatus;
  bodyComponents: Array<Record<string, unknown>>;
  variablesSchema: Record<string, unknown>;
  actionKey: string;
  claimVaultRequired: boolean;
  isActive: boolean;
  lastSyncedAt: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface WhatsAppConsent {
  customerId: string;
  consentState: WhatsAppConsentState;
  grantedAt: string | null;
  revokedAt: string | null;
  optOutKeyword: string;
  expiresAt: string | null;
  lastInboundAt: string | null;
  source: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface WhatsAppConsentSummary {
  customerId: string;
  consentWhatsapp: boolean;
  history: WhatsAppConsent;
}

export interface WhatsAppConversation {
  id: string;
  customerId: string;
  customerName: string;
  customerPhone: string;
  connectionId: string;
  assignedToId: number | null;
  assignedToUsername: string;
  status: WhatsAppConversationStatus;
  aiStatus: WhatsAppConversationAiStatus;
  unreadCount: number;
  lastMessageText: string;
  lastMessageAt: string | null;
  lastInboundAt: string | null;
  subject: string;
  tags: string[];
  resolvedAt: string | null;
  resolvedById: number | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface WhatsAppMessage {
  id: string;
  conversationId: string;
  customerId: string;
  providerMessageId: string;
  direction: WhatsAppMessageDirection;
  status: WhatsAppMessageStatus;
  type: WhatsAppMessageType;
  body: string;
  templateId: string | null;
  templateName: string;
  templateVariables: Record<string, unknown>;
  mediaUrl: string;
  aiGenerated: boolean;
  approvalRequestId: string | null;
  errorMessage: string;
  errorCode: string;
  attemptCount: number;
  idempotencyKey: string;
  metadata: Record<string, unknown>;
  queuedAt: string | null;
  sentAt: string | null;
  deliveredAt: string | null;
  readAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface WhatsAppInternalNote {
  id: number;
  conversationId: string;
  authorId: number | null;
  authorName: string;
  body: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface WhatsAppAiSuggestionStatus {
  enabled: boolean;
  /** Phase 5C statuses include the live runtime states. */
  status:
    | "disabled"
    | "suggest"
    | "auto"
    | "auto_reply_off"
    | "provider_disabled"
    | "pending_approval";
  message: string;
  provider?: string;
  autoReplyEnabled?: boolean;
  confidenceThreshold?: number;
}

// ---------- Phase 5C — WhatsApp AI Chat Sales Agent ----------

export type WhatsAppAiMode = "auto" | "suggest" | "disabled";

export type WhatsAppAiStage =
  | "greeting"
  | "discovery"
  | "category_detection"
  | "product_explanation"
  | "objection_handling"
  | "price_presented"
  | "discount_negotiation"
  | "address_collection"
  | "order_confirmation"
  | "order_booked"
  | "handoff_required";

export type WhatsAppAiLanguage = "hindi" | "hinglish" | "english" | "unknown" | "";

export interface WhatsAppAiLastSuggestion {
  action: string;
  replyText: string;
  category: string;
  language: string;
  confidence: number;
  blockedReason: string;
}

export interface WhatsAppConversationAiState {
  aiEnabled: boolean;
  aiMode: WhatsAppAiMode;
  stage: WhatsAppAiStage;
  detectedLanguage: WhatsAppAiLanguage;
  detectedCategory: string;
  lastAiAction: string;
  lastAiConfidence: number;
  discountAskCount: number;
  totalDiscountPct: number;
  offeredDiscountPct: number;
  handoffRequired: boolean;
  handoffReason: string;
  orderId: string;
  paymentId: string;
  paymentLink: string;
  lastSuggestion: WhatsAppAiLastSuggestion | null;
}

export interface WhatsAppConversationAiPayload {
  conversationId: string;
  ai: WhatsAppConversationAiState;
}

export interface WhatsAppAiGlobalStatus extends WhatsAppAiSuggestionStatus {
  rateLimits: {
    maxTurnsPerConversationPerHour: number;
    maxMessagesPerCustomerPerDay: number;
  };
}

export interface WhatsAppAiRunSummary {
  conversationId: string;
  inboundMessageId: string;
  action: string;
  sent: boolean;
  sentMessageId: string;
  handoffRequired: boolean;
  handoffReason: string;
  blockedReason: string;
  stage: string;
  confidence: number;
  language: string;
  category: string;
  orderId: string;
  paymentId: string;
}

export interface WhatsAppAiAuditEvent {
  id: number;
  kind: string;
  text: string;
  tone: "success" | "info" | "warning" | "danger";
  occurredAt: string;
  payload: Record<string, unknown>;
}

export interface WhatsAppAiRunsResponse {
  ai: WhatsAppConversationAiState;
  events: WhatsAppAiAuditEvent[];
}

export interface UpdateWhatsAppAiModePayload {
  aiEnabled?: boolean;
  aiMode?: WhatsAppAiMode;
}

export interface WhatsAppAiHandoffPayload {
  reason?: string;
}

export interface WhatsAppInboxCounts {
  all: number;
  unread: number;
  open: number;
  pending: number;
  resolved: number;
  escalatedToHuman: number;
}

export interface WhatsAppInboxSummary {
  conversations: WhatsAppConversation[];
  counts: WhatsAppInboxCounts;
  aiSuggestions: WhatsAppAiSuggestionStatus;
}

export interface WhatsAppCustomerTimelineItem {
  kind: "message" | "internal_note" | "status_event";
  id: string;
  occurredAt: string;
  data: WhatsAppMessage | WhatsAppInternalNote | Record<string, unknown>;
}

export interface WhatsAppCustomerTimeline {
  customerId: string;
  consentWhatsapp: boolean;
  conversations: WhatsAppConversation[];
  items: WhatsAppCustomerTimelineItem[];
  aiSuggestions: WhatsAppAiSuggestionStatus;
}

export interface CreateInternalNotePayload {
  body: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateWhatsAppConversationPayload {
  status?: WhatsAppConversationStatus;
  assignedToId?: number | null;
  tags?: string[];
  subject?: string;
}

export interface SendConversationTemplatePayload {
  actionKey: string;
  templateId?: string;
  variables?: Record<string, string | number>;
  triggeredBy?: string;
  idempotencyKey?: string;
}

export interface WhatsAppProviderStatus {
  provider: WhatsAppProvider;
  configured: boolean;
  healthy: boolean;
  detail: string;
  connection: {
    id: string;
    displayName: string;
    phoneNumber: string;
    phoneNumberId: string;
    businessAccountId: string;
    status: WhatsAppConnectionStatus;
    lastConnectedAt: string | null;
    lastHealthCheckAt: string | null;
  } | null;
  accessTokenSet: boolean;
  verifyTokenSet: boolean;
  appSecretSet: boolean;
  apiVersion: string;
  devProviderEnabled: boolean;
  metadata: Record<string, unknown>;
}

export interface SendWhatsAppTemplatePayload {
  customerId: string;
  actionKey: string;
  templateId?: string;
  variables?: Record<string, string | number>;
  triggeredBy?: string;
  idempotencyKey?: string;
}

export interface SendWhatsAppTemplateResponse {
  message: WhatsAppMessage;
  conversationId: string;
  approvalRequestId: string | null;
  autoApproved: boolean;
}

export interface WhatsAppConsentPatchPayload {
  consentState: WhatsAppConsentState;
  source?: string;
  note?: string;
}

export interface WhatsAppTemplateSyncPayload {
  data?: Array<Record<string, unknown>>;
}

export interface WhatsAppTemplateSyncResult {
  connectionId: string;
  createdCount: number;
  updatedCount: number;
  totalProcessed: number;
  actor: string;
}

// ---------- Phase 5D — Chat-to-Call handoff + Lifecycle automation ----------

export type WhatsAppHandoffTriggerSource =
  | "ai"
  | "operator"
  | "lifecycle"
  | "system";

export type WhatsAppHandoffStatus =
  | "pending"
  | "triggered"
  | "failed"
  | "skipped";

export interface WhatsAppHandoffToCall {
  id: number;
  conversationId: string;
  customerId: string;
  inboundMessageId: string;
  reason: string;
  triggerSource: WhatsAppHandoffTriggerSource;
  status: WhatsAppHandoffStatus;
  callId: string;
  providerCallId: string;
  requestedBy: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  triggeredAt: string | null;
  errorMessage: string;
}

export interface TriggerWhatsAppCallPayload {
  reason?: string;
  note?: string;
}

export interface TriggerWhatsAppCallResponse {
  handoffId: number;
  status: WhatsAppHandoffStatus;
  callId: string;
  providerCallId: string;
  reason: string;
  skipped: boolean;
  errorMessage: string;
  message: string;
}

export type WhatsAppLifecycleObjectType =
  | "order"
  | "payment"
  | "shipment";

export type WhatsAppLifecycleStatus =
  | "queued"
  | "sent"
  | "blocked"
  | "skipped"
  | "failed";

export interface WhatsAppLifecycleEvent {
  id: number;
  actionKey: string;
  objectType: WhatsAppLifecycleObjectType;
  objectId: string;
  eventKind: string;
  customerId: string;
  messageId: string;
  status: WhatsAppLifecycleStatus;
  blockReason: string;
  errorMessage: string;
  idempotencyKey: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export type ClaimCoverageRisk = "ok" | "weak" | "missing";

export interface ClaimVaultCoverageItem {
  product: string;
  category: string;
  approvedClaimCount: number;
  hasApprovedClaims: boolean;
  missingRequiredUsageClaims: boolean;
  lastApprovedAt: string;
  risk: ClaimCoverageRisk;
  notes: string[];
}

export interface ClaimVaultCoverageReport {
  totalProducts: number;
  okCount: number;
  weakCount: number;
  missingCount: number;
  /** Phase 5E — count of demo / default seed rows. */
  demoCount?: number;
  items: ClaimVaultCoverageItem[];
}

// ---------- Phase 5E — Rescue Discount Flow + Day-20 Reorder ----------

export type DiscountOfferSourceChannel =
  | "whatsapp_ai"
  | "ai_call"
  | "confirmation"
  | "delivery"
  | "rto"
  | "operator"
  | "system";

export type DiscountOfferStage =
  | "order_booking"
  | "confirmation"
  | "delivery"
  | "rto"
  | "reorder"
  | "customer_success";

export type DiscountOfferStatus =
  | "offered"
  | "accepted"
  | "rejected"
  | "blocked"
  | "skipped"
  | "needs_ceo_review";

export interface DiscountOffer {
  id: number;
  orderId: string;
  customerId: string;
  conversationId: string;
  sourceChannel: DiscountOfferSourceChannel;
  stage: DiscountOfferStage;
  triggerReason: string;
  previousDiscountPct: number;
  offeredAdditionalPct: number;
  resultingTotalDiscountPct: number;
  capRemainingPct: number;
  status: DiscountOfferStatus;
  blockedReason: string;
  offeredByAgent: string;
  approvalRequestId: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface DiscountOfferCap {
  currentTotalPct: number;
  capRemainingPct: number;
  finalTotalIfAppliedPct: number;
  capPassed: boolean;
  totalCapPct: number;
}

export interface DiscountOfferListResponse {
  orderId: string;
  currentDiscountPct: number;
  cap: DiscountOfferCap;
  offers: DiscountOffer[];
}

export interface CreateRescueOfferPayload {
  sourceChannel?: DiscountOfferSourceChannel;
  stage: DiscountOfferStage;
  triggerReason: string;
  refusalCount?: number;
  riskLevel?: string;
  requestedPct?: number | null;
  conversationId?: string;
  metadata?: Record<string, unknown>;
}

export interface ReorderDay20StatusResponse {
  enabled: boolean;
  lifecycleEnabled: boolean;
  lowerBoundDays: number;
  upperBoundDays: number;
  events: WhatsAppLifecycleEvent[];
}

export interface ReorderDay20RunResponse {
  eligible: number;
  queued: number;
  skipped: number;
  blocked: number;
  failed: number;
  dryRun: boolean;
}

// ---------- Phase 5F-Gate Auto-Reply Monitoring Dashboard ----------

export type WhatsAppMonitoringStatus =
  | "safe_off"
  | "limited_auto_reply_on"
  | "needs_attention"
  | "danger";

export interface WhatsAppMonitoringWabaSubscription {
  checked: boolean;
  active: boolean | null;
  subscribedAppCount: number;
  warning: string;
  error: string;
}

export interface WhatsAppMonitoringGate {
  provider: string;
  limitedTestMode: boolean;
  autoReplyEnabled: boolean;
  allowedListSize: number;
  allowedNumbersMasked: string[];
  wabaSubscription: WhatsAppMonitoringWabaSubscription;
  finalSendGuardActive: boolean;
  consentRequired: boolean;
  claimVaultRequired: boolean;
  blockedPhraseFilterActive: boolean;
  medicalSafetyActive: boolean;
  callHandoffEnabled: boolean;
  lifecycleEnabled: boolean;
  rescueDiscountEnabled: boolean;
  rtoRescueEnabled: boolean;
  reorderEnabled: boolean;
  campaignsLocked: boolean;
  readyForLimitedAutoReply: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface WhatsAppMonitoringActivity {
  windowHours: number;
  since: string;
  now: string;
  allowedListSize: number;
  inboundMessageCount: number;
  outboundMessageCount: number;
  inboundAiRunStartedCount: number;
  replyAutoSentCount: number;
  replyBlockedCount: number;
  suggestionStoredCount: number;
  handoffRequiredCount: number;
  deterministicBuilderUsedCount: number;
  deterministicBuilderBlockedCount: number;
  objectionReplyUsedCount: number;
  objectionReplyBlockedCount: number;
  autoReplyFlagPathUsedCount: number;
  autoReplyGuardBlockedCount: number;
  safetyDowngradedCount: number;
  messageDeliveredCount: number;
  messageReadCount: number;
  sendBlockedCount: number;
  unexpectedNonAllowedSendsCount: number;
  unexpectedNonAllowedSendSuffixes: string[];
  ordersCreatedInWindow: number;
  paymentsCreatedInWindow: number;
  shipmentsCreatedInWindow: number;
  discountOfferLogsCreatedInWindow: number;
  warnings: string[];
  nextAction: string;
}

export interface WhatsAppMonitoringCohortEntry {
  maskedPhone: string;
  suffix: string;
  customerFound: boolean;
  customerId: string;
  customerPhoneMasked: string;
  consentFound: boolean;
  consentState: string;
  consentSource: string;
  conversationFound: boolean;
  latestInboundId: string;
  latestInboundAt: string | null;
  latestOutboundId: string;
  latestOutboundStatus: string;
  latestOutboundAt: string | null;
  latestAuditAt: string | null;
  readyForControlledTest: boolean;
  missingSetup: string[];
}

export interface WhatsAppMonitoringCohort {
  provider: string;
  limitedTestMode: boolean;
  autoReplyEnabled: boolean;
  callHandoffEnabled: boolean;
  lifecycleEnabled: boolean;
  rescueDiscountEnabled: boolean;
  rtoRescueEnabled: boolean;
  reorderEnabled: boolean;
  allowedListSize: number;
  cohort: WhatsAppMonitoringCohortEntry[];
  wabaSubscription: WhatsAppMonitoringWabaSubscription;
  warnings: string[];
  errors: string[];
  nextAction: string;
}

export interface WhatsAppMonitoringMutationSafety {
  windowHours: number;
  since: string;
  now: string;
  ordersCreatedInWindow: number;
  paymentsCreatedInWindow: number;
  shipmentsCreatedInWindow: number;
  discountOfferLogsCreatedInWindow: number;
  lifecycleEventsInWindow: number;
  handoffEventsInWindow: number;
  totalMutations: number;
  allClean: boolean;
}

export interface WhatsAppMonitoringUnexpectedOutboundEntry {
  messageId: string;
  phoneSuffix: string;
  status: string;
  sentAt: string | null;
  providerMessageId: string;
}

export interface WhatsAppMonitoringUnexpectedOutbound {
  windowHours: number;
  since: string;
  now: string;
  unexpectedSendsCount: number;
  breakdown: WhatsAppMonitoringUnexpectedOutboundEntry[];
  rollbackRecommended: boolean;
}

export interface WhatsAppMonitoringPilotMember {
  customerId: string;
  customerName: string;
  maskedPhone: string;
  phoneSuffix: string;
  status: "pending" | "approved" | "paused" | "removed" | string;
  consentRequired: boolean;
  consentVerified: boolean;
  source: string;
  approvedAt: string | null;
  dailyCap: number;
  lastInboundAt: string | null;
  lastOutboundAt: string | null;
  latestStatus: string;
  phoneAllowedInLimitedMode: boolean;
  recentSafetyIssue: boolean;
  ready: boolean;
  blockers: string[];
}

export interface WhatsAppMonitoringPilotSafety {
  autoReplyEnabled: boolean;
  limitedTestMode: boolean;
  campaignsLocked: boolean;
  broadcastLocked: boolean;
  callHandoffEnabled: boolean;
  lifecycleEnabled: boolean;
  rescueDiscountEnabled: boolean;
  rtoRescueEnabled: boolean;
  reorderEnabled: boolean;
  allowedListSize: number;
  unexpectedNonAllowedSendsCount: number;
  mutationCounts: {
    ordersCreatedInWindow: number;
    paymentsCreatedInWindow: number;
    shipmentsCreatedInWindow: number;
    discountOfferLogsCreatedInWindow: number;
  };
  mutationTotal: number;
  dashboardAvailable: boolean;
}

export interface WhatsAppMonitoringSaasGuardrails {
  mode: string;
  organizationModelExists: boolean;
  tenantModelExists: boolean;
  branchModelExists: boolean;
  userRolesExist: boolean;
  auditOrgBranchContextExists: boolean;
  featureFlagsPerOrgExist: boolean;
  whatsappSettingsPerOrgExist: boolean;
  safeInterfacesAdded: string[];
  deferred: string[];
  nextAction: string;
}

export interface WhatsAppMonitoringPilot {
  windowHours: number;
  generatedAt: string;
  totalPilotMembers: number;
  approvedCount: number;
  pendingCount: number;
  pausedCount: number;
  consentMissingCount: number;
  readyForPilotCount: number;
  members: WhatsAppMonitoringPilotMember[];
  blockers: string[];
  nextAction: string;
  safety: WhatsAppMonitoringPilotSafety;
  saasGuardrails: WhatsAppMonitoringSaasGuardrails;
}

export interface WhatsAppMonitoringAuditEvent {
  id: number;
  occurredAt: string;
  kind: string;
  tone: "success" | "info" | "warning" | "danger";
  text: string;
  icon: string;
  conversationId: string;
  customerId: string;
  messageId: string;
  inboundMessageId: string;
  phoneSuffix: string;
  category: string;
  blockReason: string;
  finalReplySource: string;
  deterministicFallbackUsed: boolean;
  claimVaultUsed: boolean;
}

export interface WhatsAppMonitoringAuditResponse {
  windowHours: number;
  since: string;
  now: string;
  limit: number;
  count: number;
  events: WhatsAppMonitoringAuditEvent[];
}

export interface WhatsAppMonitoringOverview {
  windowHours: number;
  generatedAt: string;
  status: WhatsAppMonitoringStatus;
  nextAction: string;
  rollbackReady: boolean;
  gate: WhatsAppMonitoringGate;
  activity: WhatsAppMonitoringActivity;
  cohort: WhatsAppMonitoringCohort;
  pilot: WhatsAppMonitoringPilot;
  mutationSafety: WhatsAppMonitoringMutationSafety;
  unexpectedOutbound: WhatsAppMonitoringUnexpectedOutbound;
}
