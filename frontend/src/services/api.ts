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
  CaioAudit,
  Call,
  CallTranscriptLine,
  CeoBriefing,
  Claim,
  Customer,
  DashboardMetrics,
  KPITrend,
  Lead,
  LearningRecording,
  Order,
  Payment,
  RewardPenalty,
  Shipment,
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
  getClaimVault: () => safeFetch<Claim[]>("/compliance/claims/", () => M.CLAIM_VAULT as Claim[]),
  getHumanCallLearningItems: () =>
    safeFetch<LearningRecording[]>("/learning/recordings/", () => M.LEARNING_RECORDINGS as LearningRecording[]),

  // Settings
  getSettingsMock: () =>
    safeFetch("/settings/", () => ({ approvalMatrix: M.APPROVAL_MATRIX, integrations: M.INTEGRATIONS })),
};

export type Api = typeof api;

/**
 * Test-only export — lets vitest assert that the mock fallback fires when the
 * backend is unreachable. Not used in production code paths.
 */
export const __test__ = { safeFetch };
