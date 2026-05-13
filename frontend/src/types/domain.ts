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

// ---------- Phase 6A — SaaS Foundation read-only types ----------

export type SaasOrganizationStatus = "active" | "paused" | "archived";

export type SaasOrgRole =
  | "owner"
  | "admin"
  | "manager"
  | "agent"
  | "viewer"
  | "";

export interface SaasBranchSummary {
  id: number;
  code: string;
  name: string;
  status: string;
}

export interface SaasOrganization {
  id: number;
  code: string;
  name: string;
  legalName: string;
  status: SaasOrganizationStatus;
  timezone: string;
  country: string;
  defaultBranch: SaasBranchSummary | null;
  userOrgRole: SaasOrgRole;
  createdAt: string | null;
}

export interface SaasMembershipSummary {
  total: number;
  active: number;
  byRole: Record<string, number>;
}

export interface SaasFeatureFlagEntry {
  enabled: boolean;
  config: Record<string, unknown>;
}

export interface SaasCurrentOrganization {
  organization: SaasOrganization | null;
  membershipSummary: SaasMembershipSummary;
  settings: Record<string, unknown>;
  featureFlags: Record<string, SaasFeatureFlagEntry>;
}

export interface SaasMyOrganizations {
  count: number;
  organizations: Array<SaasOrganization | null>;
}

export interface SaasFeatureFlagsResponse {
  organization: SaasOrganization | null;
  featureFlags: Record<string, SaasFeatureFlagEntry>;
}

// ---------- Phase 6B — Default Org Data Coverage ----------

export interface SaasDataCoverageModelRow {
  model: string;
  totalRows: number;
  withOrganization: number;
  withoutOrganization: number;
  organizationCoveragePercent: number;
  hasBranchField: boolean;
  withBranch: number;
  withoutBranch: number;
  branchCoveragePercent: number;
}

export interface SaasDataCoverageTotals {
  totalRows: number;
  totalWithOrganization: number;
  totalWithoutOrganization: number;
  totalWithBranch: number;
  totalWithoutBranch: number;
  organizationCoveragePercent: number;
  branchCoveragePercent: number;
}

export interface SaasDataCoverage {
  defaultOrganizationExists: boolean;
  defaultOrganizationCode: string;
  defaultBranchExists: boolean;
  defaultBranchCode: string;
  globalTenantFilteringEnabled: boolean;
  safeToStartPhase6C: boolean;
  models: SaasDataCoverageModelRow[];
  totals: SaasDataCoverageTotals;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6C — Org-Scoped API Readiness ----------

export interface SaasOrgScopeReadiness {
  defaultOrganizationExists: boolean;
  defaultOrganizationCode: string;
  defaultBranchExists: boolean;
  defaultBranchCode: string;
  organizationCoveragePercent: number;
  branchCoveragePercent: number;
  scopedModels: string[];
  unscopedModels: string[];
  scopedApis: string[];
  unscopedApis: string[];
  auditAutoOrgContextEnabled: boolean;
  globalTenantFilteringEnabled: boolean;
  safeToStartPhase6D: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6D — Write-Path Readiness ----------

export interface SaasWritePathReadiness {
  defaultOrganizationExists: boolean;
  defaultBranchExists: boolean;
  writeContextHelpersAvailable: boolean;
  enforcementMode?: "advisory" | "safe_enforced";
  auditAutoOrgContextEnabled: boolean;
  coveredSafeCreatePaths?: string[];
  safeCreatePathsCovered: string[];
  deferredCreatePaths: string[];
  systemGlobalExceptions?: string[];
  modelsWithOrgBranch: string[];
  recentUnscopedWritesLast24h?: number;
  recentUnscopedWriteDetails?: {
    windowHours: number;
    totalWithoutOrganization: number;
    totalWithoutBranch: number;
    rows: Array<{
      model: string;
      withoutOrganization: number;
      withoutBranch: number;
    }>;
  };
  recentRowsWithoutOrganizationLast24h: number;
  recentRowsWithoutBranchLast24h: number;
  globalTenantFilteringEnabled: boolean;
  safeToStartPhase6E: boolean;
  safeToStartPhase6F?: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6E — SaaS Admin + Integration Settings ----------

export type SaasIntegrationProviderType =
  | "whatsapp_meta"
  | "razorpay"
  | "payu"
  | "delhivery"
  | "vapi"
  | "openai"
  | "other";

export interface SaasIntegrationSetting {
  id: number;
  organizationId: number;
  organizationCode: string;
  providerType: SaasIntegrationProviderType;
  providerLabel: string;
  status: "draft" | "configured" | "active" | "paused" | "invalid";
  displayName: string;
  config: Record<string, unknown>;
  secretRefs: Record<string, unknown>;
  secretRefsPresent: boolean;
  secretRefKeys: string[];
  isActive: boolean;
  lastValidatedAt: string | null;
  validationStatus: "not_checked" | "valid" | "invalid" | "warning";
  validationMessage: string;
  metadata: Record<string, unknown>;
  runtimeEnabled: false;
  runtimeUsesPerOrgSettings: false;
  createdAt: string;
  updatedAt: string;
}

export interface SaasProviderReadiness {
  providerType: SaasIntegrationProviderType;
  providerLabel: string;
  status: string;
  configured: boolean;
  isActive: boolean;
  secretRefsPresent: boolean;
  missingSecretRefs: string[];
  validationStatus: string;
  validationMessage: string;
  runtimeEnabled: false;
  runtimeUsesPerOrgSettings: false;
  setting: SaasIntegrationSetting | null;
  warnings: string[];
  nextAction: string;
}

export interface SaasIntegrationReadiness {
  organization: { id: number; code: string; name: string } | null;
  providers: SaasProviderReadiness[];
  providersConfigured: SaasIntegrationProviderType[];
  providersMissing: SaasIntegrationProviderType[];
  secretRefsMissing: SaasIntegrationProviderType[];
  integrationSettingsCount: number;
  runtimeUsesPerOrgSettings: false;
  safeToStartPhase6F: boolean;
  warnings: string[];
  nextAction: string;
}

export interface SaasSafetyLocks {
  whatsappAutoReplyEnabled: boolean;
  whatsappAutoReplyOff: boolean;
  limitedTestMode: boolean;
  campaignsLocked: boolean;
  broadcastLocked: boolean;
  callHandoffEnabled: boolean;
  lifecycleAutomationEnabled: boolean;
  rescueDiscountEnabled: boolean;
  rtoRescueEnabled: boolean;
  reorderDay20Enabled: boolean;
  runtimeUsesPerOrgSettings: false;
}

export interface SaasAuditTimelineEvent {
  id: number;
  kind: string;
  text: string;
  tone: string;
  icon: string;
  createdAt: string;
  organizationId: number | null;
}

export interface SaasAdminOverview {
  defaultOrganizationExists: boolean;
  defaultBranchExists: boolean;
  organization: (SaasOrganization & {
    membershipSummary: SaasMembershipSummary;
    featureFlags: Record<string, SaasFeatureFlagEntry>;
    integrationSettingsCount: number;
  }) | null;
  orgScopeReadiness: SaasOrgScopeReadiness;
  writePathReadiness: SaasWritePathReadiness;
  integrationReadiness: SaasIntegrationReadiness;
  integrationSettings: SaasIntegrationSetting[];
  integrationSettingsCount: number;
  providersConfigured: SaasIntegrationProviderType[];
  providersMissing: SaasIntegrationProviderType[];
  secretRefsMissing: SaasIntegrationProviderType[];
  safetyLocks: SaasSafetyLocks;
  runtimeUsesPerOrgSettings: false;
  auditTimeline: SaasAuditTimelineEvent[];
  safeToStartPhase6F: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasAdminOrganizationsResponse {
  count: number;
  organizations: Array<
    (SaasOrganization & {
      membershipSummary: SaasMembershipSummary;
      featureFlags: Record<string, SaasFeatureFlagEntry>;
      integrationSettingsCount: number;
    }) | null
  >;
}

export interface SaasIntegrationSettingsResponse {
  organization: SaasOrganization | null;
  settings: SaasIntegrationSetting[];
  runtimeUsesPerOrgSettings: false;
}

// ---------- Phase 6F — Per-Org Runtime Integration Routing Plan ----------

export interface SaasRuntimeRoutingSecretRefStatus {
  valid: boolean;
  source: "env" | "vault" | "unknown";
  maskedRef: string;
  present: boolean | null;
  canResolveAtRuntime: boolean;
  reason: string;
}

export interface SaasRuntimeRoutingProviderPreview {
  providerType: string;
  providerLabel: string;
  integrationSettingExists: boolean;
  settingStatus: string;
  isActive: boolean;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  secretRefsPresent: boolean;
  secretRefsResolvablePreview: {
    perRef: Record<string, SaasRuntimeRoutingSecretRefStatus>;
    anyMissingEnv: boolean;
  };
  missingSecretRefs: string[];
  configPresent: boolean;
  envKeyStatus: Record<string, { envVar: string; present: boolean }>;
  expectedSecretRefKeys: string[];
  setting: {
    id: number;
    providerType: string;
    displayName: string;
    status: string;
    isActive: boolean;
    validationStatus: string;
    validationMessage: string;
    secretRefs: Record<string, unknown>;
    config: Record<string, unknown>;
  } | null;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasRuntimeRoutingReadiness {
  organization: { id: number; code: string; name: string } | null;
  runtimeUsesPerOrgSettings: false;
  perOrgRuntimeEnabled: false;
  providers: SaasRuntimeRoutingProviderPreview[];
  global: {
    safeToStartPhase6G: boolean;
    blockers: string[];
    warnings: string[];
    nextAction: string;
  };
  warnings: string[];
  blockers: string[];
  nextAction: string;
}

// ---------- Phase 6G — Controlled Runtime Routing Dry Run ----------

export interface SaasRuntimeOperationDefinition {
  operationType: string;
  providerType: string;
  sideEffectRisk: "none" | "low" | "medium" | "high";
  dryRunAllowed: boolean;
  liveAllowedInPhase6G: false;
  requiredOrg: boolean;
  requiredSecretRefs: string[];
  requiredEnvKeys: string[];
  requiredConfigKeys: string[];
  readinessNotes: string;
  nextPhaseForLiveExecution: string;
}

export interface SaasAiProviderRoutePreview {
  taskType: string;
  primaryProvider: "nvidia" | string;
  primaryModel: string;
  primaryModelSource: "env" | "default";
  expectedPrimaryModel: string;
  fallbackProvider: "openai" | string;
  fallbackModel: string;
  fallbackModelSource: "env" | "default";
  fallbackConfigured: boolean;
  anthropicFallbackConfigured: boolean;
  runtimeMode: string;
  maxTokens: number;
  maxTokensSource: string;
  maxTokensFromEnv: boolean;
  apiBaseUrlPresent: boolean;
  apiKeyPresent: boolean;
  openaiKeyPresent: boolean;
  liveCallWillBeMade: false;
  dryRun: true;
  safetyWrappersRequired: boolean;
  safetyNotes: string[];
  blockers: string[];
  warnings: string[];
  nextAction: string;
  valid: boolean;
}

export interface SaasAiProviderRoutingPreview {
  runtime: {
    runtimeMode: string;
    primaryProvider: string;
    fallbackProvider: string;
    envKeyPresence: Record<string, boolean>;
  };
  tasks: SaasAiProviderRoutePreview[];
  safeToStartAiDryRun: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  dryRun: true;
  liveCallWillBeMade: false;
}

export interface SaasRuntimeDryRunOperationDecision {
  operationType: string;
  operationDefinition: SaasRuntimeOperationDefinition;
  organization: { id: number; code: string; name: string } | null;
  branch: { id: number; code: string; name: string } | null;
  providerType: string;
  providerLabel: string;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: true;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  sideEffectRisk: "none" | "low" | "medium" | "high";
  providerSettingExists: boolean;
  settingStatus: string;
  secretRefsStatus: Record<
    string,
    {
      maskedRef?: string;
      source?: string;
      present?: boolean | null;
      canResolveAtRuntime?: boolean;
      reason?: string;
    }
  >;
  envKeyStatus: Record<string, boolean>;
  configStatus: Record<string, boolean>;
  providerRuntimePreview: {
    secretRefsPresent: boolean;
    missingSecretRefs: string[];
    configPresent: boolean;
  };
  aiProviderRoute: SaasAiProviderRoutePreview | null;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  auditKind: string;
}

export interface SaasRuntimeDryRunReport {
  organization: { id: number; code: string; name: string } | null;
  runtimeUsesPerOrgSettings: false;
  perOrgRuntimeEnabled: false;
  runtimeSource: "env_config";
  dryRun: true;
  liveExecutionAllowed: false;
  operations: SaasRuntimeDryRunOperationDecision[];
  aiProviderRoutes: SaasAiProviderRoutingPreview | null;
  global: {
    safeToStartPhase6H: boolean;
    blockers: string[];
    warnings: string[];
    nextAction: string;
  };
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasControlledRuntimeReadiness {
  organization: { id: number; code: string; name: string } | null;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  runtimeUsesPerOrgSettings: false;
  dryRun: true;
  liveExecutionAllowed: false;
  operationCount: number;
  aiTaskCount: number;
  safeToStartPhase6H: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6H - Controlled Runtime Live Audit Gate ----------

export type SaasLiveGateDecision =
  | "dry_run_allowed"
  | "blocked_by_default"
  | "blocked_by_kill_switch"
  | "blocked_missing_approval"
  | "blocked_missing_provider_config"
  | "blocked_missing_consent"
  | "blocked_missing_caio_review"
  | "blocked_missing_claim_vault"
  | "blocked_missing_webhook"
  | "live_ready_but_not_executed"
  | string;

export interface SaasLiveGatePolicy {
  operationType: string;
  providerType: string;
  riskLevel: "low" | "medium" | "high" | "critical" | string;
  liveAllowedByDefault: false;
  approvalRequired: boolean;
  caioReviewRequired: boolean;
  consentRequired: boolean;
  claimVaultRequired: boolean;
  webhookRequired: boolean;
  idempotencyRequired: boolean;
  auditRequired: boolean;
  killSwitchCanBlock: boolean;
  allowedInPhase6H: false;
  nextPhaseForLiveTest: string;
  templateApprovalRequired: boolean;
  paymentApprovalRequired: boolean;
  customerIntentRequired: boolean;
  addressValidationRequired: boolean;
  providerDeferred: boolean;
  humanApprovalRequired: boolean;
  requiredEnvKeys: string[];
  requiredConfigKeys: string[];
  policyVersion: string;
  currentGateDecision?: SaasLiveGateDecision;
  liveAllowedNow?: false;
  blockers?: string[];
  warnings?: string[];
  nextAction?: string;
  metadata: Record<string, unknown>;
}

export interface SaasLiveGateRequest {
  id: number;
  organization: { id: number; code: string; name: string } | null;
  branch: { id: number; code: string; name: string } | null;
  operationType: string;
  providerType: string;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: true;
  liveExecutionRequested: boolean;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  approvalRequired: boolean;
  approvalStatus: string;
  requestedBy: number | null;
  approvedBy: number | null;
  rejectedBy: number | null;
  requestedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  expiresAt: string | null;
  riskLevel: string;
  payloadHash: string;
  safePayloadSummary: Record<string, unknown>;
  blockers: string[];
  warnings: string[];
  gateDecision: SaasLiveGateDecision;
  idempotencyKey: string;
  auditEventId: number | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  killSwitchActive: boolean;
  nextAction: string;
}

export interface SaasLiveGateAuditEvent {
  id: number;
  kind: string;
  operationType: string;
  providerType: string;
  gateDecision: string;
  actor: string;
  createdAt: string;
  text: string;
}

export interface SaasRuntimeLiveGateSummary {
  organization: { id: number; code: string; name: string } | null;
  killSwitch: {
    globalEnabled: boolean;
    orgEnabled: boolean;
    providerEnabled?: boolean;
    operationEnabled?: boolean;
    active: boolean;
    activeBlockers: string[];
  };
  operationPolicies: SaasLiveGatePolicy[];
  recentLiveExecutionRequests: SaasLiveGateRequest[];
  approvalQueue: {
    approvalPendingCount: number;
    approvedButNotExecutedCount: number;
    blockedCount: number;
    rejectedCount: number;
  };
  approvalPendingCount: number;
  approvedButNotExecutedCount: number;
  blockedCount: number;
  rejectedCount: number;
  recentGateAuditEvents: SaasLiveGateAuditEvent[];
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  runtimeUsesPerOrgSettings: false;
  defaultDryRun: true;
  defaultLiveExecutionAllowed: false;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  safeToStartPhase6I: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasRuntimeLiveGateRequestsResponse {
  count: number;
  requests: SaasLiveGateRequest[];
  dryRun: true;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
}

export interface SaasRuntimeLiveGatePoliciesResponse {
  policies: SaasLiveGatePolicy[];
  dryRun: true;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
}

export interface SaasRuntimeLiveGateKillSwitch {
  scope: string;
  enabled: boolean;
  reason: string;
  dryRun: true;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  killSwitchActive: boolean;
  approvalStatus: string;
  gateDecision: string;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasRuntimeLiveGatePreview {
  operationType: string;
  providerType: string;
  valid: boolean;
  policy?: SaasLiveGatePolicy;
  organization: { id: number; code: string; name: string } | null;
  branch: { id: number; code: string; name: string } | null;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: true;
  liveExecutionRequested: boolean;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  approvalRequired: boolean;
  approvalStatus: string;
  killSwitchActive: boolean;
  riskLevel: string;
  payloadHash: string;
  safePayloadSummary: Record<string, unknown>;
  blockers: string[];
  warnings: string[];
  gateDecision: SaasLiveGateDecision;
  nextAction: string;
}

// ---------- Phase 6I - Single Internal Live Gate Simulation ----------

export interface SaasRuntimeLiveGateSimulation {
  id: number;
  organization: { id: number; code: string; name: string } | null;
  branch: { id: number; code: string; name: string } | null;
  liveExecutionRequestId: number | null;
  operationType: "razorpay.create_order" | "whatsapp.send_text" | "ai.smoke_test" | string;
  providerType: string;
  status: string;
  approvalStatus: string;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: true;
  liveExecutionRequested: boolean;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  externalCallWasMade: false;
  providerCallAttempted: false;
  killSwitchActive: boolean;
  riskLevel: string;
  payloadHash: string;
  safePayloadSummary: Record<string, unknown>;
  blockers: string[];
  warnings: string[];
  gateDecision: SaasLiveGateDecision;
  idempotencyKey: string;
  simulationResult: Record<string, unknown>;
  preparedBy: number | null;
  approvalRequestedBy: number | null;
  approvedBy: number | null;
  rejectedBy: number | null;
  runBy: number | null;
  rolledBackBy: number | null;
  preparedAt: string | null;
  approvalRequestedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  runAt: string | null;
  rolledBackAt: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  nextAction: string;
}

export interface SaasRuntimeLiveGateSimulationSummary {
  organization: { id: number; code: string; name: string } | null;
  allowedOperations: string[];
  defaultOperation: "razorpay.create_order";
  simulationCount: number;
  approvalPendingCount: number;
  approvedCount: number;
  simulatedCount: number;
  latestSimulation: SaasRuntimeLiveGateSimulation | null;
  dryRun: true;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  externalCallWasMade: false;
  providerCallAttempted: false;
  killSwitchActive: boolean;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  safeToPreparePhase6ISimulation: boolean;
  safeToRunInternalSimulation: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasRuntimeLiveGateSimulationsResponse {
  count: number;
  simulations: SaasRuntimeLiveGateSimulation[];
  allowedOperations: string[];
  defaultOperation: "razorpay.create_order";
  dryRun: true;
  liveExecutionAllowed: false;
  externalCallWillBeMade: false;
  externalCallWasMade: false;
  providerCallAttempted: false;
  killSwitchActive: boolean;
  summary?: SaasRuntimeLiveGateSimulationSummary;
}

// ---------- Phase 6J - Single Internal Provider Test Plan ----------

export type SaasProviderTestPlanStatus =
  | "draft"
  | "prepared"
  | "validated"
  | "approval_required"
  | "approved_for_future_execution"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasProviderTestPlanPolicyEntry {
  operationType: string;
  providerType: string;
  providerEnvironment: "test" | "sandbox" | "production";
  realMoney: false;
  realCustomerDataAllowed: false;
  externalProviderCallAllowedInPhase6J: false;
  providerCallAllowed: false;
  approvalRequired: boolean;
  liveGateRequired: boolean;
  killSwitchMustRemainEnabled: boolean;
  idempotencyRequired: boolean;
  webhookRequiredForFutureExecution: boolean;
  syntheticPayloadRequired: boolean;
  safeAmountOnly: boolean;
  maxTestAmountPaise: number;
  currency: string;
  nextPhaseForExecution: string;
  rollbackRequired: boolean;
  auditRequired: boolean;
  implementationTargetInPhase6J: boolean;
  notes: string;
  requiredEnvKeys: string[];
  optionalEnvKeys: string[];
  requiredConfigKeys: string[];
  policyVersion: string;
  metadata: Record<string, unknown>;
}

export interface SaasProviderTestPlanEnvReadiness {
  providerType: string;
  envPresence: Record<string, boolean>;
  secretRefStatus: Record<string, {
    valid: boolean;
    source: string;
    maskedRef: string;
    present: boolean | null;
    canResolveAtRuntime: boolean;
    reason: string;
  }>;
  maskedSecretRefs: Record<string, string>;
  envReady: boolean;
  webhookReady: boolean;
}

export interface SaasProviderTestPlan {
  id: number;
  planId: string;
  organization: { id: number; code: string; name: string } | null;
  branch: { id: number; code: string; name: string } | null;
  providerType: string;
  operationType: string;
  providerEnvironment: "test" | "sandbox" | "production";
  status: SaasProviderTestPlanStatus;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: true;
  providerCallAllowed: false;
  externalCallWillBeMade: false;
  externalCallWasMade: false;
  providerCallAttempted: false;
  realCustomerDataAllowed: false;
  realMoney: false;
  amountPaise: number | null;
  currency: string;
  idempotencyKey: string;
  payloadHash: string;
  safePayloadSummary: Record<string, unknown>;
  envReadiness: SaasProviderTestPlanEnvReadiness;
  secretRefReadiness: Record<string, unknown>;
  gateRequirements: Record<string, unknown>;
  approvalRequirements: Record<string, unknown>;
  rollbackPlan: Record<string, unknown>;
  abortCriteria: string[];
  verificationChecklist: Array<{ key: string; expected: unknown }>;
  blockers: string[];
  warnings: string[];
  nextPhase: string;
  requestedBy: number | null;
  approvedBy: number | null;
  rejectedBy: number | null;
  archivedBy: number | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  nextAction: string;
}

export interface SaasProviderTestPlanReadiness {
  organization: { id: number; code: string; name: string } | null;
  policyVersion: string;
  phase6jImplementationTargets: string[];
  policies: SaasProviderTestPlanPolicyEntry[];
  planCount: number;
  preparedCount: number;
  validatedCount: number;
  approvedCount: number;
  archivedCount: number;
  blockedCount: number;
  providerCallAttemptedCount: number;
  externalCallMadeCount: number;
  latestPlan: SaasProviderTestPlan | null;
  plans: SaasProviderTestPlan[];
  killSwitchActive: boolean;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: true;
  providerCallAllowed: false;
  externalCallWillBeMade: false;
  externalCallWasMade: false;
  providerCallAttempted: false;
  safeToStartPhase6K: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6K - Single Internal Razorpay Test-Mode Execution Gate ----------

export type SaasProviderExecutionStatus =
  | "prepared"
  | "blocked"
  | "ready"
  | "executing"
  | "succeeded"
  | "failed"
  | "rolled_back"
  | "archived";

export type SaasProviderExecutionRollbackStatus =
  | "not_required"
  | "ready"
  | "completed"
  | "failed";

export interface SaasProviderExecutionPolicy {
  operationType: string;
  providerType: string;
  providerEnvironment: "test" | "sandbox" | "production";
  allowedInPhase6K: boolean;
  amountPaise: number;
  currency: string;
  realMoney: false;
  realCustomerDataAllowed: false;
  syntheticPayloadRequired: true;
  approvedProviderTestPlanRequired: true;
  idempotencyRequired: true;
  explicitCliConfirmationRequired: true;
  envFlagRequired: true;
  envFlagName: string;
  apiExecutionAllowed: false;
  frontendExecutionAllowed: false;
  maxExecutionsPerApprovedPlan: number;
  safeResponseSummaryOnly: true;
  businessMutationAllowed: false;
  paymentLinkCreationAllowed: false;
  captureAllowed: false;
  customerNotificationAllowed: false;
  requiredEnvKeys: string[];
  nextPhaseAfterSuccess: string;
  notes: string;
  policyVersion: string;
}

export interface SaasProviderExecutionEnvReadiness {
  envFlag: string;
  envFlagPresent: boolean;
  envFlagEnabled: boolean;
  razorpayKeyIdPresent: boolean;
  razorpayKeyMode: "test" | "live" | "unknown" | "missing";
  razorpayKeyIdMasked: string;
  razorpayKeySecretPresent: boolean;
  razorpayWebhookSecretPresent: boolean;
  isTestKey: boolean;
  isLiveKey: boolean;
}

export interface SaasProviderExecutionAttempt {
  id: number;
  executionId: string;
  planId: string;
  organization: { id: number; code: string; name: string } | null;
  branch: { id: number; code: string; name: string } | null;
  providerType: string;
  operationType: string;
  providerEnvironment: "test" | "sandbox" | "production";
  status: SaasProviderExecutionStatus;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  dryRun: boolean;
  testMode: true;
  realMoney: false;
  realCustomerDataAllowed: false;
  amountPaise: number;
  currency: string;
  providerCallAllowed: boolean;
  externalCallWillBeMade: boolean;
  externalCallWasMade: boolean;
  providerCallAttempted: boolean;
  businessMutationWasMade: false;
  paymentLinkCreated: false;
  paymentCaptured: false;
  customerNotificationSent: false;
  idempotencyKey: string;
  receipt: string;
  requestPayloadHash: string;
  safeRequestSummary: Record<string, unknown>;
  safeResponseSummary: Record<string, unknown>;
  providerObjectId: string;
  providerStatus: string;
  envReadiness: SaasProviderExecutionEnvReadiness;
  gateDecision: string;
  blockers: string[];
  warnings: string[];
  rollbackPlan: Record<string, unknown>;
  rollbackStatus: SaasProviderExecutionRollbackStatus;
  requestedBy: number | null;
  executedBy: number | null;
  rolledBackBy: number | null;
  archivedBy: number | null;
  executedAt: string | null;
  rolledBackAt: string | null;
  archivedAt: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  nextAction: string;
}

export interface SaasProviderExecutionReadiness {
  organization: { id: number; code: string; name: string } | null;
  policyVersion: string;
  envReadiness: SaasProviderExecutionEnvReadiness;
  killSwitchActive: boolean;
  latestApprovedPlan: {
    planId: string;
    providerType: string;
    operationType: string;
    providerEnvironment: string;
    amountPaise: number;
    currency: string;
    status: string;
    approvedAt: string | null;
  } | null;
  executionAttemptCount: number;
  successfulExecutionCount: number;
  failedExecutionCount: number;
  blockedExecutionCount: number;
  rolledBackExecutionCount: number;
  archivedExecutionCount: number;
  providerCallAttemptedCount: number;
  externalCallMadeCount: number;
  businessMutationCount: number;
  latestAttempt: SaasProviderExecutionAttempt | null;
  attempts: SaasProviderExecutionAttempt[];
  policy: SaasProviderExecutionPolicy | null;
  runtimeSource: "env_config";
  perOrgRuntimeEnabled: false;
  safeToRunPhase6KExecution: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6L - Razorpay Test Execution Audit Review + Webhook Readiness ----------

export interface SaasRazorpayAuditInvariant {
  key: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
}

export interface SaasRazorpayAuditEvent {
  id: number;
  kind: string;
  tone: string;
  createdAt: string;
  text: string;
  payloadKeys: string[];
}

export interface SaasRazorpayAuditReview {
  passed: boolean;
  executionId: string;
  planId?: string;
  providerType?: string;
  operationType?: string;
  providerEnvironment?: string;
  status?: string;
  providerObjectId?: string;
  providerStatus?: string;
  amountPaise?: number;
  currency?: string;
  rollbackStatus?: string;
  envSnapshot?: {
    envFlagEnabled: boolean;
    razorpayKeyMode: string;
    razorpayKeyIdMasked: string;
    razorpayWebhookSecretPresent: boolean;
  };
  invariantResults?: SaasRazorpayAuditInvariant[];
  auditEventCount?: number;
  auditEvents?: SaasRazorpayAuditEvent[];
  safeResponseSummary?: Record<string, unknown>;
  rawSecretLeakDetected?: boolean;
  blockers: string[];
  warnings: string[];
  errors?: string[];
  nextAction: string;
}

export interface SaasRazorpayWebhookReadiness {
  razorpayKeyMode: string;
  razorpayKeyIdMasked: string;
  razorpayKeyIdPresent: boolean;
  razorpayKeySecretPresent: boolean;
  razorpayWebhookSecretPresent: boolean;
  envFlagEnabled: boolean;
  isTestKey: boolean;
  isLiveKey: boolean;
  latestSucceededExecutionId: string | null;
  latestSucceededProviderObjectId: string | null;
  latestSucceededRollbackStatus: string | null;
  latestPhase6KArtefactExecutionId: string | null;
  phase6KSucceededExecutionCount: number;
  blockers: string[];
  warnings: string[];
  safeToPlanWebhookReadiness: boolean;
  nextAction: string;
}

export interface SaasRazorpayWebhookPlan {
  phase: "6L";
  policyVersion: string;
  summary: string;
  preconditions: Record<string, boolean>;
  envReadiness: SaasRazorpayWebhookReadiness;
  endpointDesign: {
    path: string;
    method: string;
    csrfExempt: boolean;
    authentication: string;
    phase6LRegistration: false;
    phase6MRegistration: boolean;
  };
  signatureVerificationDesign: {
    algorithm: string;
    secretSource: string;
    header: string;
    rawBodyMustBeUsed: boolean;
    constantTimeCompare: boolean;
    rejectOnMissingHeader: boolean;
    rejectOnEmptySecret: boolean;
    implementationReference: string;
  };
  idempotencyDesign: {
    key: string;
    fallbackKey: string;
    storage: string;
    uniqueConstraint: boolean;
    duplicateBehaviour: string;
  };
  eventAllowlist: string[];
  eventDenylist: string[];
  replayProtection: {
    windowSeconds: number;
    rejectOlderThanWindow: boolean;
    useEventCreatedAt: boolean;
    audit: string;
  };
  auditLoggingPlan: {
    kindsToAdd: string[];
    phase6LAuditMutationAllowed: false;
    phase6MAuditMutationAllowed: boolean;
    payloadHandling: {
      storeRawBody: false;
      storePayloadHash: boolean;
      storePayloadKeysOnly: boolean;
      sensitiveKeysToScrub: string[];
    };
  };
  testModeOnlyValidationPlan: {
    razorpayKeyModeMustBeTest: boolean;
    envFlagPattern: string;
    phase6MWebhookHandlerEnabledByDefault: false;
    phase6MMaxEventsPerRun: number;
    phase6MEventCanMutateBusinessTables: false;
  };
  businessMutationPolicy: Record<string, false>;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  nextPhase: string;
}

// ---------- Phase 6M-0 - MCP Gateway Foundation ----------

export interface McpGatewayReadiness {
  mcpEnabled: boolean;
  transport: string;
  publicBaseUrlConfigured: boolean;
  requireAuth: boolean;
  readOnlyMode: boolean;
  writeToolsEnabled: boolean;
  providerToolsEnabled: boolean;
  auditEnabled: boolean;
  maskPii: boolean;
  tokenTtlSeconds: number;
  maxToolCallsPerMinute: number;
  maxOutputChars: number;
  exposeResources: boolean;
  exposePrompts: boolean;
  toolCount: number;
  enabledToolCount: number;
  writeToolEnabledCount: number;
  providerToolEnabledCount: number;
  forbiddenToolsRegisteredCount: number;
  resourceCount: number;
  promptCount: number;
  activeClientCount: number;
  registeredClientCount: number;
  recentInvocationCount: number;
  rawSecretExposureCount: number;
  fullPiiExposureCount: number;
  providerCallAttemptedCount: number;
  businessMutationAttemptedCount: number;
  enabledScopes: string[];
  futureDisabledScopes: string[];
  forbiddenTools: string[];
  blockers: string[];
  warnings: string[];
  safeToEnableReadOnlyMcp: boolean;
  safeToStartPhase6M: boolean;
  nextAction: string;
}

export interface McpSecurityPosture {
  forbiddenToolsRegistered: boolean;
  writeToolsEnabled: boolean;
  providerToolsEnabled: boolean;
  writeToolEnabledCount: number;
  providerToolEnabledCount: number;
  authRequired: boolean;
  rawSecretExposureCount: number;
  piiExposureCount: number;
  providerCallAttemptedCount: number;
  businessMutationAttemptedCount: number;
  blockers: string[];
  warnings: string[];
  safe: boolean;
  nextAction: string;
}

export interface McpToolDefinitionDto {
  id: number;
  name: string;
  title: string;
  description: string;
  category: string;
  handlerKey: string;
  enabled: boolean;
  readOnly: boolean;
  riskLevel: "low" | "medium" | "high" | "critical";
  requiresAuth: boolean;
  requiresOrgContext: boolean;
  requiresHumanApproval: boolean;
  providerCallAllowed: boolean;
  businessMutationAllowed: boolean;
  piiExposureLevel: "none" | "masked" | "sensitive_blocked";
  requiredScopes: string[];
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

export interface McpToolsResponse {
  count: number;
  tools: McpToolDefinitionDto[];
  readOnlyMode: true;
  writeToolsEnabled: false;
  providerToolsEnabled: false;
}

export interface McpResourceDefinitionDto {
  id: number;
  uri: string;
  name: string;
  title: string;
  description: string;
  mimeType: string;
  enabled: boolean;
  readOnly: boolean;
  requiresAuth: boolean;
  requiredScopes: string[];
  piiExposureLevel: string;
  handlerKey: string;
}

export interface McpResourcesResponse {
  count: number;
  resources: McpResourceDefinitionDto[];
}

export interface McpPromptDefinitionDto {
  id: number;
  name: string;
  title: string;
  description: string;
  templatePreview: string;
  variablesSchema: Record<string, unknown>;
  enabled: boolean;
  requiresAuth: boolean;
  requiredScopes: string[];
  riskLevel: string;
}

export interface McpPromptsResponse {
  count: number;
  prompts: McpPromptDefinitionDto[];
}

export interface McpToolInvocationDto {
  id: number;
  invocationId: string;
  toolName: string;
  toolCategory: string;
  status:
    | "allowed"
    | "denied"
    | "blocked"
    | "succeeded"
    | "failed";
  deniedReason: string;
  riskLevel: string;
  readOnly: boolean;
  providerCallAllowed: boolean;
  businessMutationAllowed: boolean;
  providerCallAttempted: boolean;
  businessMutationAttempted: boolean;
  rawSecretExposed: boolean;
  fullPiiExposed: boolean;
  outputTruncated: boolean;
  durationMs: number | null;
  errorSummary: string;
  createdAt: string;
}

export interface McpInvocationsResponse {
  count: number;
  limit: number;
  invocations: McpToolInvocationDto[];
  providerCallAttempted: false;
  businessMutationAttempted: false;
}

export interface McpToolSimulationResult {
  passed: boolean;
  status:
    | "succeeded"
    | "failed"
    | "blocked"
    | "denied"
    | "allowed";
  toolName: string;
  invocationId: string;
  readOnly?: boolean;
  blockedReason?: string;
  providerCallAttempted: boolean;
  businessMutationAttempted: boolean;
  rawSecretExposed?: boolean;
  fullPiiExposed?: boolean;
  outputTruncated?: boolean;
  durationMs?: number;
  result: Record<string, unknown> | null;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6M - Razorpay Webhook Handler (test-mode) ----------

export interface SaasRazorpayWebhookHandlerReadiness {
  phase: "6M";
  webhookTestModeEnabled: boolean;
  webhookSecretPresent: boolean;
  businessMutationEnabled: boolean;
  customerNotificationEnabled: boolean;
  storeRawPayload: boolean;
  allowTestEventsOnly: boolean;
  replayWindowSeconds: number;
  allowedEvents: string[];
  deniedEvents: string[];
  eventCount: number;
  verifiedEventCount: number;
  duplicateEventCount: number;
  blockedEventCount: number;
  businessMutationCount: number;
  customerNotificationCount: number;
  rawSecretExposureCount: number;
  fullPiiExposureCount: number;
  safeToReceiveTestWebhooks: boolean;
  safeToStartPhase6N: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasRazorpayWebhookEventDto {
  id: number;
  sourceEventId: string;
  eventId: string;
  eventName: string;
  environment: string;
  signaturePresent: boolean;
  signatureValid: boolean;
  replayWindowValid: boolean;
  idempotencyStatus: string;
  processingStatus: string;
  processingMode: string;
  providerOrderId: string;
  providerPaymentId: string;
  providerRefundId: string;
  amountPaise: number | null;
  currency: string;
  paymentStatus: string;
  orderStatus: string;
  businessMutationAttempted: boolean;
  businessMutationWasMade: boolean;
  customerNotificationAttempted: boolean;
  customerNotificationSent: boolean;
  rawSecretExposed: boolean;
  fullPiiExposed: boolean;
  duplicateCount: number;
  deniedReason: string;
  blockers: string[];
  warnings: string[];
  scrubbedKeys: string[];
  receivedAt: string;
}

export interface SaasRazorpayWebhookEventsResponse {
  count: number;
  limit: number;
  events: SaasRazorpayWebhookEventDto[];
  businessMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
}

export interface SaasRazorpayWebhookSimulationResult {
  passed: boolean;
  eventName: string;
  sourceEventId: string;
  signatureValid: boolean;
  idempotencyStatus: string;
  processingStatus: string;
  businessMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

// ---------- Phase 6Q - Payment → Order Workflow Safety Gate ----------

export type SaasRazorpayPaymentOrderWorkflowGateStatus =
  | "draft"
  | "blocked"
  | "pending_manual_review"
  | "approved_for_future_phase6r"
  | "rejected"
  | "archived";

export interface SaasRazorpayPaymentOrderWorkflowContractRow {
  razorpayEventName: string;
  futurePaymentStatus: string;
  futureOrderStatusCandidate: string;
  futureOrderEffect: string;
  workflowAction: string;
  workflowMutationAllowedInPhase6Q: false;
  mutationAllowedInFuturePhase6R: string;
  manualReviewRequired: true;
  customerNotificationAllowed: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  providerCallAllowed: false;
  idempotencyRequired: true;
  rollbackRequired: true;
  blockers: string[];
  notes: string[];
}

export interface SaasRazorpayPaymentOrderWorkflowGateDto {
  id: number;
  sourceAttemptId: number | null;
  sourceLedgerId: number | null;
  sourceReviewId: number | null;
  razorpayWebhookEventId: number | null;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  providerOrderId: string;
  providerPaymentId: string;
  providerPaymentLinkId: string;
  amountPaise: number | null;
  currency: string;
  proposedPaymentStatus: string;
  proposedOrderStatus: string;
  proposedOrderEffect: string;
  proposedWorkflowAction: string;
  status: SaasRazorpayPaymentOrderWorkflowGateStatus;
  phase6PExecutionVerified: boolean;
  phase6PRollbackVerified: boolean;
  syntheticEligible: boolean;
  manualReviewRequired: boolean;
  workflowMutationAllowedInPhase6Q: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  discountMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
  rollbackRequired: boolean;
  idempotencyKey: string;
  blockers: string[];
  warnings: string[];
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReason: string;
  archivedByUsername: string;
  archivedAt: string | null;
  archiveReason: string;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpayPaymentOrderWorkflowGateCounts {
  draft: number;
  pendingManualReview: number;
  approvedForFuturePhase6R: number;
  rejected: number;
  archived: number;
  blocked: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  shipmentMutationWasMade: number;
  discountMutationWasMade: number;
  customerNotificationSent: number;
  providerCallAttempted: number;
}

export interface SaasRazorpayPaymentOrderWorkflowGateReadiness {
  phase: "6Q";
  status: "audit_gate_only";
  latestCompletedPhase: "6P";
  nextPhase: "6R";
  razorpayPaymentOrderWorkflowGateEnabled: boolean;
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  providerCallAttempted: false;
  rawPayloadStorageEnabled: false;
  phase6PExecutedCount: number;
  phase6PRolledBackCount: number;
  gateCounts: SaasRazorpayPaymentOrderWorkflowGateCounts;
  workflowContract: SaasRazorpayPaymentOrderWorkflowContractRow[];
  safetyInvariants: Record<string, boolean>;
  manualReviewChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  rollbackPlan: Record<string, unknown>;
  forbiddenActions: string[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  maxSafeAmountPaise: number;
  safeToStartPhase6R: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentGates: SaasRazorpayPaymentOrderWorkflowGateDto[];
}

export interface SaasRazorpayPaymentOrderWorkflowGatesResponse {
  phase: "6Q";
  limit: number;
  counts: SaasRazorpayPaymentOrderWorkflowGateCounts;
  items: SaasRazorpayPaymentOrderWorkflowGateDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  discountMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
}

// ---------- Phase 6R - Payment → WhatsApp / Courier Dispatch Readiness ----------

export type SaasRazorpayPaymentDispatchReadinessGateStatus =
  | "draft"
  | "blocked"
  | "pending_manual_review"
  | "approved_for_future_phase6s"
  | "rejected"
  | "archived";

export interface SaasRazorpayPaymentDispatchReadinessContractRow {
  razorpayEventName: string;
  futureWhatsAppReadinessAction: string;
  futureCourierReadinessAction: string;
  futureDispatchReadinessAction: string;
  whatsappSendAllowedInPhase6R: false;
  courierBookingAllowedInPhase6R: false;
  providerCallAllowedInPhase6R: false;
  mutationAllowedInFuturePhase6S: string;
  manualReviewRequired: true;
  customerNotificationAllowed: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  idempotencyRequired: true;
  rollbackRequired: true;
  blockers: string[];
  notes: string[];
}

export interface SaasRazorpayPaymentDispatchReadinessGateDto {
  id: number;
  sourceWorkflowGateId: number | null;
  sourceAttemptId: number | null;
  sourceLedgerId: number | null;
  sourceReviewId: number | null;
  razorpayWebhookEventId: number | null;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  providerOrderId: string;
  providerPaymentId: string;
  providerPaymentLinkId: string;
  amountPaise: number | null;
  currency: string;
  proposedPaymentStatus: string;
  proposedOrderStatus: string;
  proposedOrderEffect: string;
  proposedWhatsAppAction: string;
  proposedCourierAction: string;
  proposedDispatchReadinessAction: string;
  status: SaasRazorpayPaymentDispatchReadinessGateStatus;
  phase6QGateApproved: boolean;
  phase6PExecutionVerified: boolean;
  phase6PRollbackVerified: boolean;
  syntheticEligible: boolean;
  manualReviewRequired: boolean;
  dispatchReadinessAllowedInPhase6R: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  razorpayCallAttempted: false;
  providerCallAttempted: false;
  rollbackRequired: boolean;
  idempotencyKey: string;
  blockers: string[];
  warnings: string[];
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReason: string;
  archivedByUsername: string;
  archivedAt: string | null;
  archiveReason: string;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpayPaymentDispatchReadinessGateCounts {
  draft: number;
  pendingManualReview: number;
  approvedForFuturePhase6S: number;
  rejected: number;
  archived: number;
  blocked: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  shipmentMutationWasMade: number;
  shipmentCreated: number;
  whatsAppMessageCreated: number;
  whatsAppMessageQueued: number;
  customerNotificationSent: number;
  metaCloudCallAttempted: number;
  delhiveryCallAttempted: number;
  providerCallAttempted: number;
}

export interface SaasRazorpayPaymentDispatchReadiness {
  phase: "6R";
  status: "dispatch_readiness_only";
  latestCompletedPhase: "6Q";
  nextPhase: "6S";
  razorpayPaymentDispatchReadinessEnabled: boolean;
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  providerCallAttempted: false;
  rawPayloadStorageEnabled: false;
  phase6QApprovedGateCount: number;
  readinessCounts: SaasRazorpayPaymentDispatchReadinessGateCounts;
  readinessContract: SaasRazorpayPaymentDispatchReadinessContractRow[];
  safetyInvariants: Record<string, boolean>;
  whatsAppReadinessChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  courierReadinessChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  dispatchReadinessChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  rollbackPlan: Record<string, unknown>;
  forbiddenActions: string[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  maxSafeAmountPaise: number;
  safeToStartPhase6S: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentReadinessGates: SaasRazorpayPaymentDispatchReadinessGateDto[];
}

export interface SaasRazorpayPaymentDispatchReadinessGatesResponse {
  phase: "6R";
  limit: number;
  counts: SaasRazorpayPaymentDispatchReadinessGateCounts;
  items: SaasRazorpayPaymentDispatchReadinessGateDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  providerCallAttempted: false;
}

// ---------- Phase 6S - Limited Internal Dispatch Pilot Plan ----------

export type SaasRazorpayPaymentDispatchPilotPlanStatus =
  | "draft"
  | "blocked"
  | "pending_manual_review"
  | "approved_for_future_phase6t"
  | "rejected"
  | "archived";

export type SaasRazorpayPaymentDispatchPilotPlanMode =
  | "planning_only"
  | "internal_staff_only";

export interface SaasRazorpayPaymentDispatchPilotContractRow {
  razorpayEventName: string;
  futurePilotEligibility: string;
  futureWhatsAppPilotAction: string;
  futureCourierPilotAction: string;
  futureDispatchPilotAction: string;
  pilotExecutionAllowedInPhase6S: false;
  whatsappSendAllowedInPhase6S: false;
  courierBookingAllowedInPhase6S: false;
  providerCallAllowedInPhase6S: false;
  mutationAllowedInFuturePhase6T: string;
  manualReviewRequired: true;
  internalStaffOnly: true;
  maxPilotOrders: number;
  maxAmountPaise: number;
  customerNotificationAllowed: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  idempotencyRequired: true;
  rollbackRequired: true;
  abortCriteria: string[];
  blockers: string[];
  notes: string[];
}

export interface SaasRazorpayPaymentDispatchPilotPlanDto {
  id: number;
  sourceReadinessGateId: number | null;
  sourceWorkflowGateId: number | null;
  sourceAttemptId: number | null;
  sourceLedgerId: number | null;
  sourceReviewId: number | null;
  razorpayWebhookEventId: number | null;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  providerOrderId: string;
  providerPaymentId: string;
  providerPaymentLinkId: string;
  amountPaise: number | null;
  currency: string;
  proposedPilotScope: string;
  proposedPaymentStatus: string;
  proposedOrderStatus: string;
  proposedOrderEffect: string;
  proposedWhatsAppAction: string;
  proposedCourierAction: string;
  proposedDispatchAction: string;
  pilotMode: SaasRazorpayPaymentDispatchPilotPlanMode;
  status: SaasRazorpayPaymentDispatchPilotPlanStatus;
  internalOnly: boolean;
  maxPilotOrders: number;
  maxAmountPaise: number;
  allowedCustomerScope: string;
  allowedStaffCohort: Array<Record<string, unknown>>;
  allowedEventNames: string[];
  manualReviewRequired: boolean;
  pilotExecutionAllowedInPhase6S: false;
  liveSendAllowedInPhase6S: false;
  courierBookingAllowedInPhase6S: false;
  providerCallAllowedInPhase6S: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  awbCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  razorpayCallAttempted: false;
  providerCallAttempted: false;
  rollbackRequired: boolean;
  idempotencyKey: string;
  blockers: string[];
  warnings: string[];
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReason: string;
  archivedByUsername: string;
  archivedAt: string | null;
  archiveReason: string;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpayPaymentDispatchPilotPlanCounts {
  draft: number;
  pendingManualReview: number;
  approvedForFuturePhase6T: number;
  rejected: number;
  archived: number;
  blocked: number;
  pilotExecutionAllowedInPhase6S: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  shipmentMutationWasMade: number;
  shipmentCreated: number;
  awbCreated: number;
  whatsAppMessageCreated: number;
  whatsAppMessageQueued: number;
  customerNotificationSent: number;
  metaCloudCallAttempted: number;
  delhiveryCallAttempted: number;
  providerCallAttempted: number;
}

export interface SaasRazorpayPaymentDispatchPilotPlanReadiness {
  phase: "6S";
  status: "pilot_planning_only";
  latestCompletedPhase: "6R";
  nextPhase: "6T";
  razorpayPaymentDispatchPilotPlanEnabled: boolean;
  pilotExecutionEnabled: false;
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  providerCallAttempted: false;
  rawPayloadStorageEnabled: false;
  phase6RApprovedReadinessGateCount: number;
  pilotPlanCounts: SaasRazorpayPaymentDispatchPilotPlanCounts;
  pilotContract: SaasRazorpayPaymentDispatchPilotContractRow[];
  safetyInvariants: Record<string, boolean>;
  internalStaffCohortChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  whatsAppPilotChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  courierPilotChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  dispatchPilotChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  killSwitchRequirements: Record<string, unknown>;
  approvalRequirements: Record<string, unknown>;
  rollbackPlan: Record<string, unknown>;
  abortCriteria: string[];
  verificationChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  forbiddenActions: string[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  maxSafeAmountPaise: number;
  maxPilotOrders: number;
  safeToStartPhase6T: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentPilotPlans: SaasRazorpayPaymentDispatchPilotPlanDto[];
}

export interface SaasRazorpayPaymentDispatchPilotPlansResponse {
  phase: "6S";
  limit: number;
  counts: SaasRazorpayPaymentDispatchPilotPlanCounts;
  items: SaasRazorpayPaymentDispatchPilotPlanDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  pilotExecutionAllowedInPhase6S: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  awbCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  providerCallAttempted: false;
}

// ---------- Phase 6T - Final Phase 6 Audit + Lock ----------

export type SaasRazorpayPhase6FinalAuditLockStatus =
  | "draft"
  | "blocked"
  | "pending_manual_review"
  | "locked_for_future_controlled_pilot_review"
  | "rejected"
  | "archived";

export interface SaasRazorpayPhase6FinalAuditContractRow {
  phase: "6N" | "6O" | "6P" | "6Q" | "6R" | "6S";
  label: string;
  requiredStatus: string;
  actualStatus: string;
  verified: boolean;
  mutationAllowedInPhase: false;
  providerCallAllowedInPhase: false;
  customerNotificationAllowedInPhase: false;
  frontendExecutionAllowed: false;
  apiExecutionAllowed: false;
  cliOnlyReview: true;
  requiredEvidence: string[];
  blockers: string[];
  warnings: string[];
  notes: string[];
}

export interface SaasRazorpayPhase6FinalAuditLockDto {
  id: number;
  sourcePilotPlanId: number | null;
  sourceReadinessGateId: number | null;
  sourceWorkflowGateId: number | null;
  sourceAttemptId: number | null;
  sourceLedgerId: number | null;
  sourceReviewId: number | null;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  amountPaise: number | null;
  currency: string;
  status: SaasRazorpayPhase6FinalAuditLockStatus;
  fullChainVerified: boolean;
  finalAuditPassed: boolean;
  futureExecutionAllowedByPhase6T: false;
  controlledPilotExecutionAllowedInPhase6T: false;
  manualReviewRequired: boolean;
  internalOnly: boolean;
  maxPilotOrders: number;
  maxAmountPaise: number;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  awbCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  razorpayCallAttempted: false;
  providerCallAttempted: false;
  finalAttestation: Record<string, unknown>;
  directorSignoffContract: Record<string, unknown>;
  killSwitchContract: Record<string, unknown>;
  rollbackContract: Record<string, unknown>;
  abortCriteria: Array<Record<string, string>>;
  operatorChecklist: Array<Record<string, string>>;
  blockers: string[];
  warnings: string[];
  safetyInvariants: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpayPhase6FinalAuditLockCounts {
  draft: number;
  pendingManualReview: number;
  lockedForFutureControlledPilotReview: number;
  rejected: number;
  archived: number;
  blocked: number;
  futureExecutionAllowedByPhase6T: number;
  controlledPilotExecutionAllowedInPhase6T: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  shipmentMutationWasMade: number;
  shipmentCreated: number;
  awbCreated: number;
  whatsAppMessageCreated: number;
  whatsAppMessageQueued: number;
  customerNotificationSent: number;
  metaCloudCallAttempted: number;
  delhiveryCallAttempted: number;
  razorpayCallAttempted: number;
  providerCallAttempted: number;
}

export interface SaasRazorpayPhase6FinalAuditLockReadiness {
  phase: "6T";
  status: "final_audit_lock_only";
  latestCompletedPreviousPhase: "6S";
  nextPhase: string;
  razorpayPhase6FinalAuditLockEnabled: boolean;
  futureControlledPilotAllowedByPhase6T: false;
  controlledPilotExecutionAllowedInPhase6T: false;
  pilotExecutionAllowed: false;
  realBusinessMutation: false;
  realOrderMutation: false;
  realPaymentMutation: false;
  whatsAppSend: false;
  whatsAppQueued: false;
  metaCloudCall: false;
  delhiveryCall: false;
  razorpayCall: false;
  shipmentCreated: false;
  awbCreated: false;
  customerNotification: false;
  providerCall: false;
  approvedPhase6SPilotPlanCount: number;
  finalAuditLockCounts: SaasRazorpayPhase6FinalAuditLockCounts;
  auditChain: SaasRazorpayPhase6FinalAuditContractRow[];
  finalAttestation: Record<string, unknown>;
  directorSignoffContract: Record<string, unknown>;
  killSwitchContract: Record<string, unknown>;
  rollbackContract: Record<string, unknown>;
  abortCriteria: Array<Record<string, string>>;
  operatorChecklist: Array<Record<string, string>>;
  safetyInvariants: Record<string, unknown>;
  safeToStartFutureControlledPilot: boolean;
  safeToStartPhase7A: false;
  executionPath: "cli_only_review";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentFinalAuditLocks: SaasRazorpayPhase6FinalAuditLockDto[];
}

export interface SaasRazorpayPhase6FinalAuditLocksResponse {
  phase: "6T";
  status: "final_audit_lock_only";
  limit: number;
  counts: SaasRazorpayPhase6FinalAuditLockCounts;
  items: SaasRazorpayPhase6FinalAuditLockDto[];
  executionPath: "cli_only_review";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  futureControlledPilotAllowedByPhase6T: false;
  controlledPilotExecutionAllowedInPhase6T: false;
  pilotExecutionAllowed: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  awbCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  razorpayCallAttempted: false;
  providerCallAttempted: false;
}

// ---------- Phase 7B - Controlled Pilot Execution Gate (gate-only) ----------

export type SaasRazorpayControlledPilotGateStatus =
  | "draft"
  | "blocked"
  | "pending_manual_review"
  | "approved_for_future_phase7c_execution_review"
  | "rejected"
  | "archived";

export interface SaasRazorpayControlledPilotGateDto {
  id: number;
  sourceFinalAuditLockId: number | null;
  sourcePilotPlanId: number | null;
  sourceReadinessGateId: number | null;
  sourceWorkflowGateId: number | null;
  sourceAttemptId: number | null;
  sourceLedgerId: number | null;
  sourceReviewId: number | null;
  sourceEventRecordId: number | null;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  amountPaise: number | null;
  currency: string;
  status: SaasRazorpayControlledPilotGateStatus;
  phase6TLockVerified: boolean;
  phase6SPilotPlanVerified: boolean;
  phase6RReadinessVerified: boolean;
  phase6QWorkflowGateVerified: boolean;
  phase6PAttemptVerified: boolean;
  phase6OReviewVerified: boolean;
  phase6MEventVerified: boolean;
  fullChainVerified: boolean;
  dryRunPassed: boolean;
  rollbackDryRunPassed: boolean;
  manualReviewRequired: boolean;
  internalOnly: boolean;
  maxPilotOrders: number;
  maxAmountPaise: number;
  controlledPilotExecutionAllowedInPhase7B: false;
  liveExecutionAllowedInPhase7B: false;
  providerCallAllowedInPhase7B: false;
  businessMutationAllowedInPhase7B: false;
  customerNotificationAllowedInPhase7B: false;
  whatsAppSendAllowedInPhase7B: false;
  whatsAppQueueAllowedInPhase7B: false;
  courierBookingAllowedInPhase7B: false;
  shipmentCreationAllowedInPhase7B: false;
  awbCreationAllowedInPhase7B: false;
  frontendExecutionAllowedInPhase7B: false;
  apiExecutionAllowedInPhase7B: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  awbCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  razorpayCallAttempted: false;
  providerCallAttempted: false;
  envFlagFlipDetected: false;
  rawSecretExposed: false;
  fullPiiExposed: false;
  idempotencyKey: string;
  blockers: string[];
  warnings: string[];
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReason: string;
  archivedByUsername: string;
  archivedAt: string | null;
  archiveReason: string;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpayControlledPilotGateCounts {
  draft: number;
  pendingManualReview: number;
  approvedForFuturePhase7CExecutionReview: number;
  rejected: number;
  archived: number;
  blocked: number;
  controlledPilotExecutionAllowedInPhase7B: number;
  providerCallAttempted: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  shipmentCreated: number;
  awbCreated: number;
  whatsAppMessageCreated: number;
  whatsAppMessageQueued: number;
  customerNotificationSent: number;
  metaCloudCallAttempted: number;
  delhiveryCallAttempted: number;
  razorpayCallAttempted: number;
}

export interface SaasRazorpayControlledPilotGateReadiness {
  phase: "7B";
  status: "controlled_pilot_gate_only";
  latestCompletedPhase: "6T";
  nextPhase: "7C_not_approved";
  phase7ControlledPilotGateEnabled: boolean;
  phase7BMakesProviderCall: false;
  phase7BSendsOrQueuesWhatsApp: false;
  phase7BCreatesShipmentOrAwb: false;
  phase7BMutatesBusinessRow: false;
  phase7BSendsCustomerNotification: false;
  phase7BCallsRazorpay: false;
  phase7BValidatesLiveRazorpayKey: false;
  phase7BRazorpayKeyDisplayPolicy: string;
  phase6TLockedForFutureControlledPilotReviewCount: number;
  controlledPilotGateCounts: SaasRazorpayControlledPilotGateCounts;
  controlledPilotGateContract: Record<string, unknown>;
  safetyInvariants: Record<string, unknown>;
  internalStaffCohortChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  killSwitchRequirements: Record<string, unknown>;
  approvalRequirements: Record<string, unknown>;
  rollbackRehearsalSteps: Array<Record<string, unknown>>;
  abortCriteria: string[];
  forbiddenActions: string[];
  executionPath: "cli_only_review";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  maxSafeAmountPaise: number;
  maxPilotOrders: number;
  envPosture: string;
  razorpayKeyValidationOwnedBy: string;
  safeToStartPhase7CExecutionReviewFlow: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentControlledPilotGates: SaasRazorpayControlledPilotGateDto[];
}

export interface SaasRazorpayControlledPilotGatesResponse {
  phase: "7B";
  limit: number;
  counts: SaasRazorpayControlledPilotGateCounts;
  items: SaasRazorpayControlledPilotGateDto[];
  executionPath: "cli_only_review";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  controlledPilotExecutionAllowedInPhase7B: false;
  liveExecutionAllowedInPhase7B: false;
  providerCallAllowedInPhase7B: false;
  businessMutationAllowedInPhase7B: false;
  customerNotificationAllowedInPhase7B: false;
  whatsAppSendAllowedInPhase7B: false;
  whatsAppQueueAllowedInPhase7B: false;
  courierBookingAllowedInPhase7B: false;
  shipmentCreationAllowedInPhase7B: false;
  awbCreationAllowedInPhase7B: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  shipmentMutationWasMade: false;
  shipmentCreated: false;
  awbCreated: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  customerNotificationSent: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  razorpayCallAttempted: false;
  providerCallAttempted: false;
}

// ---------- Phase 7F - Delhivery / Courier Controlled Readiness ----------

export type SaasRazorpayCourierReadinessGateStatus =
  | "draft"
  | "pending_manual_review"
  | "approved_for_future_phase7g_or_courier_execution_review"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasRazorpayCourierReadinessGateDto {
  id: number;
  status: SaasRazorpayCourierReadinessGateStatus;
  sourcePhase7EGateId: number | null;
  sourcePhase7DAttemptId: number | null;
  sourcePhase7BGateId: number | null;
  sourcePhase6TLockId: number | null;
  delhiveryModeAtPrepare: string;
  delhiveryEnvTokenPresent: boolean;
  delhiveryEnvBaseUrlPresent: boolean;
  delhiveryEnvPickupLocationPresent: boolean;
  delhiveryEnvReturnAddressPresent: boolean;
  sourcePhase7DSignoffWindowValidationStatus:
    | "valid_structured_window"
    | "failed_or_legacy_free_text"
    | "not_applicable";
  phase7DHotfix1Present: boolean;
  dryRunPassed: boolean;
  dryRunFailedReasons: string[];
  rollbackDryRunPassed: boolean;
  rollbackDryRunFailedReasons: string[];
  delhiveryCallAllowedInPhase7F: false;
  courierBookingAllowedInPhase7F: false;
  shipmentCreationAllowedInPhase7F: false;
  awbCreationAllowedInPhase7F: false;
  pickupBookingAllowedInPhase7F: false;
  labelGenerationAllowedInPhase7F: false;
  customerNotificationAllowedInPhase7F: false;
  whatsappSendAllowedInPhase7F: false;
  whatsappQueueAllowedInPhase7F: false;
  metaCloudCallAllowedInPhase7F: false;
  razorpayCallAllowedInPhase7F: false;
  businessMutationAllowedInPhase7F: false;
  realCustomerAllowedInPhase7F: false;
  providerCallAttempted: false;
  delhiveryCallAttempted: false;
  shipmentCreated: false;
  awbCreated: false;
  pickupBooked: false;
  labelGenerated: false;
  customerNotificationSent: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  realShipmentMutationWasMade: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasRazorpayCourierReadinessGateCounts {
  draft: number;
  pending_manual_review: number;
  approved_for_future_phase7g_or_courier_execution_review: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasRazorpayCourierReadiness {
  phase: "7F";
  status: "courier_readiness_only";
  latestCompletedPhase: "7E";
  nextPhase: "7G_or_courier_live_not_approved";
  envFlags: {
    phase7fCourierReadinessGateEnabled: boolean;
  };
  envFlagSnapshot: Record<string, boolean | string>;
  delhiveryEnvPresence: {
    DELHIVERY_API_TOKEN_present: boolean;
    DELHIVERY_API_BASE_URL_present: boolean;
    DELHIVERY_PICKUP_LOCATION_present: boolean;
    DELHIVERY_RETURN_ADDRESS_present: boolean;
  };
  killSwitch: {
    enabled: boolean;
    model: string;
    id?: number;
  };
  phase7DHotfix1Present: boolean;
  phase7EApprovedGateCount: number;
  phase7FGateCounts: SaasRazorpayCourierReadinessGateCounts;
  items: SaasRazorpayCourierReadinessGateDto[];
  phase7DSourceSignoffMayBeLegacyFreeTextWithAck: boolean;
  phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand: boolean;
  phase7FRequiresFutureExecuteWindowGuardForCourier: boolean;
  phase7FCallsDelhivery: false;
  phase7FCreatesShipmentRow: false;
  phase7FCreatesAwb: false;
  phase7FBooksPickup: false;
  phase7FGeneratesLabel: false;
  phase7FSendsCustomerNotification: false;
  phase7FMutatesBusinessRow: false;
  phase7FCallsMetaCloud: false;
  phase7FCallsRazorpay: false;
  phase7FSendsWhatsApp: false;
  phase7FQueuesWhatsApp: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasRazorpayCourierReadinessGatesResponse {
  phase: "7F";
  limit: number;
  counts: SaasRazorpayCourierReadinessGateCounts;
  items: SaasRazorpayCourierReadinessGateDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase7FCallsDelhivery: false;
  phase7FCreatesShipmentRow: false;
  phase7FCreatesAwb: false;
  phase7FBooksPickup: false;
  phase7FGeneratesLabel: false;
  phase7FSendsWhatsApp: false;
  phase7FQueuesWhatsApp: false;
  phase7FCallsMetaCloud: false;
  phase7FCallsRazorpay: false;
  phase7FSendsCustomerNotification: false;
  phase7FMutatesBusinessRow: false;
}

// ---------- Phase 7G - One-shot Delhivery TEST/MOCK Courier Execution Gate ----------

export type SaasRazorpayCourierExecutionAttemptStatus =
  | "draft"
  | "pending_director_signoff"
  | "approved_for_one_shot_courier_test_or_live_review"
  | "executed"
  | "failed"
  | "rolled_back_recorded"
  | "rejected"
  | "archived"
  | "blocked";

export type SaasRazorpayCourierExecutionRollbackStatus =
  | "not_required"
  | "pending"
  | "recorded_only_no_provider_cancel"
  | "cancellation_attempted_separately";

export interface SaasRazorpayCourierExecutionAttemptDto {
  id: number;
  status: SaasRazorpayCourierExecutionAttemptStatus;
  sourcePhase7FGateId: number | null;
  sourcePhase7EGateId: number | null;
  sourcePhase7DAttemptId: number | null;
  sourcePhase7BGateId: number | null;
  sourcePhase6TLockId: number | null;
  delhiveryModeAtEachStep: Record<string, string>;
  delhiveryEnvTokenPresent: boolean;
  delhiveryEnvBaseUrlPresent: boolean;
  delhiveryEnvPickupLocationPresent: boolean;
  delhiveryEnvReturnAddressPresent: boolean;
  killSwitchSnapshotAtEachStep: Record<string, unknown>;
  envFlagSnapshotAtEachStep: Record<string, unknown>;
  safetyInvariantsSnapshot: Record<string, unknown>;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  syntheticOrderId: string;
  syntheticPayloadSummary: Record<string, unknown>;
  idempotencyKey: string;
  idempotencyLockAcquired: boolean;
  providerObjectId: string;
  providerStatus: string;
  safeRequestSummary: Record<string, unknown>;
  safeResponseSummary: Record<string, unknown>;
  // Allowed-True booleans (single-attempt only).
  providerCallAttempted: boolean;
  delhiveryCallAttempted: boolean;
  awbCreated: boolean;
  // Locked-False booleans (always False; surfaced for the section to render).
  shipmentCreated: false;
  businessMutationWasMade: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  realShipmentMutationWasMade: false;
  customerNotificationSent: false;
  recordedSignoffWindowValid: boolean | null;
  recordedSignoffWindowStartUtc: string | null;
  recordedSignoffWindowEndUtc: string | null;
  directorSignoffPresent: boolean;
  directorSignoffPresentBoolean: boolean;
  operatorName: string;
  confirmOneShotCourierExecution: boolean;
  modeAcknowledgement: string;
  rollbackRecordOnlyAcknowledged: boolean;
  rollbackStatus: SaasRazorpayCourierExecutionRollbackStatus;
  rolledBackAt: string | null;
  rollbackReasonPresent: boolean;
  archiveReasonPresent: boolean;
  rejectReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  requestedByUsername: string;
  reviewedByUsername: string;
  executedByUsername: string;
  rolledBackByUsername: string;
  rejectedByUsername: string;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  executedAt: string | null;
  failedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasRazorpayCourierExecutionAttemptCounts {
  draft: number;
  blocked: number;
  pendingDirectorSignoff: number;
  approvedForOneShotRun: number;
  executed: number;
  failed: number;
  rolledBackRecorded: number;
  rejected: number;
  archived: number;
  providerCallAttempted: number;
  delhiveryCallAttempted: number;
  awbCreated: number;
  shipmentCreated: number;
  businessMutationWasMade: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  realShipmentMutationWasMade: number;
  customerNotificationSent: number;
}

export interface SaasRazorpayCourierExecutionReadiness {
  phase: "7G";
  status: "delhivery_test_or_mock_one_shot_courier_execution_only";
  latestCompletedPhase: "7F";
  nextPhase: "phase_7g_live_or_phase_7h_not_approved";
  phase7GCourierExecutionEnabled: boolean;
  phase7GDirectorApprovedOneShotCourierExecution: boolean;
  phase7GAllowDelhiveryTestAwb: boolean;
  phase7GLiveCustomerCourierApproved: false;
  phase7GAllowedDelhiveryModes: string[];
  delhiveryEnvPresence: {
    DELHIVERY_API_TOKEN_present: boolean;
    DELHIVERY_API_BASE_URL_present: boolean;
    DELHIVERY_PICKUP_LOCATION_present: boolean;
    DELHIVERY_RETURN_ADDRESS_present: boolean;
  };
  envFlagSnapshot: Record<string, boolean | string>;
  killSwitch: {
    enabled: boolean;
    model: string;
    id?: number;
  };
  approvedPhase7FGateCount: number;
  attemptCounts: SaasRazorpayCourierExecutionAttemptCounts;
  executionContract: Record<string, unknown>;
  forbiddenActions: string[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase7GCallsDelhivery: false;
  phase7GCreatesShipmentRow: false;
  phase7GCreatesAwbRowOnAttemptOnly: true;
  phase7GBooksCourierPickupSeparately: false;
  phase7GGeneratesCourierLabel: false;
  phase7GSendsWhatsApp: false;
  phase7GQueuesWhatsApp: false;
  phase7GCallsMetaCloud: false;
  phase7GCallsRazorpay: false;
  phase7GCallsVapi: false;
  phase7GSendsCustomerNotification: false;
  phase7GMutatesBusinessRow: false;
  safeToRunPhase7GExecution: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentAttempts: SaasRazorpayCourierExecutionAttemptDto[];
}

export interface SaasRazorpayCourierExecutionAttemptsResponse {
  phase: "7G";
  limit: number;
  counts: SaasRazorpayCourierExecutionAttemptCounts;
  items: SaasRazorpayCourierExecutionAttemptDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase7GCallsDelhivery: false;
  phase7GCreatesShipmentRow: false;
  phase7GCreatesAwbRowOnAttemptOnly: true;
  phase7GBooksCourierPickupSeparately: false;
  phase7GGeneratesCourierLabel: false;
  phase7GSendsWhatsApp: false;
  phase7GQueuesWhatsApp: false;
  phase7GCallsMetaCloud: false;
  phase7GCallsRazorpay: false;
  phase7GCallsVapi: false;
  phase7GSendsCustomerNotification: false;
  phase7GMutatesBusinessRow: false;
  phase7GLiveCustomerCourierApproved: false;
}

// ---------- Phase 7D - Razorpay Controlled Pilot Execution (one-shot TEST) ----------

export type SaasRazorpayControlledPilotExecutionAttemptStatus =
  | "draft"
  | "blocked"
  | "pending_director_signoff"
  | "approved_for_one_shot_run"
  | "executed"
  | "failed"
  | "rolled_back"
  | "archived";

export interface SaasRazorpayControlledPilotExecutionAttemptDto {
  id: number;
  status: SaasRazorpayControlledPilotExecutionAttemptStatus;
  rollbackStatus: "pending" | "completed" | "failed";
  sourcePhase7BGateId: number | null;
  sourcePhase6TLockId: number | null;
  sourcePhase6SPilotPlanId: number | null;
  sourcePhase6RReadinessGateId: number | null;
  sourcePhase6QWorkflowGateId: number | null;
  sourcePhase6PAttemptId: number | null;
  sourcePhase6OReviewId: number | null;
  sourcePhase6MEventId: string;
  providerEnvironment: "test";
  amountPaise: number;
  currency: "INR";
  receipt: string;
  idempotencyKey: string;
  providerObjectId: string;
  providerStatus: string;
  providerCallAttempted: boolean;
  businessMutationWasMade: false;
  paymentLinkCreated: false;
  paymentCaptured: false;
  paymentRefunded: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  whatsAppLifecycleEventCreated: false;
  shipmentCreated: false;
  awbCreated: false;
  metaCloudCallAttempted: false;
  delhiveryCallAttempted: false;
  customerNotificationSent: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  customerMutationWasMade: false;
  leadMutationWasMade: false;
  discountOfferLogMutationWasMade: false;
  mcpToolCalled: false;
  rawSecretExposed: false;
  fullPiiExposed: false;
  blockers: string[];
  warnings: string[];
  createdAt: string;
  updatedAt: string;
  executedAt: string | null;
  rolledBackAt: string | null;
  archivedAt: string | null;
}

export interface SaasRazorpayControlledPilotExecutionAttemptCounts {
  draft: number;
  blocked: number;
  pendingDirectorSignoff: number;
  approvedForOneShotRun: number;
  executed: number;
  failed: number;
  rolledBack: number;
  archived: number;
  providerCallAttempted: number;
  businessMutationWasMade: number;
  paymentLinkCreated: number;
  paymentCaptured: number;
  paymentRefunded: number;
  whatsAppMessageCreated: number;
  whatsAppMessageQueued: number;
  shipmentCreated: number;
  awbCreated: number;
  metaCloudCallAttempted: number;
  delhiveryCallAttempted: number;
  customerNotificationSent: number;
}

export interface SaasRazorpayControlledPilotExecutionReadiness {
  phase: "7D";
  status: "razorpay_test_execution_only";
  latestCompletedPhase: "7B";
  nextPhase: "7E_not_approved";
  envFlags: {
    lifecycleEnabled: boolean;
    directorOneShotApproved: boolean;
    allowRazorpayTestOrder: boolean;
  };
  envFlagSnapshot: Record<string, boolean>;
  razorpayKeyAdvisory: {
    razorpayKeyIdPresent: boolean;
    razorpayKeyIdMasked: string;
    razorpayKeyMode: "test" | "live" | "missing" | "unknown";
    isTestKey: boolean;
  };
  killSwitch: {
    enabled: boolean;
    model: string;
    id?: number;
  };
  approvedPhase7BGateCount: number;
  attemptCounts: SaasRazorpayControlledPilotExecutionAttemptCounts;
  phase7DRazorpayTestExecutionEnabled: boolean;
  phase7DDirectorApprovedOneShotExecution: boolean;
  phase7DAllowRazorpayTestOrder: boolean;
  phase7DSendsOrQueuesWhatsApp: false;
  phase7DCreatesShipmentOrAwb: false;
  phase7DMutatesBusinessRow: false;
  phase7DCallsMetaCloud: false;
  phase7DCallsDelhivery: false;
  phase7DCreatesPaymentLink: false;
  phase7DCapturesPayment: false;
  phase7DRefundsPayment: false;
  phase7DSendsCustomerNotification: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasRazorpayControlledPilotExecutionAttemptsResponse {
  phase: "7D";
  limit: number;
  counts: SaasRazorpayControlledPilotExecutionAttemptCounts;
  items: SaasRazorpayControlledPilotExecutionAttemptDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  controlledPilotExecutionAllowedInPhase7D: false;
  phase7DSendsOrQueuesWhatsApp: false;
  phase7DCallsMetaCloud: false;
  phase7DCallsDelhivery: false;
  phase7DCreatesShipmentOrAwb: false;
  phase7DCreatesPaymentLink: false;
  phase7DCapturesPayment: false;
  phase7DRefundsPayment: false;
  phase7DSendsCustomerNotification: false;
  phase7DMutatesBusinessRow: false;
}

// ---------- Phase 7E - Controlled Internal WhatsApp Notification Readiness ----------

export type SaasRazorpayWhatsAppInternalNotificationGateStatus =
  | "draft"
  | "pending_manual_review"
  | "approved_for_future_phase7f_or_7e_send_review"
  | "rejected"
  | "archived"
  | "blocked";

export type SaasRazorpayWhatsAppInternalNotificationGateSourcePhase7DSignoffWindowValidationStatus =
  | "valid_structured_window"
  | "failed_or_legacy_free_text"
  | "not_applicable";

export interface SaasRazorpayWhatsAppInternalNotificationGateDto {
  id: number;
  status: SaasRazorpayWhatsAppInternalNotificationGateStatus;
  sourcePhase7DAttemptId: number | null;
  sourcePhase7BGateId: number | null;
  sourcePhase6TLockId: number | null;
  targetInternalCohortPhoneSuffixLast4: string;
  proposedTemplateActionKeys: string[];
  proposedTemplateNamesResolved: string[];
  proposedVariableKeys: string[];
  claimVaultGrounded: boolean;
  claimVaultBlockers: string[];
  dryRunPassed: boolean;
  dryRunFailedReasons: string[];
  rollbackDryRunPassed: boolean;
  rollbackDryRunFailedReasons: string[];
  sourcePhase7DSignoffWindowValidationStatus: SaasRazorpayWhatsAppInternalNotificationGateSourcePhase7DSignoffWindowValidationStatus;
  sourcePhase7DWindowViolationAcknowledged: boolean;
  sourcePhase7DWindowViolationAckAt: string | null;
  phase7EFutureReviewSignoffWindowStartUtc: string | null;
  phase7EFutureReviewSignoffWindowEndUtc: string | null;
  phase7EFutureReviewSignoffWindowValid: boolean;
  whatsappSendAllowedInPhase7E: false;
  whatsappQueueAllowedInPhase7E: false;
  metaCloudCallAllowedInPhase7E: false;
  businessMutationAllowedInPhase7E: false;
  customerNotificationAllowedInPhase7E: false;
  realCustomerAllowedInPhase7E: false;
  providerCallAttempted: false;
  whatsAppMessageCreated: false;
  whatsAppMessageQueued: false;
  whatsAppLifecycleEventCreated: false;
  metaCloudCallAttempted: false;
  customerNotificationSent: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasRazorpayWhatsAppInternalNotificationGateCounts {
  draft: number;
  pending_manual_review: number;
  approved_for_future_phase7f_or_7e_send_review: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasRazorpayWhatsAppInternalNotificationReadiness {
  phase: "7E";
  status: "whatsapp_internal_notification_readiness_only";
  latestCompletedPhase: "7D";
  nextPhase: "7F_or_7E_live_not_approved";
  envFlags: {
    phase7eGateEnabled: boolean;
  };
  envFlagSnapshot: Record<string, boolean | string>;
  killSwitch: {
    enabled: boolean;
    model: string;
    id?: number;
  };
  phase7DRolledBackEligibleCount: number;
  phase7DEligibleForPhase7ECount: number;
  gateCounts: SaasRazorpayWhatsAppInternalNotificationGateCounts;
  items: SaasRazorpayWhatsAppInternalNotificationGateDto[];
  phase7DSourceSignoffMayBeLegacyFreeTextWithAck: boolean;
  phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand: boolean;
  phase7ESendsWhatsApp: false;
  phase7EQueuesWhatsApp: false;
  phase7ECallsMetaCloud: false;
  phase7ECallsDelhivery: false;
  phase7ECreatesShipmentOrAwb: false;
  phase7ECreatesPaymentLink: false;
  phase7ECapturesPayment: false;
  phase7ERefundsPayment: false;
  phase7ESendsCustomerNotification: false;
  phase7EMutatesBusinessRow: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasRazorpayWhatsAppInternalNotificationGatesResponse {
  phase: "7E";
  limit: number;
  counts: SaasRazorpayWhatsAppInternalNotificationGateCounts;
  items: SaasRazorpayWhatsAppInternalNotificationGateDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase7ESendsWhatsApp: false;
  phase7EQueuesWhatsApp: false;
  phase7ECallsMetaCloud: false;
  phase7ECallsDelhivery: false;
  phase7ECreatesShipmentOrAwb: false;
  phase7ECreatesPaymentLink: false;
  phase7ECapturesPayment: false;
  phase7ERefundsPayment: false;
  phase7ESendsCustomerNotification: false;
  phase7EMutatesBusinessRow: false;
}

// ---------- Phase 6P - Controlled Internal Paid-Status Mutation Test ----------

export interface SaasRazorpaySandboxPaidStatusEventMapping {
  razorpayEventName: string;
  sandboxPaymentStatus: string;
  sandboxOrderEffect: string;
  realOrderMutationAllowedInPhase6P: false;
  realPaymentMutationAllowedInPhase6P: false;
  customerNotificationAllowed: false;
  providerCallAllowed: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  idempotencyRequired: true;
  rollbackRequired: true;
  executionPath: "cli_only";
  blockers: string[];
}

export type SaasRazorpaySandboxPaidStatusAttemptStatus =
  | "prepared"
  | "blocked"
  | "executed"
  | "rolled_back"
  | "failed"
  | "archived";

export interface SaasRazorpaySandboxPaidStatusAttemptDto {
  id: number;
  reviewId: number;
  ledgerId: number | null;
  razorpayWebhookEventId: number;
  sourceEventId: string;
  eventName: string;
  status: SaasRazorpaySandboxPaidStatusAttemptStatus;
  requestedAction: "apply_sandbox_status" | "rollback_sandbox_status";
  proposedPaymentStatus: string;
  proposedOrderEffect: string;
  beforeState: Record<string, unknown>;
  afterState: Record<string, unknown>;
  blockers: string[];
  warnings: string[];
  confirmationProvided: boolean;
  directorSignoffText: string;
  executedByUsername: string;
  executedAt: string | null;
  rolledBackByUsername: string;
  rolledBackAt: string | null;
  archivedByUsername: string;
  archivedAt: string | null;
  idempotencyKey: string;
  businessMutationWasMade: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpaySandboxPaidStatusLedgerDto {
  id: number;
  reviewId: number;
  razorpayWebhookEventId: number;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  providerOrderId: string;
  providerPaymentId: string;
  providerPaymentLinkId: string;
  providerRefundId: string;
  amountPaise: number | null;
  currency: string;
  sandboxPaymentStatus: string;
  sandboxOrderEffect: string;
  currentState: string;
  previousState: string;
  mutationCount: number;
  lastAttemptId: number | null;
  syntheticEligible: boolean;
  businessMutationWasMade: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
  rollbackRequired: boolean;
  rolledBack: boolean;
  rolledBackAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpaySandboxPaidStatusAttemptCounts {
  prepared: number;
  blocked: number;
  executed: number;
  rolledBack: number;
  failed: number;
  archived: number;
  everExecuted: number;
  everRolledBack: number;
  businessMutationWasMade: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  customerNotificationSent: number;
  providerCallAttempted: number;
}

export interface SaasRazorpaySandboxPaidStatusLedgerCounts {
  totalLedgers: number;
  rolledBackLedgers: number;
  businessMutationWasMade: number;
  realOrderMutationWasMade: number;
  realPaymentMutationWasMade: number;
  customerNotificationSent: number;
  providerCallAttempted: number;
}

export interface SaasRazorpaySandboxPaidStatusMutationReadiness {
  phase: "6P";
  status: "sandbox_ledger_only";
  latestCompletedPhase: "6O";
  nextPhase: "6Q";
  razorpaySandboxPaidStatusMutationEnabled: boolean;
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  providerCallAttempted: false;
  rawPayloadStorageEnabled: false;
  approvedPhase6OReviewCount: number;
  attemptCounts: SaasRazorpaySandboxPaidStatusAttemptCounts;
  ledgerCounts: SaasRazorpaySandboxPaidStatusLedgerCounts;
  eventMappings: SaasRazorpaySandboxPaidStatusEventMapping[];
  safetyInvariants: Record<string, boolean>;
  forbiddenActions: string[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  maxSafeAmountPaise: number;
  safeToStartPhase6Q: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentAttempts: SaasRazorpaySandboxPaidStatusAttemptDto[];
  recentLedgers: SaasRazorpaySandboxPaidStatusLedgerDto[];
}

export interface SaasRazorpaySandboxPaidStatusMutationAttemptsResponse {
  phase: "6P";
  limit: number;
  counts: SaasRazorpaySandboxPaidStatusAttemptCounts;
  items: SaasRazorpaySandboxPaidStatusAttemptDto[];
  ledgerCounts: SaasRazorpaySandboxPaidStatusLedgerCounts;
  ledgerItems: SaasRazorpaySandboxPaidStatusLedgerDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  businessMutationWasMade: false;
  realOrderMutationWasMade: false;
  realPaymentMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
}

// ---------- Phase 6N - Razorpay Business-Mutation Sandbox Plan ----------

export interface SaasRazorpayBusinessMutationEventMapping {
  razorpayEventName: string;
  futureSandboxPaymentStatus: string;
  futureSandboxOrderEffect: string;
  mutationAllowedInPhase6N: false;
  mutationAllowedInFuturePhase6O: string;
  manualReviewRequired: boolean;
  customerNotificationAllowed: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  idempotencyRequired: true;
  rollbackRequired: true;
  blockers: string[];
  notes: string;
}

export interface SaasRazorpayBusinessMutationManualReviewItem {
  key: string;
  description: string;
  automated: boolean;
}

export interface SaasRazorpayBusinessMutationRollbackStep {
  order: number;
  action: string;
  owner: string;
  phase6NEnforced: boolean;
}

export interface SaasRazorpayBusinessMutationRollbackPlan {
  phase: string;
  rollbackTriggers: string[];
  rollbackSteps: SaasRazorpayBusinessMutationRollbackStep[];
  rollbackVerification: string[];
  phase6NCanExecuteRollback: false;
  rollbackOwnedByOperatorOnly: true;
  rollbackNeverInvokesProviderApi: true;
}

export interface SaasRazorpayBusinessMutationSandboxReadiness {
  phase: "6N";
  status: "planning_only";
  latestCompletedPhase: "6M";
  nextPhase: "6O";
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  rawPayloadStorageEnabled: false;
  phase6MWebhookTestModeEnabled: boolean;
  phase6MVerifiedEventCount: number;
  phase6MBusinessMutationCount: number;
  phase6MCustomerNotificationCount: number;
  phase6MRawSecretExposureCount: number;
  phase6MFullPiiExposureCount: number;
  planComplete: boolean;
  eventMappingCount: number;
  manualReviewChecklistSize: number;
  rollbackStepCount: number;
  safetyCountersZero: boolean;
  phase6MFlagsLockedOff: boolean;
  safeToStartPhase6O: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  requiredEnvDefaults: Record<string, boolean>;
  forbiddenActions: string[];
}

// ---------- Phase 6O - Razorpay Sandbox Status Mapping + Manual Review ----------

export interface SaasRazorpaySandboxStatusEventMapping {
  razorpayEventName: string;
  futureSandboxPaymentStatus: string;
  futureSandboxOrderEffect: string;
  proposedReviewAction: string;
  manualReviewRequired: true;
  mutationAllowedInPhase6O: false;
  mutationAllowedInFuturePhase6P: string;
  customerNotificationAllowed: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  idempotencyRequired: true;
  rollbackRequired: true;
  blockers: string[];
  notes: string[];
}

export type SaasRazorpaySandboxStatusReviewStatus =
  | "proposed"
  | "pending_manual_review"
  | "approved_for_future_phase6p"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasRazorpaySandboxStatusReviewDto {
  id: number;
  razorpayWebhookEventId: number;
  sourceEventId: string;
  eventName: string;
  providerEnvironment: string;
  providerOrderId: string;
  providerPaymentId: string;
  providerPaymentLinkId: string;
  providerRefundId: string;
  amountPaise: number | null;
  currency: string;
  proposedPaymentStatus: string;
  proposedOrderEffect: string;
  proposedReviewAction: string;
  status: SaasRazorpaySandboxStatusReviewStatus;
  syntheticEligible: boolean;
  manualReviewRequired: boolean;
  mutationAllowedInPhase6O: false;
  businessMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
  shipmentEffectAllowed: false;
  discountEffectAllowed: false;
  rollbackRequired: boolean;
  idempotencyKey: string;
  blockers: string[];
  warnings: string[];
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReason: string;
  archivedByUsername: string;
  archivedAt: string | null;
  archiveReason: string;
  createdAt: string;
  updatedAt: string;
}

export interface SaasRazorpaySandboxStatusReviewCounts {
  proposed: number;
  pendingManualReview: number;
  approvedForFuturePhase6P: number;
  rejected: number;
  archived: number;
  blocked: number;
  businessMutationWasMade: number;
  customerNotificationSent: number;
  providerCallAttempted: number;
}

export interface SaasRazorpaySandboxStatusMappingReadiness {
  phase: "6O";
  status: "sandbox_review_only";
  latestCompletedPhase: "6N";
  nextPhase: "6P";
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  providerCallAttempted: false;
  rawPayloadStorageEnabled: false;
  razorpaySandboxStatusMappingEnabled: boolean;
  phase6MWebhookTestModeEnabled: boolean;
  phase6MVerifiedEventCount: number;
  phase6MBusinessMutationCount: number;
  phase6MCustomerNotificationCount: number;
  phase6MRawSecretExposureCount: number;
  phase6MFullPiiExposureCount: number;
  reviewCounts: SaasRazorpaySandboxStatusReviewCounts;
  eventMappings: SaasRazorpaySandboxStatusEventMapping[];
  safetyInvariants: Record<string, boolean>;
  manualReviewChecklist: Array<{
    key: string;
    description: string;
    automated: boolean;
  }>;
  rollbackPlan: Record<string, unknown>;
  forbiddenActions: string[];
  maxSafeAmountPaise: number;
  safeToStartPhase6P: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentReviews: SaasRazorpaySandboxStatusReviewDto[];
}

export interface SaasRazorpaySandboxStatusReviewsResponse {
  phase: "6O";
  limit: number;
  counts: SaasRazorpaySandboxStatusReviewCounts;
  items: SaasRazorpaySandboxStatusReviewDto[];
  businessMutationWasMade: false;
  customerNotificationSent: false;
  providerCallAttempted: false;
}

export interface SaasRazorpaySandboxStatusReviewActionResult {
  phase: "6O";
  ok?: boolean;
  created?: boolean;
  reused?: boolean;
  review: SaasRazorpaySandboxStatusReviewDto | null;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface SaasRazorpayBusinessMutationSandboxPlan {
  phase: "6N";
  policyVersion: string;
  status: "planning_only";
  latestCompletedPhase: "6M";
  nextPhase: "6O";
  businessMutationEnabled: false;
  customerNotificationEnabled: false;
  rawPayloadStorageEnabled: false;
  safeToStartPhase6O: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  summary: string;
  eventMappings: SaasRazorpayBusinessMutationEventMapping[];
  syntheticEligibilityPolicy: Record<string, unknown>;
  manualReviewChecklist: SaasRazorpayBusinessMutationManualReviewItem[];
  rollbackPlan: SaasRazorpayBusinessMutationRollbackPlan;
  safetyInvariants: Record<string, boolean>;
  forbiddenActions: string[];
  requiredEnvDefaults: Record<string, boolean>;
  auditPlan: Array<{
    kind: string;
    tone: string;
    emittedBy: string;
    payloadKeys: string[];
    neverIncludes: string[];
  }>;
}

// ---------- Phase 7H - Courier Execution Evidence Lock ----------

export type SaasRazorpayCourierExecutionEvidenceLockStatus =
  | "draft"
  | "pending_manual_review"
  | "locked"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasRazorpayCourierExecutionEvidenceLockDto {
  id: number;
  status: SaasRazorpayCourierExecutionEvidenceLockStatus;
  sourcePhase7GAttemptId: number | null;
  sourcePhase7FGateId: number | null;
  sourcePhase7EGateId: number | null;
  sourcePhase7DAttemptId: number | null;
  sourcePhase7BGateId: number | null;
  sourcePhase6TLockId: number | null;
  providerObjectIdSnapshot: string;
  providerStatusSnapshot: string;
  recordedSignoffWindowValidSnapshot: boolean | null;
  executedAtSnapshot: string | null;
  rolledBackAtSnapshot: string | null;
  rollbackStatusSnapshot: string;
  shipmentCreatedSnapshot: boolean;
  businessMutationWasMadeSnapshot: boolean;
  customerNotificationSentSnapshot: boolean;
  evidenceJson: Record<string, unknown>;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  createdAt: string | null;
  updatedAt: string | null;
  lockedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasRazorpayCourierExecutionEvidenceLockCounts {
  draft: number;
  pending_manual_review: number;
  locked: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasRazorpayCourierExecutionEvidenceLockReadiness {
  phase: "7H";
  status: "courier_evidence_lock_only";
  latestCompletedPhase: "7G";
  nextPhase: "phase_7g_live_or_phase_7h_complete";
  killSwitch: { enabled: boolean; model: string; id?: number };
  eligiblePhase7GAttemptCount: number;
  phase7HLockCounts: SaasRazorpayCourierExecutionEvidenceLockCounts;
  items: SaasRazorpayCourierExecutionEvidenceLockDto[];
  phase7HCallsDelhivery: false;
  phase7HCreatesShipmentRow: false;
  phase7HCreatesAwb: false;
  phase7HSendsWhatsApp: false;
  phase7HQueuesWhatsApp: false;
  phase7HCallsMetaCloud: false;
  phase7HCallsRazorpay: false;
  phase7HSendsCustomerNotification: false;
  phase7HMutatesBusinessRow: false;
  phase7HLiveCustomerCourierApproved: false;
  executionPath: "lock_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasRazorpayCourierExecutionEvidenceLocksResponse {
  phase: "7H";
  limit: number;
  counts: SaasRazorpayCourierExecutionEvidenceLockCounts;
  items: SaasRazorpayCourierExecutionEvidenceLockDto[];
  executionPath: "lock_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase7HCallsDelhivery: false;
  phase7HCreatesShipmentRow: false;
  phase7HCreatesAwb: false;
  phase7HSendsWhatsApp: false;
  phase7HQueuesWhatsApp: false;
  phase7HCallsMetaCloud: false;
  phase7HCallsRazorpay: false;
  phase7HSendsCustomerNotification: false;
  phase7HMutatesBusinessRow: false;
  phase7HLiveCustomerCourierApproved: false;
}

// ---------- Phase 7E-Live-A - Internal Allowed-list WhatsApp One-shot Send ----------

export type SaasPhase7ELiveInternalSendStatus =
  | "draft"
  | "pending_director_signoff"
  | "approved_for_internal_one_shot_send"
  | "executed"
  | "failed"
  | "rollback_recorded"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasPhase7ELiveInternalSendAttemptDto {
  id: number;
  status: SaasPhase7ELiveInternalSendStatus;
  sourcePhase7EGateId: number | null;
  sourcePhase7DAttemptId: number | null;
  sourcePhase7BGateId: number | null;
  sourcePhase6TLockId: number | null;
  templateName: string;
  templateLanguage: string;
  allowedRecipientLast4: string;
  recipientScope: "internal_staff_allow_list";
  providerMessageId: string;
  providerStatus: string;
  safeRequestSummary: Record<string, unknown>;
  safeResponseSummary: Record<string, unknown>;
  recordedSignoffWindowValid: boolean | null;
  recordedSignoffWindowStartUtc: string | null;
  recordedSignoffWindowEndUtc: string | null;
  providerCallAttempted: boolean;
  metaCloudCallAttempted: boolean;
  whatsAppMessageCreated: boolean;
  whatsAppMessageQueued: boolean;
  customerNotificationSent: false;
  businessMutationWasMade: false;
  realCustomerAllowed: false;
  realCustomerPhoneUsed: false;
  claimVaultGrounded: boolean;
  idempotencyKey: string;
  idempotencyLockAcquired: boolean;
  directorSignoffPresent: boolean;
  operatorName: string;
  confirmInternalWhatsAppSend: boolean;
  rollbackReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  executedAt: string | null;
  failedAt: string | null;
  rolledBackAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase7ELiveInternalSendCounts {
  draft: number;
  pending_director_signoff: number;
  approved_for_internal_one_shot_send: number;
  executed: number;
  failed: number;
  rollback_recorded: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase7ELiveInternalSendReadiness {
  phase: "7E-Live-A";
  status: "internal_allowed_list_whatsapp_one_shot_send_only";
  latestCompletedPhase: "7E";
  nextPhase: "phase_7e_live_a_executed_or_phase_7e_live_b_not_approved";
  phase7ELiveInternalWhatsAppSendEnabled: boolean;
  whatsAppLiveMetaLimitedTestMode: boolean;
  allowedTestNumbersCount: number;
  envFlagSnapshot: Record<string, boolean | string>;
  killSwitch: { enabled: boolean; model: string; id?: number };
  attemptCounts: SaasPhase7ELiveInternalSendCounts;
  items: SaasPhase7ELiveInternalSendAttemptDto[];
  phase7ELiveSendsToRealCustomer: false;
  phase7ELiveMutatesBusinessRow: false;
  phase7ELiveCustomerNotification: false;
  phase7ELiveSupportsFreeformMedicalText: false;
  phase7ELiveRecipientScope: "internal_staff_allow_list";
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  safeToRunPhase7ELiveSend: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  recentAttempts: SaasPhase7ELiveInternalSendAttemptDto[];
}

export interface SaasPhase7ELiveInternalSendAttemptsResponse {
  phase: "7E-Live-A";
  limit: number;
  counts: SaasPhase7ELiveInternalSendCounts;
  items: SaasPhase7ELiveInternalSendAttemptDto[];
  executionPath: "cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  recipientScope: "internal_staff_allow_list";
  phase7ELiveSendsToRealCustomer: false;
  phase7ELiveMutatesBusinessRow: false;
  phase7ELiveCustomerNotification: false;
  phase7ELiveSupportsFreeformMedicalText: false;
}

// ---------- Phase 7I - Final Phase 7 Payment + WhatsApp + Courier Audit Lock ----------

export type SaasPhase7IFinalAuditLockStatus =
  | "draft"
  | "pending_manual_review"
  | "locked"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasPhase7IFinalAuditLockDto {
  id: number;
  status: SaasPhase7IFinalAuditLockStatus;
  sourcePhase7DAttemptId: number | null;
  sourcePhase7ELiveSendAttemptId: number | null;
  sourcePhase7GAttemptId: number | null;
  sourcePhase7HEvidenceLockId: number | null;
  sourcePhase6TLockId: number | null;
  // Phase 7D snapshot
  phase7DAttemptStatusSnapshot: string;
  phase7DProviderObjectIdSnapshot: string;
  phase7DBusinessMutationWasMadeSnapshot: boolean;
  phase7DCustomerNotificationSentSnapshot: boolean;
  // Phase 7E-Live-A snapshot
  phase7ELiveAttemptStatusSnapshot: string;
  phase7ELiveProviderMessageIdSnapshot: string;
  phase7ELiveProviderStatusSnapshot: string;
  phase7ELiveTemplateNameSnapshot: string;
  phase7ELiveTemplateLanguageSnapshot: string;
  phase7ELiveAllowedRecipientLast4Snapshot: string;
  phase7ELiveRecipientScopeSnapshot: string;
  phase7ELiveWhatsAppMessageCreatedSnapshot: boolean;
  phase7ELiveWhatsAppMessageQueuedSnapshot: boolean;
  phase7ELiveCustomerNotificationSentSnapshot: boolean;
  phase7ELiveBusinessMutationWasMadeSnapshot: boolean;
  phase7ELiveRealCustomerPhoneUsedSnapshot: boolean;
  phase7ELiveClaimVaultGroundedSnapshot: boolean;
  phase7ELiveRecordedSignoffWindowValidSnapshot: boolean | null;
  // Phase 7G snapshot
  phase7GAttemptStatusSnapshot: string;
  phase7GProviderObjectIdSnapshot: string;
  phase7GProviderStatusSnapshot: string;
  phase7GRollbackStatusSnapshot: string;
  phase7GAwbCreatedSnapshot: boolean;
  phase7GShipmentCreatedSnapshot: boolean;
  phase7GBusinessMutationWasMadeSnapshot: boolean;
  phase7GCustomerNotificationSentSnapshot: boolean;
  phase7GRecordedSignoffWindowValidSnapshot: boolean | null;
  // Phase 7H snapshot
  phase7HEvidenceLockStatusSnapshot: string;
  phase7HProviderObjectIdSnapshot: string;
  phase7HShipmentCreatedSnapshot: boolean;
  phase7HBusinessMutationWasMadeSnapshot: boolean;
  phase7HCustomerNotificationSentSnapshot: boolean;
  evidenceJson: Record<string, unknown>;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  createdAt: string | null;
  updatedAt: string | null;
  lockedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase7IFinalAuditLockCounts {
  draft: number;
  pending_manual_review: number;
  locked: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase7IFinalAuditLockReadiness {
  phase: "7I";
  status: "final_phase7_audit_lock_only";
  latestCompletedPhase: "7H";
  nextPhase: "phase7i_locked_or_phase7_live_not_approved";
  killSwitch: { enabled: boolean; model: string; id?: number };
  eligiblePhase7HEvidenceLockCount: number;
  eligiblePhase7ELiveAttemptCount: number;
  eligiblePhase7GAttemptCount: number;
  phase7ILockCounts: SaasPhase7IFinalAuditLockCounts;
  items: SaasPhase7IFinalAuditLockDto[];
  phase7ICallsRazorpay: false;
  phase7ICallsMetaCloud: false;
  phase7ICallsDelhivery: false;
  phase7ICallsVapi: false;
  phase7ISendsWhatsApp: false;
  phase7IQueuesWhatsApp: false;
  phase7ICreatesShipmentRow: false;
  phase7ICreatesAwb: false;
  phase7ICreatesPaymentLink: false;
  phase7ICapturesPayment: false;
  phase7IRefundsPayment: false;
  phase7ISendsCustomerNotification: false;
  phase7IMutatesBusinessRow: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
  executionPath: "lock_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasPhase7IFinalAuditLocksResponse {
  phase: "7I";
  limit: number;
  counts: SaasPhase7IFinalAuditLockCounts;
  items: SaasPhase7IFinalAuditLockDto[];
  executionPath: "lock_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase7ICallsRazorpay: false;
  phase7ICallsMetaCloud: false;
  phase7ICallsDelhivery: false;
  phase7ICallsVapi: false;
  phase7ISendsWhatsApp: false;
  phase7IQueuesWhatsApp: false;
  phase7ICreatesShipmentRow: false;
  phase7ICreatesAwb: false;
  phase7ICreatesPaymentLink: false;
  phase7ICapturesPayment: false;
  phase7IRefundsPayment: false;
  phase7ISendsCustomerNotification: false;
  phase7IMutatesBusinessRow: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
}

// ---------- Phase 8A - Payment -> Order Mutation Sandbox Gate ----------

export type SaasPhase8APaymentOrderMutationSandboxGateStatus =
  | "draft"
  | "pending_manual_review"
  | "dry_run_passed"
  | "approved_for_future_phase8b_review"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasPhase8APaymentOrderMutationSandboxGateDto {
  id: number;
  status: SaasPhase8APaymentOrderMutationSandboxGateStatus;
  sourcePhase7ILockId: number | null;
  sourcePhase7DAttemptId: number | null;
  sandboxOnly: true;
  realBusinessMutationAllowed: false;
  realOrderMutationAllowed: false;
  realPaymentMutationAllowed: false;
  customerNotificationAllowed: false;
  whatsAppAllowed: false;
  courierAllowed: false;
  syntheticOrderRequired: true;
  manualReviewRequired: true;
  claimVaultNotRequiredForPaymentStatus: true;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  evidenceJson: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase8APaymentOrderMutationDryRunDto {
  id: number;
  gateId: number;
  sourcePhase7ILockId: number | null;
  sourcePhase7DAttemptId: number | null;
  proposedSourcePaymentReference: string;
  proposedTargetOrderReference: string;
  proposedTargetOrderIsSynthetic: boolean;
  proposedOldOrderStatus: string;
  proposedNewOrderStatus: string;
  proposedOldPaymentStatus: string;
  proposedNewPaymentStatus: string;
  wouldMutateOrder: false;
  wouldMutatePayment: false;
  wouldSendCustomerNotification: false;
  wouldSendWhatsApp: false;
  wouldCallCourier: false;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  passed: boolean;
  blockers: string[];
  warnings: string[];
  rollbackReasonPresent: boolean;
  rolledBackAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface SaasPhase8APaymentOrderMutationSandboxGateCounts {
  draft: number;
  pending_manual_review: number;
  dry_run_passed: number;
  approved_for_future_phase8b_review: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase8APaymentOrderMutationSandboxReadiness {
  phase: "8A";
  status: "payment_order_mutation_sandbox_only";
  latestCompletedPhase: "7I";
  nextPhase: string;
  killSwitch: { enabled: boolean; model: string; id?: number };
  phase8APaymentOrderMutationSandboxEnabled: boolean;
  eligiblePhase7ILockCount: number;
  phase8AGateCounts: SaasPhase8APaymentOrderMutationSandboxGateCounts;
  items: SaasPhase8APaymentOrderMutationSandboxGateDto[];
  phase8ACallsRazorpay: false;
  phase8ACallsMetaCloud: false;
  phase8ACallsDelhivery: false;
  phase8ACallsVapi: false;
  phase8ASendsWhatsApp: false;
  phase8AQueuesWhatsApp: false;
  phase8ACreatesShipmentRow: false;
  phase8ACreatesAwb: false;
  phase8ACreatesPaymentLink: false;
  phase8ACapturesPayment: false;
  phase8ARefundsPayment: false;
  phase8ASendsCustomerNotification: false;
  phase8AMutatesBusinessRow: false;
  phase8AMutatesRealOrder: false;
  phase8AMutatesRealPayment: false;
  phase8ARealCustomerAutomationApproved: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
  executionPath: "sandbox_dry_run_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasPhase8APaymentOrderMutationSandboxGatesResponse {
  phase: "8A";
  limit: number;
  counts: SaasPhase8APaymentOrderMutationSandboxGateCounts;
  items: SaasPhase8APaymentOrderMutationSandboxGateDto[];
  executionPath: "sandbox_dry_run_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase8ACallsRazorpay: false;
  phase8ACallsMetaCloud: false;
  phase8ACallsDelhivery: false;
  phase8ACallsVapi: false;
  phase8ASendsWhatsApp: false;
  phase8AQueuesWhatsApp: false;
  phase8ACreatesShipmentRow: false;
  phase8ACreatesAwb: false;
  phase8ACreatesPaymentLink: false;
  phase8ACapturesPayment: false;
  phase8ARefundsPayment: false;
  phase8ASendsCustomerNotification: false;
  phase8AMutatesBusinessRow: false;
  phase8AMutatesRealOrder: false;
  phase8AMutatesRealPayment: false;
  phase8ARealCustomerAutomationApproved: false;
}

// ---------- Phase 8B - Payment -> Order Mutation Review Gate ----------

export type SaasPhase8BPaymentOrderMutationReviewGateStatus =
  | "draft"
  | "pending_manual_review"
  | "dry_run_passed"
  | "approved_for_future_phase8c_controlled_mutation_review"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasPhase8BPaymentOrderMutationReviewGateDto {
  id: number;
  status: SaasPhase8BPaymentOrderMutationReviewGateStatus;
  sourcePhase8AGateId: number | null;
  sourcePhase7ILockId: number | null;
  sourcePhase7DAttemptId: number | null;
  reviewOnly: true;
  realMutationAllowed: false;
  realOrderMutationAllowed: false;
  realPaymentMutationAllowed: false;
  customerNotificationAllowed: false;
  whatsAppAllowed: false;
  courierAllowed: false;
  phase8CRequired: true;
  manualReviewRequired: true;
  paymentReferenceSnapshot: string;
  orderReferenceStrategySnapshot: string;
  syntheticOrderReferenceSnapshot: string;
  proposedRealOrderMatchingStrategy: string;
  proposedPaymentToOrderMappingJson: Record<string, unknown>;
  dryRunPassed: boolean;
  rollbackDryRunPassed: boolean;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  evidenceJson: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase8BPaymentOrderMutationReviewDryRunDto {
  id: number;
  gateId: number;
  sourcePhase8AGateId: number | null;
  sourcePhase7ILockId: number | null;
  sourcePhase7DAttemptId: number | null;
  paymentReference: string;
  paymentStatusSnapshot: string;
  targetOrderReference: string;
  targetOrderMatchType:
    | "synthetic_reference_only"
    | "future_real_order_lookup_not_executed";
  proposedOldOrderStatus: string;
  proposedNewOrderStatus: string;
  proposedOldPaymentStatus: string;
  proposedNewPaymentStatus: string;
  wouldMutateOrder: false;
  wouldMutatePayment: false;
  wouldNotifyCustomer: false;
  wouldSendWhatsApp: false;
  wouldCallCourier: false;
  wouldCreateShipment: false;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  passed: boolean;
  blockers: string[];
  warnings: string[];
  rollbackRecorded: boolean;
  rollbackReasonPresent: boolean;
  rolledBackAt: string | null;
  createdAt: string | null;
}

export interface SaasPhase8BPaymentOrderMutationReviewGateCounts {
  draft: number;
  pending_manual_review: number;
  dry_run_passed: number;
  approved_for_future_phase8c_controlled_mutation_review: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase8BPaymentOrderMutationReviewReadiness {
  phase: "8B";
  status: "payment_order_mutation_review_gate_only";
  latestCompletedPhase: "8A";
  nextPhase: string;
  killSwitch: { enabled: boolean; model: string; id?: number };
  phase8BPaymentOrderMutationReviewGateEnabled: boolean;
  eligiblePhase8AGateCount: number;
  phase8BGateCounts: SaasPhase8BPaymentOrderMutationReviewGateCounts;
  items: SaasPhase8BPaymentOrderMutationReviewGateDto[];
  phase8BCallsRazorpay: false;
  phase8BCallsMetaCloud: false;
  phase8BCallsDelhivery: false;
  phase8BCallsVapi: false;
  phase8BSendsWhatsApp: false;
  phase8BQueuesWhatsApp: false;
  phase8BCreatesShipmentRow: false;
  phase8BCreatesAwb: false;
  phase8BCreatesPaymentLink: false;
  phase8BCapturesPayment: false;
  phase8BRefundsPayment: false;
  phase8BSendsCustomerNotification: false;
  phase8BMutatesBusinessRow: false;
  phase8BMutatesRealOrder: false;
  phase8BMutatesRealPayment: false;
  phase8BApprovesPhase8C: false;
  phase8BApprovesRealCustomerAutomation: false;
  phase8CApproved: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
  executionPath: "review_dry_run_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasPhase8BPaymentOrderMutationReviewGatesResponse {
  phase: "8B";
  limit: number;
  counts: SaasPhase8BPaymentOrderMutationReviewGateCounts;
  items: SaasPhase8BPaymentOrderMutationReviewGateDto[];
  executionPath: "review_dry_run_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase8BCallsRazorpay: false;
  phase8BCallsMetaCloud: false;
  phase8BCallsDelhivery: false;
  phase8BCallsVapi: false;
  phase8BSendsWhatsApp: false;
  phase8BQueuesWhatsApp: false;
  phase8BCreatesShipmentRow: false;
  phase8BCreatesAwb: false;
  phase8BCreatesPaymentLink: false;
  phase8BCapturesPayment: false;
  phase8BRefundsPayment: false;
  phase8BSendsCustomerNotification: false;
  phase8BMutatesBusinessRow: false;
  phase8BMutatesRealOrder: false;
  phase8BMutatesRealPayment: false;
  phase8BApprovesPhase8C: false;
  phase8BApprovesRealCustomerAutomation: false;
}

// ---------- Phase 8C - Controlled Real Payment -> Order Mutation ----------

export type SaasPhase8CPaymentOrderControlledMutationGateStatus =
  | "draft"
  | "pending_manual_review"
  | "dry_run_passed"
  | "approved_for_one_shot_controlled_mutation"
  | "executed"
  | "rolled_back"
  | "rejected"
  | "archived"
  | "blocked";

export type SaasPhase8CPaymentOrderControlledMutationAttemptStatus =
  | "draft"
  | "pending_director_signoff"
  | "approved_for_one_shot_mutation"
  | "executed"
  | "rolled_back"
  | "failed"
  | "blocked"
  | "rejected";

export type SaasPhase8CPaymentOrderControlledMutationRollbackStatus =
  | "draft"
  | "rollback_recorded"
  | "rollback_failed"
  | "blocked";

export interface SaasPhase8CPaymentOrderControlledMutationGateDto {
  id: number;
  status: SaasPhase8CPaymentOrderControlledMutationGateStatus;
  sourcePhase8BGateId: number | null;
  sourcePhase8AGateId: number | null;
  sourcePhase7ILockId: number | null;
  sourcePhase7DAttemptId: number | null;
  controlledMutationOnly: true;
  realCustomerAllowed: false;
  customerNotificationAllowed: false;
  whatsAppAllowed: false;
  courierAllowed: false;
  providerCallAllowed: false;
  shipmentCreationAllowed: false;
  paymentCaptureAllowed: false;
  refundAllowed: false;
  rollbackRequired: true;
  directorSignoffRequired: true;
  structuredUtcWindowRequired: true;
  sourcePaymentReferenceSnapshot: string;
  targetOrderReferenceSnapshot: string;
  targetPaymentReferenceSnapshot: string;
  proposedOldOrderStatus: string;
  proposedNewOrderStatus: string;
  proposedOldPaymentStatus: string;
  proposedNewPaymentStatus: string;
  dryRunPassed: boolean;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  evidenceJson: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase8CPaymentOrderControlledMutationAttemptDto {
  id: number;
  gateId: number;
  sourcePhase8BGateId: number | null;
  targetOrderId: string;
  targetPaymentId: string;
  targetOrderReference: string;
  targetPaymentReference: string;
  paymentReferenceSnapshot: string;
  status: SaasPhase8CPaymentOrderControlledMutationAttemptStatus;
  oldOrderStatus: string;
  newOrderStatus: string;
  oldPaymentStatus: string;
  newPaymentStatus: string;
  orderMutationWasMade: boolean;
  paymentMutationWasMade: boolean;
  businessMutationWasMade: boolean;
  customerNotificationSent: false;
  whatsAppSent: false;
  courierCalled: false;
  providerCallAttempted: false;
  shipmentCreated: false;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  blockers: string[];
  warnings: string[];
  directorSignoffTextHashPresent: boolean;
  recordedSignoffWindowStartUtc: string | null;
  recordedSignoffWindowEndUtc: string | null;
  recordedSignoffWindowValid: boolean;
  operatorNamePresent: boolean;
  executedAt: string | null;
  failedAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface SaasPhase8CPaymentOrderControlledMutationRollbackDto {
  id: number;
  attemptId: number;
  status: SaasPhase8CPaymentOrderControlledMutationRollbackStatus;
  restoredOrderStatus: string;
  restoredPaymentStatus: string;
  rollbackWasMade: boolean;
  customerNotificationSent: false;
  whatsAppSent: false;
  courierCalled: false;
  providerCallAttempted: false;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  reasonPresent: boolean;
  rolledBackAt: string | null;
  createdAt: string | null;
}

export interface SaasPhase8CPaymentOrderControlledMutationGateCounts {
  draft: number;
  pending_manual_review: number;
  dry_run_passed: number;
  approved_for_one_shot_controlled_mutation: number;
  executed: number;
  rolled_back: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase8CPaymentOrderControlledMutationReadiness {
  phase: "8C";
  status: "payment_order_controlled_mutation_only";
  latestCompletedPhase: "8B";
  nextPhase: string;
  phase8CGateEnabled: boolean;
  phase8CDirectorApproved: boolean;
  phase8CAllowInternalMutation: boolean;
  killSwitch: { enabled: boolean; model: string; id?: number };
  eligiblePhase8BGateCount: number;
  phase8CGateCounts: SaasPhase8CPaymentOrderControlledMutationGateCounts;
  items: SaasPhase8CPaymentOrderControlledMutationGateDto[];
  phase8CCallsRazorpay: false;
  phase8CCallsMetaCloud: false;
  phase8CCallsDelhivery: false;
  phase8CCallsVapi: false;
  phase8CSendsWhatsApp: false;
  phase8CQueuesWhatsApp: false;
  phase8CCreatesShipmentRow: false;
  phase8CCreatesAwb: false;
  phase8CCreatesPaymentLink: false;
  phase8CCapturesPayment: false;
  phase8CRefundsPayment: false;
  phase8CSendsCustomerNotification: false;
  phase8CMutatesCustomer: false;
  phase8CMutatesLead: false;
  phase8CMutatesShipment: false;
  phase8CMutatesDiscountOfferLog: false;
  phase8CApprovesRealCustomerAutomation: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
  executionPath: "cli_only_one_shot_controlled_mutation";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasPhase8CPaymentOrderControlledMutationGatesResponse {
  phase: "8C";
  limit: number;
  counts: SaasPhase8CPaymentOrderControlledMutationGateCounts;
  items: SaasPhase8CPaymentOrderControlledMutationGateDto[];
  executionPath: "cli_only_one_shot_controlled_mutation";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase8CCallsRazorpay: false;
  phase8CCallsMetaCloud: false;
  phase8CCallsDelhivery: false;
  phase8CCallsVapi: false;
  phase8CSendsWhatsApp: false;
  phase8CQueuesWhatsApp: false;
  phase8CCreatesShipmentRow: false;
  phase8CCreatesAwb: false;
  phase8CCreatesPaymentLink: false;
  phase8CCapturesPayment: false;
  phase8CRefundsPayment: false;
  phase8CSendsCustomerNotification: false;
  phase8CMutatesCustomer: false;
  phase8CMutatesLead: false;
  phase8CMutatesShipment: false;
  phase8CMutatesDiscountOfferLog: false;
  phase8CApprovesRealCustomerAutomation: false;
}

// ---------- Phase 8D - Controlled Mutation Evidence Lock ----------

export type SaasPhase8DControlledMutationEvidenceLockStatus =
  | "draft"
  | "pending_manual_review"
  | "locked"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasPhase8DControlledMutationEvidenceLockDto {
  id: number;
  status: SaasPhase8DControlledMutationEvidenceLockStatus;
  sourcePhase8CGateId: number | null;
  sourcePhase8CAttemptId: number | null;
  sourcePhase8BGateId: number | null;
  sourcePhase8AGateId: number | null;
  sourcePhase7ILockId: number | null;
  sourcePhase7DAttemptId: number | null;
  phase8CGateStatusSnapshot: string;
  phase8CAttemptStatusSnapshot: string;
  phase8CAttemptExecutedAtSnapshot: string | null;
  recordedSignoffWindowValidSnapshot: boolean;
  targetOrderIdSnapshot: string;
  targetPaymentIdSnapshot: string;
  targetOrderReferenceSnapshot: string;
  targetPaymentReferenceSnapshot: string;
  oldOrderStatusSnapshot: string;
  executedOrderStatusSnapshot: string;
  finalOrderStatusSnapshot: string;
  oldPaymentStatusSnapshot: string;
  executedPaymentStatusSnapshot: string;
  finalPaymentStatusSnapshot: string;
  orderMutationWasMadeSnapshot: boolean;
  paymentMutationWasMadeSnapshot: boolean;
  businessMutationWasMadeSnapshot: boolean;
  rollbackCompletedSnapshot: boolean;
  finalDbRestoredSnapshot: boolean;
  phase8DCallsRazorpaySnapshot: false;
  phase8DCallsMetaCloudSnapshot: false;
  phase8DCallsDelhiverySnapshot: false;
  phase8DSendsWhatsAppSnapshot: false;
  phase8DSendsCustomerNotificationSnapshot: false;
  phase8DCreatesShipmentSnapshot: false;
  phase8DCapturesPaymentSnapshot: false;
  phase8DRefundsPaymentSnapshot: false;
  beforeCountsSnapshot: Record<string, number>;
  afterExecuteCountsSnapshot: Record<string, number>;
  afterRollbackCountsSnapshot: Record<string, number>;
  countDeltasSnapshot: Record<string, number>;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  evidenceJson: Record<string, unknown>;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  createdAt: string | null;
  updatedAt: string | null;
  lockedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase8DControlledMutationEvidenceLockCounts {
  draft: number;
  pending_manual_review: number;
  locked: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase8DControlledMutationEvidenceLockReadiness {
  phase: "8D";
  status: "controlled_mutation_evidence_lock_only";
  latestCompletedPhase: "8C";
  nextPhase: string;
  killSwitch: { enabled: boolean; model: string; id?: number };
  eligiblePhase8CGateCount: number;
  phase8DLockCounts: SaasPhase8DControlledMutationEvidenceLockCounts;
  items: SaasPhase8DControlledMutationEvidenceLockDto[];
  phase8DExecutesPhase8CAgain: false;
  phase8DRollsBackPhase8CAgain: false;
  phase8DCallsRazorpay: false;
  phase8DCallsMetaCloud: false;
  phase8DCallsDelhivery: false;
  phase8DCallsVapi: false;
  phase8DSendsWhatsApp: false;
  phase8DQueuesWhatsApp: false;
  phase8DCreatesShipmentRow: false;
  phase8DCreatesAwb: false;
  phase8DCreatesPaymentLink: false;
  phase8DCapturesPayment: false;
  phase8DRefundsPayment: false;
  phase8DSendsCustomerNotification: false;
  phase8DMutatesOrder: false;
  phase8DMutatesPayment: false;
  phase8DMutatesCustomer: false;
  phase8DMutatesLead: false;
  phase8DMutatesShipment: false;
  phase8DMutatesDiscountOfferLog: false;
  phase8DMutatesWhatsAppMessage: false;
  phase8DApprovesRealCustomerAutomation: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
  executionPath: "lock_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasPhase8DControlledMutationEvidenceLocksResponse {
  phase: "8D";
  limit: number;
  counts: SaasPhase8DControlledMutationEvidenceLockCounts;
  items: SaasPhase8DControlledMutationEvidenceLockDto[];
  executionPath: "lock_only_cli_only";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase8DExecutesPhase8CAgain: false;
  phase8DRollsBackPhase8CAgain: false;
  phase8DCallsRazorpay: false;
  phase8DCallsMetaCloud: false;
  phase8DCallsDelhivery: false;
  phase8DSendsWhatsApp: false;
  phase8DSendsCustomerNotification: false;
  phase8DCreatesShipmentRow: false;
  phase8DCreatesAwb: false;
  phase8DCapturesPayment: false;
  phase8DRefundsPayment: false;
  phase8DMutatesOrder: false;
  phase8DMutatesPayment: false;
  phase8DMutatesCustomer: false;
  phase8DMutatesLead: false;
}

// ---------- Phase 8E - Real Customer Payment -> Order Pilot ----------

export type SaasPhase8ERealCustomerPaymentOrderPilotGateStatus =
  | "draft"
  | "pending_manual_review"
  | "dry_run_passed"
  | "approved_for_future_phase8f_real_customer_controlled_mutation"
  | "rejected"
  | "archived"
  | "blocked";

export interface SaasPhase8ERealCustomerPaymentOrderPilotGateDto {
  id: number;
  status: SaasPhase8ERealCustomerPaymentOrderPilotGateStatus;
  sourcePhase8DLockId: number | null;
  sourcePhase8CGateId: number | null;
  sourcePhase8BGateId: number | null;
  sourcePhase8AGateId: number | null;
  sourcePhase7ILockId: number | null;
  realCustomerPilotOnly: true;
  realMutationAllowed: false;
  realOrderMutationAllowed: false;
  realPaymentMutationAllowed: false;
  customerNotificationAllowed: false;
  whatsAppAllowed: false;
  courierAllowed: false;
  providerCallAllowed: false;
  phase8FRequired: true;
  manualReviewRequired: true;
  directorSignoffRequired: true;
  rollbackRequired: true;
  candidateOrderIdSnapshot: string;
  candidatePaymentIdSnapshot: string;
  candidateOrderCurrentStatusSnapshot: string;
  candidatePaymentCurrentStatusSnapshot: string;
  proposedOrderNewStatusSnapshot: string;
  proposedPaymentNewStatusSnapshot: string;
  dryRunPassed: boolean;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  evidenceJson: Record<string, unknown>;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  reviewedByUsername: string;
  reviewedAt: string | null;
  reviewReasonPresent: boolean;
  rejectReasonPresent: boolean;
  archiveReasonPresent: boolean;
  createdAt: string | null;
  updatedAt: string | null;
  approvedAt: string | null;
  rejectedAt: string | null;
  archivedAt: string | null;
}

export interface SaasPhase8ERealCustomerPaymentOrderPilotCandidateDto {
  id: number;
  gateId: number;
  orderId: string;
  paymentId: string;
  orderCustomerNameMasked: string;
  orderPhoneLast4: string;
  paymentGateway: string;
  paymentReferencePrefix: string;
  orderCurrentPaymentStatus: string;
  paymentCurrentStatus: string;
  orderAmount: number;
  paymentAmount: number;
  isRealCustomerCandidate: true;
  candidateValidationPassed: boolean;
  candidateValidationBlockers: string[];
  candidateValidationWarnings: string[];
  consentRequired: true;
  customerNotificationAllowed: false;
  whatsAppAllowed: false;
  courierAllowed: false;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface SaasPhase8ERealCustomerPaymentOrderPilotDryRunDto {
  id: number;
  gateId: number;
  candidateId: number;
  targetOrderId: string;
  targetPaymentId: string;
  oldOrderPaymentStatus: string;
  newOrderPaymentStatusCandidate: string;
  oldPaymentStatus: string;
  newPaymentStatusCandidate: string;
  wouldMutateOrder: false;
  wouldMutatePayment: false;
  wouldSendCustomerNotification: false;
  wouldSendWhatsApp: false;
  wouldCallCourier: false;
  wouldCreateShipment: false;
  wouldCallProvider: false;
  beforeCounts: Record<string, number>;
  afterCounts: Record<string, number>;
  countDeltas: Record<string, number>;
  passed: boolean;
  blockers: string[];
  warnings: string[];
  createdAt: string | null;
}

export interface SaasPhase8ERealCustomerPaymentOrderPilotGateCounts {
  draft: number;
  pending_manual_review: number;
  dry_run_passed: number;
  approved_for_future_phase8f_real_customer_controlled_mutation: number;
  rejected: number;
  archived: number;
  blocked: number;
}

export interface SaasPhase8ERealCustomerPaymentOrderPilotReadiness {
  phase: "8E";
  status: "real_customer_payment_order_pilot_review_only";
  latestCompletedPhase: "8D";
  nextPhase: string;
  phase8EPaymentOrderPilotEnabled: boolean;
  killSwitch: { enabled: boolean; model: string; id?: number };
  eligiblePhase8DLockCount: number;
  phase8EGateCounts: SaasPhase8ERealCustomerPaymentOrderPilotGateCounts;
  items: SaasPhase8ERealCustomerPaymentOrderPilotGateDto[];
  phase8ECallsRazorpay: false;
  phase8ECallsMetaCloud: false;
  phase8ECallsDelhivery: false;
  phase8ECallsVapi: false;
  phase8ESendsWhatsApp: false;
  phase8EQueuesWhatsApp: false;
  phase8ECreatesShipmentRow: false;
  phase8ECreatesAwb: false;
  phase8ECreatesPaymentLink: false;
  phase8ECapturesPayment: false;
  phase8ERefundsPayment: false;
  phase8ESendsCustomerNotification: false;
  phase8EMutatesOrder: false;
  phase8EMutatesPayment: false;
  phase8EMutatesCustomer: false;
  phase8EMutatesLead: false;
  phase8EMutatesShipment: false;
  phase8EMutatesDiscountOfferLog: false;
  phase8EMutatesWhatsAppMessage: false;
  phase8EApprovesRealCustomerAutomation: false;
  phase8FApproved: false;
  phase7ELiveBApproved: false;
  phase7GLiveApproved: false;
  executionPath: "review_dry_run_only_cli_only_no_execute";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  blockers: string[];
  warnings: string[];
  nextAction: string;
  forbiddenActions: string[];
}

export interface SaasPhase8ERealCustomerPaymentOrderPilotGatesResponse {
  phase: "8E";
  limit: number;
  counts: SaasPhase8ERealCustomerPaymentOrderPilotGateCounts;
  items: SaasPhase8ERealCustomerPaymentOrderPilotGateDto[];
  executionPath: "review_dry_run_only_cli_only_no_execute";
  frontendCanExecute: false;
  apiEndpointCanExecute: false;
  apiEndpointCanApprove: false;
  phase8ECallsRazorpay: false;
  phase8ECallsMetaCloud: false;
  phase8ECallsDelhivery: false;
  phase8ECallsVapi: false;
  phase8ESendsWhatsApp: false;
  phase8EQueuesWhatsApp: false;
  phase8ECreatesShipmentRow: false;
  phase8ECreatesAwb: false;
  phase8ECreatesPaymentLink: false;
  phase8ECapturesPayment: false;
  phase8ERefundsPayment: false;
  phase8ESendsCustomerNotification: false;
  phase8EMutatesOrder: false;
  phase8EMutatesPayment: false;
  phase8EMutatesCustomer: false;
  phase8EMutatesLead: false;
  phase8EApprovesRealCustomerAutomation: false;
}
