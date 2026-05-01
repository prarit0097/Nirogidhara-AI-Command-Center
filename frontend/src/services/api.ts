/**
 * Service layer for the Nirogidhara AI Command Center frontend.
 *
 * Each function maps to a Django REST endpoint served by ``backend/`` (see
 * ``docs/BACKEND_API.md``). At runtime the layer:
 *
 *   1. Calls ``${VITE_API_BASE_URL}${path}`` with any auth token from
 *      ``localStorage`` (no login UI yet — ready for Phase 2).
 *   2. On any network/HTTP failure, falls back to the deterministic mock
 *      fixtures in ``mockData.ts``. This keeps every page rendering even when
 *      the backend is offline (useful for designers and CI without backend).
 *   3. Logs a single warning per missing endpoint so the dev console makes
 *      the fallback visible.
 *
 * Function names and return shapes are stable — pages should NOT change when
 * the backend swaps in for the mocks.
 *
 * Endpoint contract:
 *   GET  /api/dashboard/metrics
 *   GET  /api/dashboard/activity
 *   GET  /api/leads                  GET /api/leads/:id
 *   GET  /api/customers              GET /api/customers/:id
 *   GET  /api/orders                 GET /api/orders/pipeline
 *   GET  /api/calls                  GET /api/calls/active
 *   GET  /api/calls/active/transcript
 *   GET  /api/confirmation/queue
 *   GET  /api/payments
 *   GET  /api/shipments
 *   GET  /api/rto/risk
 *   GET  /api/agents                 GET /api/agents/hierarchy
 *   GET  /api/ai/ceo-briefing
 *   GET  /api/ai/caio-audits
 *   GET  /api/rewards
 *   GET  /api/compliance/claims
 *   GET  /api/learning/recordings
 *   GET  /api/analytics
 *   GET  /api/analytics/{funnel,revenue-trend,state-rto,product-performance}
 *   GET  /api/settings
 */

import * as M from "./mockData";
import type {
  ActiveCall,
  ActivityEvent,
  Agent,
  AgentRun,
  AgentBudget,
  AgentBudgetWritePayload,
  AgentRunCreatePayload,
  AgentRuntimeStatus,
  AiSchedulerStatus,
  CaioAudit,
  PromptVersion,
  PromptVersionCreatePayload,
  SandboxPatchPayload,
  SandboxState,
  Call,
  CallTranscriptLine,
  CallTriggerPayload,
  CallTriggerResponse,
  CeoBriefing,
  Claim,
  ConfirmationOutcome,
  CreateLeadPayload,
  CreateOrderPayload,
  Customer,
  CustomerWritePayload,
  DashboardMetrics,
  KPITrend,
  Lead,
  LearningRecording,
  Order,
  OrderStage,
  Payment,
  PaymentLinkPayload,
  PaymentLinkResponse,
  ApprovalEvaluatePayload,
  ApprovalEvaluationResult,
  ApprovalRequest,
  ExecuteApprovalPayload,
  ExecuteApprovalResponse,
  RescueAttempt,
  RescueAttemptCreatePayload,
  RescueAttemptUpdatePayload,
  RewardPenalty,
  RewardPenaltyEvent,
  RewardPenaltySummary,
  RewardPenaltySweepPayload,
  RewardPenaltySweepResult,
  Shipment,
  ShipmentCreatePayload,
  UpdateLeadPayload,
  SendWhatsAppTemplatePayload,
  SendWhatsAppTemplateResponse,
  WhatsAppConnection,
  WhatsAppConsentPatchPayload,
  WhatsAppConsentSummary,
  WhatsAppConversation,
  WhatsAppCustomerTimeline,
  WhatsAppInboxSummary,
  WhatsAppInternalNote,
  WhatsAppMessage,
  WhatsAppProviderStatus,
  WhatsAppTemplate,
  WhatsAppTemplateSyncPayload,
  WhatsAppTemplateSyncResult,
  CreateInternalNotePayload,
  UpdateWhatsAppConversationPayload,
  SendConversationTemplatePayload,
  WhatsAppAiGlobalStatus,
  WhatsAppAiHandoffPayload,
  WhatsAppAiRunSummary,
  WhatsAppAiRunsResponse,
  WhatsAppConversationAiPayload,
  WhatsAppConversationAiState,
  UpdateWhatsAppAiModePayload,
  WhatsAppHandoffToCall,
  TriggerWhatsAppCallPayload,
  TriggerWhatsAppCallResponse,
  WhatsAppLifecycleEvent,
  ClaimVaultCoverageReport,
  DiscountOffer,
  DiscountOfferListResponse,
  CreateRescueOfferPayload,
  ReorderDay20RunResponse,
  ReorderDay20StatusResponse,
  WhatsAppMonitoringActivity,
  WhatsAppMonitoringAuditResponse,
  WhatsAppMonitoringCohort,
  WhatsAppMonitoringGate,
  WhatsAppMonitoringMutationSafety,
  WhatsAppMonitoringOverview,
  WhatsAppMonitoringUnexpectedOutbound,
} from "@/types/domain";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
const BASE = RAW_BASE.replace(/\/+$/, "");

const warnedPaths = new Set<string>();

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("nirogidhara.jwt") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function safeFetch<T>(path: string, fallback: () => T | Promise<T>): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { Accept: "application/json", ...authHeaders() },
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} for ${path}`);
    }
    return (await res.json()) as T;
  } catch (error) {
    if (!warnedPaths.has(path)) {
      warnedPaths.add(path);
      console.warn(`[api] Falling back to mock data for ${path}: ${(error as Error).message}`);
    }
    return fallback();
  }
}

type HttpMethod = "POST" | "PATCH" | "PUT" | "DELETE";

async function safeMutate<T>(
  path: string,
  method: HttpMethod,
  body: unknown,
  fallback: () => T | Promise<T>,
): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} for ${method} ${path}`);
    }
    if (res.status === 204) {
      return undefined as unknown as T;
    }
    return (await res.json()) as T;
  } catch (error) {
    const key = `${method} ${path}`;
    if (!warnedPaths.has(key)) {
      warnedPaths.add(key);
      console.warn(`[api] Falling back to optimistic mock for ${key}: ${(error as Error).message}`);
    }
    return fallback();
  }
}

const wait = <T,>(data: T, ms = 0): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(data), ms));

// ---------- Service functions ----------

export const api = {
  // Dashboard
  getDashboardMetrics: () =>
    safeFetch<DashboardMetrics>("/dashboard/metrics/", () => M.DASHBOARD_METRICS as DashboardMetrics),
  getLiveActivityFeed: () =>
    safeFetch<ActivityEvent[]>("/dashboard/activity/", () => M.ACTIVITY_FEED as ActivityEvent[]),

  // Analytics
  getFunnel: () => safeFetch<KPITrend[]>("/analytics/funnel/", () => M.FUNNEL as KPITrend[]),
  getRevenueTrend: () => safeFetch<KPITrend[]>("/analytics/revenue-trend/", () => M.REVENUE_TREND as KPITrend[]),
  getStateRto: () => safeFetch<KPITrend[]>("/analytics/state-rto/", () => M.STATE_RTO as KPITrend[]),
  getProductPerformance: () =>
    safeFetch<KPITrend[]>("/analytics/product-performance/", () => M.PRODUCT_PERFORMANCE as KPITrend[]),
  getAnalyticsData: () =>
    safeFetch("/analytics/", () => ({
      funnel: M.FUNNEL as KPITrend[],
      revenueTrend: M.REVENUE_TREND as KPITrend[],
      stateRto: M.STATE_RTO as KPITrend[],
      productPerformance: M.PRODUCT_PERFORMANCE as KPITrend[],
      discountImpact: [
        { discount: "0%", delivered: 62, rto: 18 },
        { discount: "10%", delivered: 71, rto: 14 },
        { discount: "15%", delivered: 78, rto: 12 },
        { discount: "20%", delivered: 81, rto: 14 },
        { discount: "25%", delivered: 76, rto: 22 },
        { discount: "30%", delivered: 64, rto: 31 },
      ],
    })),

  // Leads / Customers
  getLeads: () => safeFetch<Lead[]>("/leads/", () => M.LEADS as Lead[]),
  getLeadById: (id: string) =>
    safeFetch<Lead | undefined>(`/leads/${id}/`, () => (M.LEADS as Lead[]).find((l) => l.id === id)),
  getCustomers: () => safeFetch<Customer[]>("/customers/", () => M.CUSTOMERS as Customer[]),
  getCustomerById: (id: string) =>
    safeFetch<Customer | undefined>(`/customers/${id}/`, () =>
      (M.CUSTOMERS as Customer[]).find((c) => c.id === id),
    ),

  // Orders
  getOrders: () => safeFetch<Order[]>("/orders/", () => M.ORDERS as Order[]),
  getOrderPipeline: () => safeFetch<Order[]>("/orders/pipeline/", () => M.ORDERS as Order[]),

  // Calls
  getCalls: () => safeFetch<Call[]>("/calls/", () => M.CALLS as Call[]),
  getActiveCall: () => safeFetch<ActiveCall>("/calls/active/", () => M.ACTIVE_CALL as ActiveCall),
  getCallTranscripts: () =>
    safeFetch<CallTranscriptLine[]>(
      "/calls/active/transcript/",
      () => M.ACTIVE_CALL.transcript as CallTranscriptLine[],
    ),

  // Confirmation
  getConfirmationQueue: () =>
    safeFetch("/confirmation/queue/", () => wait(M.CONFIRMATION_QUEUE)) as Promise<
      Array<Order & { hoursWaiting: number; addressConfidence: number; checklist: Record<string, boolean> }>
    >,

  // Payments / Shipments / RTO
  getPayments: () => safeFetch<Payment[]>("/payments/", () => M.PAYMENTS as Payment[]),
  getShipments: () => safeFetch<Shipment[]>("/shipments/", () => M.SHIPMENTS as Shipment[]),
  getRtoRiskOrders: () =>
    safeFetch("/rto/risk/", () => M.RTO_RISK_ORDERS) as Promise<
      Array<Order & { riskReasons: string[]; rescueStatus: string }>
    >,

  // Agents
  getAgentStatus: () => safeFetch<Agent[]>("/agents/", () => M.AGENTS as unknown as Agent[]),
  getAgentHierarchy: () =>
    safeFetch("/agents/hierarchy/", () => ({
      root: "Prarit Sidana (Director)",
      ceo: "CEO AI Agent",
      caio: "CAIO Agent",
      departments: (M.AGENTS as unknown as Agent[]).filter((a) => a.id !== "ceo" && a.id !== "caio"),
    })),

  // AI governance
  getCeoBriefing: () => safeFetch<CeoBriefing>("/ai/ceo-briefing/", () => M.CEO_BRIEFING as CeoBriefing),
  getCaioAudits: () => safeFetch<CaioAudit[]>("/ai/caio-audits/", () => M.CAIO_AUDITS as CaioAudit[]),

  // Rewards / Compliance / Learning
  getRewardPenaltyScores: () =>
    safeFetch<RewardPenalty[]>("/rewards/", () => M.REWARD_LEADERBOARD as RewardPenalty[]),
  // Phase 4B — per-order, per-AI-agent scoring events.
  getRewardPenaltyEvents: (params?: { agent?: string; orderId?: string; eventType?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.agent) qs.set("agent", params.agent);
    if (params?.orderId) qs.set("orderId", params.orderId);
    if (params?.eventType) qs.set("eventType", params.eventType);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<RewardPenaltyEvent[]>(
      `/rewards/events/${suffix}`,
      () => M.REWARD_PENALTY_EVENTS as RewardPenaltyEvent[],
    );
  },
  getRewardPenaltySummary: () =>
    safeFetch<RewardPenaltySummary>(
      "/rewards/summary/",
      () => M.REWARD_PENALTY_SUMMARY as RewardPenaltySummary,
    ),
  runRewardPenaltySweep: (payload: RewardPenaltySweepPayload = {}) =>
    safeMutate<RewardPenaltySweepResult>(
      "/rewards/sweep/",
      "POST",
      payload,
      () => optimisticSweepResult(payload),
    ),
  // Phase 4C — Approval Matrix Middleware.
  getApprovals: (params?: { status?: string; action?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.action) qs.set("action", params.action);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<ApprovalRequest[]>(
      `/ai/approvals/${suffix}`,
      () => M.APPROVAL_REQUESTS as ApprovalRequest[],
    );
  },
  getApprovalById: (id: string) =>
    safeFetch<ApprovalRequest | undefined>(
      `/ai/approvals/${id}/`,
      () => (M.APPROVAL_REQUESTS as ApprovalRequest[]).find((a) => a.id === id),
    ),
  approveApprovalRequest: (id: string, note: string = "") =>
    safeMutate<ApprovalRequest>(
      `/ai/approvals/${id}/approve/`,
      "POST",
      { note },
      () => optimisticApprovalDecision(id, "approved", note),
    ),
  rejectApprovalRequest: (id: string, note: string = "") =>
    safeMutate<ApprovalRequest>(
      `/ai/approvals/${id}/reject/`,
      "POST",
      { note },
      () => optimisticApprovalDecision(id, "rejected", note),
    ),
  evaluateApprovalAction: (payload: ApprovalEvaluatePayload) =>
    safeMutate<ApprovalEvaluationResult>(
      "/ai/approvals/evaluate/",
      "POST",
      payload,
      () => optimisticApprovalEvaluation(payload),
    ),
  requestAgentRunApproval: (agentRunId: string, reason: string = "") =>
    safeMutate<ApprovalRequest>(
      `/ai/agent-runs/${agentRunId}/request-approval/`,
      "POST",
      { reason },
      () => optimisticAgentRunApproval(agentRunId, reason),
    ),
  // Phase 4D — Approved Action Execution Layer.
  executeApprovalRequest: (id: string, payload: ExecuteApprovalPayload = {}) =>
    safeMutate<ExecuteApprovalResponse>(
      `/ai/approvals/${id}/execute/`,
      "POST",
      payload,
      () => optimisticExecuteApprovalResponse(id),
    ),
  getClaimVault: () => safeFetch<Claim[]>("/compliance/claims/", () => M.CLAIM_VAULT as Claim[]),
  getHumanCallLearningItems: () =>
    safeFetch<LearningRecording[]>("/learning/recordings/", () => M.LEARNING_RECORDINGS as LearningRecording[]),

  // Settings
  getSettingsMock: () =>
    safeFetch("/settings/", () => ({ approvalMatrix: M.APPROVAL_MATRIX, integrations: M.INTEGRATIONS })),

  // ---------- PHASE 2A — write methods ----------
  // All require auth (JWT in localStorage["nirogidhara.jwt"]) + role >= operations.
  // Each method falls back to a deterministic optimistic shape when offline so
  // pages that wire these up later don't crash during dev / on first load.

  createLead: (payload: CreateLeadPayload) =>
    safeMutate<Lead>("/leads/", "POST", payload, () => optimisticLead(payload)),

  updateLead: (id: string, payload: UpdateLeadPayload) =>
    safeMutate<Lead>(`/leads/${id}/`, "PATCH", payload, () => {
      const base = (M.LEADS as Lead[]).find((l) => l.id === id) ?? (M.LEADS[0] as Lead);
      return { ...base, ...payload, id } as Lead;
    }),

  assignLead: (id: string, assignee: string) =>
    safeMutate<Lead>(`/leads/${id}/assign/`, "POST", { assignee }, () => {
      const base = (M.LEADS as Lead[]).find((l) => l.id === id) ?? (M.LEADS[0] as Lead);
      return { ...base, assignee };
    }),

  createCustomer: (payload: CustomerWritePayload) =>
    safeMutate<Customer>("/customers/", "POST", payload, () => optimisticCustomer(payload)),

  updateCustomer: (id: string, payload: CustomerWritePayload) =>
    safeMutate<Customer>(`/customers/${id}/`, "PATCH", payload, () => {
      const base = (M.CUSTOMERS as Customer[]).find((c) => c.id === id) ?? (M.CUSTOMERS[0] as Customer);
      return { ...base, ...optimisticCustomer(payload), id };
    }),

  createOrder: (payload: CreateOrderPayload) =>
    safeMutate<Order>("/orders/", "POST", payload, () => optimisticOrder(payload)),

  transitionOrder: (id: string, stage: OrderStage, notes = "") =>
    safeMutate<Order>(`/orders/${id}/transition/`, "POST", { stage, notes }, () => {
      const base = (M.ORDERS as Order[]).find((o) => o.id === id) ?? (M.ORDERS[0] as Order);
      return { ...base, stage };
    }),

  moveOrderToConfirmation: (id: string) =>
    safeMutate<Order>(`/orders/${id}/move-to-confirmation/`, "POST", undefined, () => {
      const base = (M.ORDERS as Order[]).find((o) => o.id === id) ?? (M.ORDERS[0] as Order);
      return { ...base, stage: "Confirmation Pending" };
    }),

  confirmOrder: (id: string, outcome: ConfirmationOutcome, notes = "") =>
    safeMutate<Order>(`/orders/${id}/confirm/`, "POST", { outcome, notes }, () => {
      const base = (M.ORDERS as Order[]).find((o) => o.id === id) ?? (M.ORDERS[0] as Order);
      const stage: OrderStage =
        outcome === "confirmed" ? "Confirmed" : outcome === "cancelled" ? "RTO" : base.stage;
      return { ...base, stage };
    }),

  createPaymentLink: (payload: PaymentLinkPayload) =>
    safeMutate<PaymentLinkResponse>("/payments/links/", "POST", payload, () => {
      const payment = optimisticPayment(payload);
      const gateway = (payload.gateway ?? "Razorpay").toLowerCase();
      const url = `https://${gateway === "razorpay" ? "razorpay" : "payu"}.example/pay/mock`;
      return {
        gatewayReferenceId: `plink_mock_${payload.orderId}`,
        paymentUrl: url,
        paymentId: payment.id,
        gateway,
        status: payment.status.toLowerCase(),
        payment: { ...payment, paymentUrl: url } as Payment,
      };
    }),

  createShipment: (payload: ShipmentCreatePayload) =>
    safeMutate<Shipment>("/shipments/", "POST", payload, () => optimisticShipment(payload)),

  createRescueAttempt: (payload: RescueAttemptCreatePayload) =>
    safeMutate<RescueAttempt>("/rto/rescue/", "POST", payload, () => optimisticRescue(payload)),

  updateRescueAttempt: (id: string, payload: RescueAttemptUpdatePayload) =>
    safeMutate<RescueAttempt>(`/rto/rescue/${id}/`, "PATCH", payload, () => ({
      id,
      orderId: "",
      channel: "AI Call",
      outcome: payload.outcome,
      notes: payload.notes ?? "",
      attemptedAt: new Date().toISOString(),
    })),

  // ---------- PHASE 2D — Vapi voice trigger ----------
  // Server holds the API key; the frontend just kicks off the call. Mock
  // mode (default) returns a deterministic provider id without any network.

  triggerCallForLead: (payload: CallTriggerPayload) =>
    safeMutate<CallTriggerResponse>("/calls/trigger/", "POST", payload, () =>
      optimisticCallTrigger(payload),
    ),

  // ---------- PHASE 3A — AgentRun (read-only / dry-run) ----------
  // Admin/director only. Phase 3A always runs in dry-run mode server-side
  // — `dryRun` on the wire is forward-compat for Phase 5 approval matrix.

  listAgentRuns: () =>
    safeFetch<AgentRun[]>("/ai/agent-runs/", () => []),

  getAgentRun: (id: string) =>
    safeFetch<AgentRun | undefined>(`/ai/agent-runs/${id}/`, () => undefined),

  createAgentRun: (payload: AgentRunCreatePayload) =>
    safeMutate<AgentRun>("/ai/agent-runs/", "POST", payload, () =>
      optimisticAgentRun(payload),
    ),

  // ---------- PHASE 3B — per-agent runtime (admin/director only) ----------
  // Each call dispatches the agent's read-only DB slice through
  // run_readonly_agent_analysis on the backend. Disabled / no-key path
  // returns a `skipped` AgentRun. Frontend never receives an API key.

  getAgentRuntimeStatus: () =>
    safeFetch<AgentRuntimeStatus>("/ai/agent-runtime/status/", () =>
      optimisticRuntimeStatus(),
    ),

  runCeoDailyBrief: () =>
    safeMutate<AgentRun>("/ai/agent-runtime/ceo/daily-brief/", "POST", {}, () =>
      optimisticAgentRun({ agent: "ceo" }),
    ),

  runCaioAuditSweep: () =>
    safeMutate<AgentRun>(
      "/ai/agent-runtime/caio/audit-sweep/",
      "POST",
      {},
      () => optimisticAgentRun({ agent: "caio" }),
    ),

  runAdsAnalysis: () =>
    safeMutate<AgentRun>("/ai/agent-runtime/ads/analyze/", "POST", {}, () =>
      optimisticAgentRun({ agent: "ads" }),
    ),

  runRtoAnalysis: () =>
    safeMutate<AgentRun>("/ai/agent-runtime/rto/analyze/", "POST", {}, () =>
      optimisticAgentRun({ agent: "rto" }),
    ),

  runSalesGrowthAnalysis: () =>
    safeMutate<AgentRun>(
      "/ai/agent-runtime/sales-growth/analyze/",
      "POST",
      {},
      () => optimisticAgentRun({ agent: "sales_growth" }),
    ),

  runCfoAnalysis: () =>
    safeMutate<AgentRun>("/ai/agent-runtime/cfo/analyze/", "POST", {}, () =>
      optimisticAgentRun({ agent: "cfo" }),
    ),

  runComplianceAnalysis: () =>
    safeMutate<AgentRun>(
      "/ai/agent-runtime/compliance/analyze/",
      "POST",
      {},
      () => optimisticAgentRun({ agent: "compliance" }),
    ),

  // ---------- PHASE 3C — Scheduler / cost / fallback snapshot ----------
  // Admin/director only; pure read endpoint. Frontend never receives any
  // provider API key — only redacted broker URL + last cost figure.

  getAiSchedulerStatus: () =>
    safeFetch<AiSchedulerStatus>("/ai/scheduler/status/", () =>
      optimisticSchedulerStatus(),
    ),

  // ---------- PHASE 3D — Governance: sandbox + prompts + budgets ----------
  // Admin/director only. The frontend never receives provider API keys.

  getSandboxStatus: () =>
    safeFetch<SandboxState>("/ai/sandbox/status/", () => ({
      isEnabled: false,
      note: "",
      updatedBy: "",
      updatedAt: new Date().toISOString(),
    })),

  setSandboxStatus: (payload: SandboxPatchPayload) =>
    safeMutate<SandboxState>("/ai/sandbox/status/", "PATCH", payload, () => ({
      isEnabled: payload.isEnabled,
      note: payload.note ?? "",
      updatedBy: "",
      updatedAt: new Date().toISOString(),
    })),

  listPromptVersions: (agent?: string) => {
    const path = agent
      ? `/ai/prompt-versions/?agent=${encodeURIComponent(agent)}`
      : "/ai/prompt-versions/";
    return safeFetch<PromptVersion[]>(path, () => []);
  },

  createPromptVersion: (payload: PromptVersionCreatePayload) =>
    safeMutate<PromptVersion>(
      "/ai/prompt-versions/",
      "POST",
      payload,
      () => optimisticPromptVersion(payload),
    ),

  activatePromptVersion: (id: string) =>
    safeMutate<PromptVersion>(
      `/ai/prompt-versions/${id}/activate/`,
      "POST",
      {},
      () => ({ ...optimisticPromptVersion({ agent: "ceo", version: "draft" }), id, isActive: true, status: "active" }),
    ),

  rollbackPromptVersion: (id: string, reason: string) =>
    safeMutate<PromptVersion>(
      `/ai/prompt-versions/${id}/rollback/`,
      "POST",
      { reason },
      () => ({ ...optimisticPromptVersion({ agent: "ceo", version: "draft" }), id, rollbackReason: reason, status: "active" }),
    ),

  listAgentBudgets: () =>
    safeFetch<AgentBudget[]>("/ai/budgets/", () => []),

  upsertAgentBudget: (payload: AgentBudgetWritePayload) =>
    safeMutate<AgentBudget>("/ai/budgets/", "POST", payload, () => ({
      id: 0,
      agent: payload.agent,
      dailyBudgetUsd: String(payload.dailyBudgetUsd),
      monthlyBudgetUsd: String(payload.monthlyBudgetUsd),
      isEnforced: payload.isEnforced ?? true,
      alertThresholdPct: payload.alertThresholdPct ?? 80,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      dailySpendUsd: "0",
      monthlySpendUsd: "0",
    })),

  // ---------- Phase 5A — WhatsApp Live Sender Foundation ----------
  getWhatsAppProviderStatus: () =>
    safeFetch<WhatsAppProviderStatus>(
      "/whatsapp/provider/status/",
      () => M.WHATSAPP_PROVIDER_STATUS as WhatsAppProviderStatus,
    ),
  listWhatsAppConnections: () =>
    safeFetch<WhatsAppConnection[]>(
      "/whatsapp/connections/",
      () => M.WHATSAPP_CONNECTIONS as WhatsAppConnection[],
    ),
  listWhatsAppTemplates: (params?: {
    actionKey?: string;
    category?: string;
    status?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params?.actionKey) qs.set("actionKey", params.actionKey);
    if (params?.category) qs.set("category", params.category);
    if (params?.status) qs.set("status", params.status);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<WhatsAppTemplate[]>(
      `/whatsapp/templates/${suffix}`,
      () => M.WHATSAPP_TEMPLATES as WhatsAppTemplate[],
    );
  },
  syncWhatsAppTemplates: (payload: WhatsAppTemplateSyncPayload = {}) =>
    safeMutate<WhatsAppTemplateSyncResult>(
      "/whatsapp/templates/sync/",
      "POST",
      payload,
      () => ({
        connectionId: (M.WHATSAPP_CONNECTIONS[0] as WhatsAppConnection).id,
        createdCount: 0,
        updatedCount: (M.WHATSAPP_TEMPLATES as WhatsAppTemplate[]).length,
        totalProcessed: (M.WHATSAPP_TEMPLATES as WhatsAppTemplate[]).length,
        actor: "mock",
      }),
    ),
  listWhatsAppConversations: (params?: { customerId?: string; status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.customerId) qs.set("customerId", params.customerId);
    if (params?.status) qs.set("status", params.status);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<WhatsAppConversation[]>(
      `/whatsapp/conversations/${suffix}`,
      () => M.WHATSAPP_CONVERSATIONS as WhatsAppConversation[],
    );
  },
  getWhatsAppConversationMessages: (conversationId: string) =>
    safeFetch<WhatsAppMessage[]>(
      `/whatsapp/conversations/${conversationId}/messages/`,
      () =>
        (M.WHATSAPP_MESSAGES as WhatsAppMessage[]).filter(
          (m) => m.conversationId === conversationId,
        ),
    ),
  listWhatsAppMessages: (params?: {
    customerId?: string;
    conversationId?: string;
    status?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.customerId) qs.set("customerId", params.customerId);
    if (params?.conversationId) qs.set("conversationId", params.conversationId);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<WhatsAppMessage[]>(
      `/whatsapp/messages/${suffix}`,
      () => M.WHATSAPP_MESSAGES as WhatsAppMessage[],
    );
  },
  sendWhatsAppTemplate: (payload: SendWhatsAppTemplatePayload) =>
    safeMutate<SendWhatsAppTemplateResponse>(
      "/whatsapp/send-template/",
      "POST",
      payload,
      () => optimisticWhatsAppSendResponse(payload),
    ),
  retryWhatsAppMessage: (id: string) =>
    safeMutate<WhatsAppMessage>(
      `/whatsapp/messages/${id}/retry/`,
      "POST",
      {},
      () => {
        const base = (M.WHATSAPP_MESSAGES as WhatsAppMessage[]).find(
          (m) => m.id === id,
        );
        if (!base) {
          return optimisticWhatsAppMessage({
            id,
            customerId: "NRG-MOCK",
            actionKey: "whatsapp.payment_reminder",
          });
        }
        return { ...base, status: "queued", attemptCount: base.attemptCount + 1 };
      },
    ),
  getWhatsAppConsent: (customerId: string) =>
    safeFetch<WhatsAppConsentSummary>(
      `/whatsapp/consent/${customerId}/`,
      () => ({
        customerId,
        consentWhatsapp: true,
        history: {
          customerId,
          consentState: "granted",
          grantedAt: null,
          revokedAt: null,
          optOutKeyword: "",
          expiresAt: null,
          lastInboundAt: null,
          source: "mock",
          metadata: {},
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
      }),
    ),
  patchWhatsAppConsent: (
    customerId: string,
    payload: WhatsAppConsentPatchPayload,
  ) =>
    safeMutate<WhatsAppConsentSummary>(
      `/whatsapp/consent/${customerId}/`,
      "PATCH",
      payload,
      () => ({
        customerId,
        consentWhatsapp: payload.consentState === "granted",
        history: {
          customerId,
          consentState: payload.consentState,
          grantedAt:
            payload.consentState === "granted"
              ? new Date().toISOString()
              : null,
          revokedAt:
            payload.consentState === "granted"
              ? null
              : new Date().toISOString(),
          optOutKeyword: "",
          expiresAt: null,
          lastInboundAt: null,
          source: payload.source ?? "operator",
          metadata: {},
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
      }),
    ),

  // ---------- Phase 5B — WhatsApp Inbox + Customer 360 timeline ----------
  getWhatsAppInbox: (params?: { limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<WhatsAppInboxSummary>(
      `/whatsapp/inbox/${suffix}`,
      () => emptyInboxSummary(),
    );
  },
  getWhatsAppConversation: (id: string) =>
    safeFetch<WhatsAppConversation | null>(
      `/whatsapp/conversations/${id}/`,
      () =>
        (M.WHATSAPP_CONVERSATIONS as WhatsAppConversation[]).find(
          (c) => c.id === id,
        ) ?? null,
    ),
  getWhatsAppConversationNotes: (id: string) =>
    safeFetch<WhatsAppInternalNote[]>(
      `/whatsapp/conversations/${id}/notes/`,
      () => [],
    ),
  createWhatsAppConversationNote: (
    id: string,
    payload: CreateInternalNotePayload,
  ) =>
    safeMutate<WhatsAppInternalNote>(
      `/whatsapp/conversations/${id}/notes/`,
      "POST",
      payload,
      () => optimisticInternalNote(id, payload),
    ),
  updateWhatsAppConversation: (
    id: string,
    payload: UpdateWhatsAppConversationPayload,
  ) =>
    safeMutate<WhatsAppConversation>(
      `/whatsapp/conversations/${id}/`,
      "PATCH",
      payload,
      () => optimisticConversationUpdate(id, payload),
    ),
  markWhatsAppConversationRead: (id: string) =>
    safeMutate<WhatsAppConversation>(
      `/whatsapp/conversations/${id}/mark-read/`,
      "POST",
      {},
      () => optimisticConversationUpdate(id, { /* unread cleared client-side */ }),
    ),
  sendWhatsAppConversationTemplate: (
    id: string,
    payload: SendConversationTemplatePayload,
  ) =>
    safeMutate<SendWhatsAppTemplateResponse>(
      `/whatsapp/conversations/${id}/send-template/`,
      "POST",
      payload,
      () => optimisticConversationSendResponse(id, payload),
    ),
  getCustomerWhatsAppTimeline: (customerId: string) =>
    safeFetch<WhatsAppCustomerTimeline>(
      `/whatsapp/customers/${customerId}/timeline/`,
      () => emptyCustomerTimeline(customerId),
    ),

  // ---------- Phase 5C — WhatsApp AI Chat Sales Agent ----------
  getWhatsAppAiStatus: () =>
    safeFetch<WhatsAppAiGlobalStatus>(
      "/whatsapp/ai/status/",
      () => emptyAiGlobalStatus(),
    ),
  updateWhatsAppConversationAiMode: (
    id: string,
    payload: UpdateWhatsAppAiModePayload,
  ) =>
    safeMutate<WhatsAppConversationAiPayload>(
      `/whatsapp/conversations/${id}/ai-mode/`,
      "PATCH",
      payload,
      () => optimisticAiPayload(id, payload),
    ),
  runWhatsAppConversationAi: (id: string) =>
    safeMutate<WhatsAppAiRunSummary>(
      `/whatsapp/conversations/${id}/run-ai/`,
      "POST",
      {},
      () => emptyAiRunSummary(id),
    ),
  getWhatsAppConversationAiRuns: (id: string) =>
    safeFetch<WhatsAppAiRunsResponse>(
      `/whatsapp/conversations/${id}/ai-runs/`,
      () => ({ ai: defaultAiState(), events: [] }),
    ),
  handoffWhatsAppConversation: (
    id: string,
    payload: WhatsAppAiHandoffPayload = {},
  ) =>
    safeMutate<WhatsAppConversationAiPayload>(
      `/whatsapp/conversations/${id}/handoff/`,
      "POST",
      payload,
      () =>
        optimisticAiPayload(id, {
          aiEnabled: false,
          aiMode: "disabled",
        }),
    ),
  resumeWhatsAppConversationAi: (id: string) =>
    safeMutate<WhatsAppConversationAiPayload>(
      `/whatsapp/conversations/${id}/resume-ai/`,
      "POST",
      {},
      () =>
        optimisticAiPayload(id, {
          aiEnabled: true,
          aiMode: "auto",
        }),
    ),

  // ---------- Phase 5D — Chat-to-call handoff + lifecycle automation ----------
  triggerWhatsAppConversationCall: (
    id: string,
    payload: TriggerWhatsAppCallPayload = {},
  ) =>
    safeMutate<TriggerWhatsAppCallResponse>(
      `/whatsapp/conversations/${id}/handoff-to-call/`,
      "POST",
      payload,
      () => optimisticTriggerCallResponse(payload),
    ),
  getWhatsAppConversationHandoffs: (id: string) =>
    safeFetch<WhatsAppHandoffToCall[]>(
      `/whatsapp/conversations/${id}/handoffs/`,
      () => [],
    ),
  getWhatsAppLifecycleEvents: (params?: {
    objectType?: string;
    objectId?: string;
    status?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.objectType) qs.set("objectType", params.objectType);
    if (params?.objectId) qs.set("objectId", params.objectId);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return safeFetch<WhatsAppLifecycleEvent[]>(
      `/whatsapp/lifecycle-events/${suffix}`,
      () => [],
    );
  },
  getClaimVaultCoverage: () =>
    safeFetch<ClaimVaultCoverageReport>("/compliance/claim-coverage/", () => ({
      totalProducts: 0,
      okCount: 0,
      weakCount: 0,
      missingCount: 0,
      demoCount: 0,
      items: [],
    })),

  // ---------- Phase 5E — Rescue Discount Flow + Day-20 Reorder ----------
  getOrderDiscountOffers: (orderId: string) =>
    safeFetch<DiscountOfferListResponse>(
      `/orders/${orderId}/discount-offers/`,
      () => emptyDiscountOfferList(orderId),
    ),
  createRescueDiscountOffer: (
    orderId: string,
    payload: CreateRescueOfferPayload,
  ) =>
    safeMutate<DiscountOffer>(
      `/orders/${orderId}/discount-offers/rescue/`,
      "POST",
      payload,
      () => optimisticDiscountOffer(orderId, payload),
    ),
  acceptRescueDiscountOffer: (orderId: string, offerId: number) =>
    safeMutate<DiscountOffer>(
      `/orders/${orderId}/discount-offers/${offerId}/accept/`,
      "POST",
      {},
      () => optimisticDiscountOfferDecision(orderId, offerId, "accepted"),
    ),
  rejectRescueDiscountOffer: (
    orderId: string,
    offerId: number,
    note: string = "",
  ) =>
    safeMutate<DiscountOffer>(
      `/orders/${orderId}/discount-offers/${offerId}/reject/`,
      "POST",
      { note },
      () => optimisticDiscountOfferDecision(orderId, offerId, "rejected"),
    ),
  getReorderDay20Status: () =>
    safeFetch<ReorderDay20StatusResponse>(
      "/whatsapp/reorder/day20/status/",
      () => ({
        enabled: false,
        lifecycleEnabled: false,
        lowerBoundDays: 20,
        upperBoundDays: 27,
        events: [],
      }),
    ),
  runReorderDay20Sweep: (dryRun: boolean = false) =>
    safeMutate<ReorderDay20RunResponse>(
      "/whatsapp/reorder/day20/run/",
      "POST",
      { dryRun },
      () => ({
        eligible: 0,
        queued: 0,
        skipped: 0,
        blocked: 0,
        failed: 0,
        dryRun,
      }),
    ),

  // ---------- Phase 5F-Gate Auto-Reply Monitoring Dashboard ----------

  getWhatsAppMonitoringOverview: (hours: number = 2) =>
    safeFetch<WhatsAppMonitoringOverview>(
      `/whatsapp/monitoring/overview/?hours=${hours}`,
      () => M.WHATSAPP_MONITORING_OVERVIEW as WhatsAppMonitoringOverview,
    ),
  getWhatsAppMonitoringGate: () =>
    safeFetch<WhatsAppMonitoringGate>(
      "/whatsapp/monitoring/gate/",
      () =>
        (M.WHATSAPP_MONITORING_OVERVIEW as WhatsAppMonitoringOverview).gate,
    ),
  getWhatsAppMonitoringActivity: (hours: number = 2) =>
    safeFetch<WhatsAppMonitoringActivity>(
      `/whatsapp/monitoring/activity/?hours=${hours}`,
      () =>
        (M.WHATSAPP_MONITORING_OVERVIEW as WhatsAppMonitoringOverview)
          .activity,
    ),
  getWhatsAppMonitoringCohort: () =>
    safeFetch<WhatsAppMonitoringCohort>(
      "/whatsapp/monitoring/cohort/",
      () =>
        (M.WHATSAPP_MONITORING_OVERVIEW as WhatsAppMonitoringOverview).cohort,
    ),
  getWhatsAppMonitoringAudit: (hours: number = 2, limit: number = 100) =>
    safeFetch<WhatsAppMonitoringAuditResponse>(
      `/whatsapp/monitoring/audit/?hours=${hours}&limit=${limit}`,
      () => M.WHATSAPP_MONITORING_AUDIT as WhatsAppMonitoringAuditResponse,
    ),
  getWhatsAppMonitoringMutationSafety: (hours: number = 2) =>
    safeFetch<WhatsAppMonitoringMutationSafety>(
      `/whatsapp/monitoring/mutation-safety/?hours=${hours}`,
      () =>
        (M.WHATSAPP_MONITORING_OVERVIEW as WhatsAppMonitoringOverview)
          .mutationSafety,
    ),
  getWhatsAppMonitoringUnexpectedOutbound: (hours: number = 2) =>
    safeFetch<WhatsAppMonitoringUnexpectedOutbound>(
      `/whatsapp/monitoring/unexpected-outbound/?hours=${hours}`,
      () =>
        (M.WHATSAPP_MONITORING_OVERVIEW as WhatsAppMonitoringOverview)
          .unexpectedOutbound,
    ),
};

// ---------- Optimistic mock builders for offline fallback ----------

function optimisticLead(payload: CreateLeadPayload): Lead {
  return {
    id: `LD-DRAFT-${Date.now()}`,
    name: payload.name,
    phone: payload.phone,
    state: payload.state,
    city: payload.city,
    language: payload.language ?? "Hinglish",
    source: payload.source ?? "Manual",
    campaign: payload.campaign ?? "",
    productInterest: payload.productInterest ?? "",
    status: "New",
    quality: payload.quality ?? "Warm",
    qualityScore: payload.qualityScore ?? 50,
    assignee: payload.assignee ?? "",
    duplicate: payload.duplicate ?? false,
    createdAt: "just now",
  };
}

function optimisticCustomer(payload: CustomerWritePayload): Customer {
  return {
    id: `CU-DRAFT-${Date.now()}`,
    leadId: payload.leadId ?? "",
    name: payload.name ?? "",
    phone: payload.phone ?? "",
    state: payload.state ?? "",
    city: payload.city ?? "",
    language: payload.language ?? "Hinglish",
    productInterest: payload.productInterest ?? "",
    diseaseCategory: payload.diseaseCategory ?? "",
    lifestyleNotes: payload.lifestyleNotes ?? "",
    objections: payload.objections ?? [],
    aiSummary: payload.aiSummary ?? "",
    riskFlags: payload.riskFlags ?? [],
    reorderProbability: payload.reorderProbability ?? 0,
    satisfaction: payload.satisfaction ?? 0,
    consent: {
      call: payload.consent?.call ?? true,
      whatsapp: payload.consent?.whatsapp ?? false,
      marketing: payload.consent?.marketing ?? false,
    },
  };
}

function optimisticOrder(payload: CreateOrderPayload): Order {
  return {
    id: `NRG-DRAFT-${Date.now()}`,
    customerName: payload.customerName,
    phone: payload.phone,
    product: payload.product,
    quantity: payload.quantity ?? 1,
    amount: payload.amount ?? 3000,
    discountPct: payload.discountPct ?? 0,
    advancePaid: payload.advancePaid ?? false,
    advanceAmount: payload.advanceAmount ?? 0,
    paymentStatus: payload.paymentStatus ?? "Pending",
    state: payload.state,
    city: payload.city,
    rtoRisk: payload.rtoRisk ?? "Low",
    rtoScore: payload.rtoScore ?? 10,
    agent: payload.agent ?? "",
    stage: payload.stage ?? "Order Punched",
    awb: null,
    ageHours: 0,
    createdAt: "just now",
  };
}

function optimisticPayment(payload: PaymentLinkPayload): Payment {
  return {
    id: `PAY-DRAFT-${Date.now()}`,
    orderId: payload.orderId,
    customer: "",
    amount: payload.amount,
    gateway: payload.gateway,
    status: "Pending",
    type: payload.type,
    time: "just now",
  };
}

function optimisticShipment(payload: ShipmentCreatePayload): Shipment {
  const awb = `DLH${Date.now().toString().slice(-8)}`;
  return {
    awb,
    orderId: payload.orderId,
    customer: "",
    state: "",
    city: "",
    status: "Pickup Scheduled",
    eta: "3 days",
    courier: "Delhivery",
    trackingUrl: `https://delhivery.example/track/${awb}`,
    riskFlag: "",
    timeline: [
      { step: "AWB Generated", at: "Day 0", done: true },
      { step: "Pickup Scheduled", at: "Day 0", done: true },
      { step: "In Transit", at: "Day 1", done: false },
      { step: "Out for Delivery", at: "Day 3", done: false },
      { step: "Delivered / RTO", at: "Day 4", done: false },
    ],
  };
}

function optimisticRescue(payload: RescueAttemptCreatePayload): RescueAttempt {
  return {
    id: `RES-DRAFT-${Date.now()}`,
    orderId: payload.orderId,
    channel: payload.channel,
    outcome: "Pending",
    notes: payload.notes ?? "",
    attemptedAt: new Date().toISOString(),
  };
}

function optimisticCallTrigger(payload: CallTriggerPayload): CallTriggerResponse {
  const safeLead = payload.leadId.replace(/-/g, "_");
  const purpose = payload.purpose || "sales_call";
  return {
    callId: `CL-DRAFT-${Date.now()}`,
    provider: "vapi",
    status: "queued",
    leadId: payload.leadId,
    providerCallId: `call_mock_${safeLead}_${purpose}`,
  };
}

function optimisticAgentRun(payload: AgentRunCreatePayload): AgentRun {
  return {
    id: `AR-DRAFT-${Date.now()}`,
    agent: payload.agent,
    promptVersion: "v1.0-phase3a",
    inputPayload: payload.input ?? {},
    outputPayload: {},
    status: "skipped",
    provider: "disabled",
    model: "",
    latencyMs: 0,
    costUsd: null,
    errorMessage: "Backend offline — optimistic stub. Phase 3A runs are dry-run only.",
    dryRun: true,
    triggeredBy: "",
    createdAt: new Date().toISOString(),
    completedAt: null,
    promptTokens: null,
    completionTokens: null,
    totalTokens: null,
    providerAttempts: [],
    fallbackUsed: false,
    pricingSnapshot: {},
  };
}

function optimisticRuntimeStatus(): AgentRuntimeStatus {
  return {
    phase: "3B",
    dryRunOnly: true,
    agents: [
      "ceo",
      "caio",
      "ads",
      "rto",
      "sales_growth",
      "cfo",
      "compliance",
    ],
    lastRuns: {
      ceo: null,
      caio: null,
      ads: null,
      rto: null,
      sales_growth: null,
      cfo: null,
      compliance: null,
      marketing: null,
    },
  };
}

function optimisticPromptVersion(payload: PromptVersionCreatePayload): PromptVersion {
  return {
    id: `PV-DRAFT-${Date.now()}`,
    agent: payload.agent,
    version: payload.version,
    title: payload.title ?? "",
    systemPolicy: payload.systemPolicy ?? "",
    rolePrompt: payload.rolePrompt ?? "",
    instructionPayload: payload.instructionPayload ?? {},
    isActive: false,
    status: "draft",
    createdBy: "",
    metadata: payload.metadata ?? {},
    createdAt: new Date().toISOString(),
    activatedAt: null,
    rolledBackAt: null,
    rollbackReason: "",
  };
}

function optimisticApprovalDecision(
  id: string,
  status: ApprovalRequest["status"],
  note: string,
): ApprovalRequest {
  const fallback = (M.APPROVAL_REQUESTS as ApprovalRequest[]).find((a) => a.id === id);
  const base: ApprovalRequest =
    fallback ?? ((M.APPROVAL_REQUESTS as ApprovalRequest[])[0] as ApprovalRequest);
  return {
    ...base,
    id,
    status,
    decisionNote: note,
    decidedBy: "you",
    decidedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function optimisticApprovalEvaluation(
  payload: ApprovalEvaluatePayload,
): ApprovalEvaluationResult {
  return {
    action: payload.action,
    mode: "approval_required",
    approver: "admin",
    status: "pending",
    allowed: false,
    requiresHuman: true,
    reason: "Offline preview — backend unreachable.",
    policy: {},
    approvalRequestId: null,
    notes: ["offline_preview"],
  };
}

function optimisticAgentRunApproval(agentRunId: string, reason: string): ApprovalRequest {
  return {
    id: `APR-DRAFT-${Date.now()}`,
    action: "agent_run.suggested",
    mode: "approval_required",
    approver: "admin",
    status: "pending",
    requestedBy: "you",
    requestedByAgent: agentRunId,
    targetApp: "ai_governance",
    targetModel: "AgentRun",
    targetObjectId: agentRunId,
    proposedPayload: {},
    policySnapshot: {},
    reason: reason || "Draft promotion (offline)",
    decisionNote: "",
    decidedBy: "",
    decidedAt: null,
    expiresAt: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    metadata: { agent_run_id: agentRunId, offline: true },
    decisionLogs: [],
  };
}

function optimisticExecuteApprovalResponse(id: string): ExecuteApprovalResponse {
  return {
    approvalRequestId: id,
    action: "",
    executionStatus: "skipped",
    executedAt: null,
    executedBy: "",
    result: {},
    errorMessage: "Offline preview — backend unreachable.",
    message: "Offline preview — backend unreachable.",
    alreadyExecuted: false,
  };
}

function optimisticSweepResult(payload: RewardPenaltySweepPayload): RewardPenaltySweepResult {
  return {
    evaluatedOrders: 0,
    createdEvents: 0,
    updatedEvents: 0,
    skippedOrders: 0,
    totalReward: 0,
    totalPenalty: 0,
    netScore: 0,
    dryRun: payload.dryRun ?? false,
    leaderboardUpdated: false,
    missingDataWarnings: [],
  };
}

function optimisticSchedulerStatus(): AiSchedulerStatus {
  return {
    celeryConfigured: true,
    celeryEagerMode: true,
    redisConfigured: false,
    brokerUrl: "redis://localhost:6379/0",
    timezone: "Asia/Kolkata",
    morningSchedule: { hour: 9, minute: 0 },
    eveningSchedule: { hour: 18, minute: 0 },
    lastDailyBriefingRun: null,
    lastCaioSweepRun: null,
    aiProvider: "disabled",
    primaryModel: "",
    fallbacks: ["openai", "anthropic"],
    lastCostUsd: null,
    lastFallbackUsed: false,
  };
}

// ---------- Phase 5A — WhatsApp optimistic helpers ----------

function optimisticWhatsAppMessage(args: {
  id?: string;
  customerId: string;
  actionKey: string;
  templateId?: string;
  variables?: Record<string, string | number>;
}): WhatsAppMessage {
  const id = args.id ?? `WAM-MOCK-${Date.now()}`;
  const now = new Date().toISOString();
  return {
    id,
    conversationId: `WCV-MOCK-${args.customerId}`,
    customerId: args.customerId,
    providerMessageId: `wamid.MOCK_${id}`,
    direction: "outbound",
    status: "sent",
    type: "template",
    body: `Mock template ${args.actionKey}`,
    templateId: args.templateId ?? "WAT-MOCK-1",
    templateVariables: { ...(args.variables ?? {}) },
    mediaUrl: "",
    aiGenerated: false,
    approvalRequestId: null,
    errorMessage: "",
    errorCode: "",
    attemptCount: 1,
    idempotencyKey: `wsp:${id}`,
    metadata: { trigger: "mock" },
    queuedAt: now,
    sentAt: now,
    deliveredAt: null,
    readAt: null,
    createdAt: now,
    updatedAt: now,
  };
}

function optimisticWhatsAppSendResponse(
  payload: SendWhatsAppTemplatePayload,
): SendWhatsAppTemplateResponse {
  const message = optimisticWhatsAppMessage({
    customerId: payload.customerId,
    actionKey: payload.actionKey,
    templateId: payload.templateId,
    variables: payload.variables,
  });
  return {
    message,
    conversationId: message.conversationId,
    approvalRequestId: null,
    autoApproved: true,
  };
}

function optimisticInternalNote(
  conversationId: string,
  payload: CreateInternalNotePayload,
): WhatsAppInternalNote {
  const now = new Date().toISOString();
  return {
    id: Date.now(),
    conversationId,
    authorId: null,
    authorName: "you",
    body: payload.body,
    metadata: payload.metadata ?? {},
    createdAt: now,
    updatedAt: now,
  };
}

function optimisticConversationUpdate(
  id: string,
  patch: UpdateWhatsAppConversationPayload,
): WhatsAppConversation {
  const base = (M.WHATSAPP_CONVERSATIONS as WhatsAppConversation[]).find(
    (c) => c.id === id,
  );
  const fallback: WhatsAppConversation = base ?? {
    id,
    customerId: "NRG-MOCK",
    customerName: "Mock customer",
    customerPhone: "",
    connectionId: "WAC-MOCK-1",
    assignedToId: null,
    assignedToUsername: "",
    status: "open",
    aiStatus: "disabled",
    unreadCount: 0,
    lastMessageText: "",
    lastMessageAt: null,
    lastInboundAt: null,
    subject: "",
    tags: [],
    resolvedAt: null,
    resolvedById: null,
    metadata: {},
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  return {
    ...fallback,
    ...patch,
    unreadCount: 0,
    updatedAt: new Date().toISOString(),
  };
}

function optimisticConversationSendResponse(
  conversationId: string,
  payload: SendConversationTemplatePayload,
): SendWhatsAppTemplateResponse {
  const message = optimisticWhatsAppMessage({
    customerId: "NRG-MOCK",
    actionKey: payload.actionKey,
    templateId: payload.templateId,
    variables: payload.variables,
  });
  return {
    message: { ...message, conversationId },
    conversationId,
    approvalRequestId: null,
    autoApproved: true,
  };
}

function emptyInboxSummary(): WhatsAppInboxSummary {
  return {
    conversations: [],
    counts: {
      all: 0,
      unread: 0,
      open: 0,
      pending: 0,
      resolved: 0,
      escalatedToHuman: 0,
    },
    aiSuggestions: {
      enabled: false,
      status: "disabled",
      message: "AI WhatsApp suggestions are planned for Phase 5C.",
    },
  };
}

function emptyCustomerTimeline(customerId: string): WhatsAppCustomerTimeline {
  return {
    customerId,
    consentWhatsapp: false,
    conversations: [],
    items: [],
    aiSuggestions: {
      enabled: false,
      status: "disabled",
      message: "AI WhatsApp suggestions are planned for Phase 5C.",
    },
  };
}

export type Api = typeof api;

// ---------- Phase 5C — WhatsApp AI optimistic helpers ----------

function defaultAiState(): WhatsAppConversationAiState {
  return {
    aiEnabled: true,
    aiMode: "auto",
    stage: "greeting",
    detectedLanguage: "",
    detectedCategory: "",
    lastAiAction: "",
    lastAiConfidence: 0,
    discountAskCount: 0,
    totalDiscountPct: 0,
    offeredDiscountPct: 0,
    handoffRequired: false,
    handoffReason: "",
    orderId: "",
    paymentId: "",
    paymentLink: "",
    lastSuggestion: null,
  };
}

function optimisticAiPayload(
  conversationId: string,
  patch: UpdateWhatsAppAiModePayload,
): WhatsAppConversationAiPayload {
  const base = defaultAiState();
  return {
    conversationId,
    ai: {
      ...base,
      ...(patch.aiEnabled !== undefined ? { aiEnabled: patch.aiEnabled } : {}),
      ...(patch.aiMode !== undefined ? { aiMode: patch.aiMode } : {}),
    },
  };
}

function emptyAiRunSummary(conversationId: string): WhatsAppAiRunSummary {
  return {
    conversationId,
    inboundMessageId: "",
    action: "no_action",
    sent: false,
    sentMessageId: "",
    handoffRequired: false,
    handoffReason: "",
    blockedReason: "ai_provider_disabled",
    stage: "greeting",
    confidence: 0,
    language: "",
    category: "",
    orderId: "",
    paymentId: "",
  };
}

function emptyAiGlobalStatus(): WhatsAppAiGlobalStatus {
  return {
    enabled: false,
    status: "provider_disabled",
    message:
      "AI provider is disabled (mock fallback). Set AI_PROVIDER and WHATSAPP_AI_AUTO_REPLY_ENABLED in production.",
    provider: "disabled",
    autoReplyEnabled: false,
    confidenceThreshold: 0.75,
    rateLimits: {
      maxTurnsPerConversationPerHour: 10,
      maxMessagesPerCustomerPerDay: 30,
    },
  };
}

// ---------- Phase 5D — handoff optimistic helper ----------

function optimisticTriggerCallResponse(
  payload: TriggerWhatsAppCallPayload,
): TriggerWhatsAppCallResponse {
  return {
    handoffId: Date.now(),
    status: "skipped",
    callId: "",
    providerCallId: "",
    reason: payload.reason ?? "customer_requested_call",
    skipped: true,
    errorMessage: "Backend offline — optimistic stub.",
    message: "Backend offline — optimistic stub.",
  };
}

// ---------- Phase 5E — Discount offer optimistic helpers ----------

function emptyDiscountOfferList(orderId: string): DiscountOfferListResponse {
  return {
    orderId,
    currentDiscountPct: 0,
    cap: {
      currentTotalPct: 0,
      capRemainingPct: 50,
      finalTotalIfAppliedPct: 0,
      capPassed: true,
      totalCapPct: 50,
    },
    offers: [],
  };
}

function optimisticDiscountOffer(
  orderId: string,
  payload: CreateRescueOfferPayload,
): DiscountOffer {
  const now = new Date().toISOString();
  const offered = payload.requestedPct ?? 0;
  return {
    id: Date.now(),
    orderId,
    customerId: "",
    conversationId: payload.conversationId ?? "",
    sourceChannel: payload.sourceChannel ?? "operator",
    stage: payload.stage,
    triggerReason: payload.triggerReason,
    previousDiscountPct: 0,
    offeredAdditionalPct: offered,
    resultingTotalDiscountPct: offered,
    capRemainingPct: Math.max(0, 50 - offered),
    status: "offered",
    blockedReason: "",
    offeredByAgent: "operator",
    approvalRequestId: "",
    metadata: payload.metadata ?? {},
    createdAt: now,
    updatedAt: now,
  };
}

function optimisticDiscountOfferDecision(
  orderId: string,
  offerId: number,
  status: "accepted" | "rejected",
): DiscountOffer {
  const now = new Date().toISOString();
  return {
    id: offerId,
    orderId,
    customerId: "",
    conversationId: "",
    sourceChannel: "operator",
    stage: "confirmation",
    triggerReason: "offline_decision",
    previousDiscountPct: 0,
    offeredAdditionalPct: 0,
    resultingTotalDiscountPct: 0,
    capRemainingPct: 50,
    status,
    blockedReason: "",
    offeredByAgent: "operator",
    approvalRequestId: "",
    metadata: {},
    createdAt: now,
    updatedAt: now,
  };
}

/**
 * Test-only export — lets vitest assert that the mock fallback fires when the
 * backend is unreachable. Not used in production code paths.
 */
export const __test__ = { safeFetch, safeMutate };
