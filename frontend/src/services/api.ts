/**
 * Mock API service layer for Nirogidhara AI Command Center.
 *
 * Each function below maps to a future Django REST Framework endpoint.
 * Replace the mock returns with real `fetch`/`axios` calls when the backend
 * is ready — the function signatures and shapes are the contract.
 *
 * Planned endpoints:
 *   GET  /api/dashboard/metrics
 *   GET  /api/dashboard/activity
 *   GET  /api/leads
 *   GET  /api/leads/:id
 *   GET  /api/customers
 *   GET  /api/customers/:id
 *   GET  /api/orders
 *   GET  /api/orders/pipeline
 *   GET  /api/calls
 *   GET  /api/calls/active
 *   GET  /api/confirmation/queue
 *   GET  /api/payments
 *   GET  /api/shipments
 *   GET  /api/rto/risk
 *   GET  /api/agents
 *   GET  /api/agents/hierarchy
 *   GET  /api/ai/ceo-briefing
 *   GET  /api/ai/caio-audits
 *   GET  /api/rewards
 *   GET  /api/compliance/claims
 *   GET  /api/learning/recordings
 *   GET  /api/analytics/*
 *   GET  /api/settings
 */

import * as M from "./mockData";
import type {
  ActiveCall,
  ActivityEvent,
  Agent,
  CaioAudit,
  Call,
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

const wait = <T,>(data: T, ms = 0): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(data), ms));

export const api = {
  // Dashboard
  getDashboardMetrics: () => wait(M.DASHBOARD_METRICS as DashboardMetrics),
  getLiveActivityFeed: () => wait(M.ACTIVITY_FEED as ActivityEvent[]),
  getFunnel: () => wait(M.FUNNEL as KPITrend[]),
  getRevenueTrend: () => wait(M.REVENUE_TREND as KPITrend[]),
  getStateRto: () => wait(M.STATE_RTO as KPITrend[]),
  getProductPerformance: () => wait(M.PRODUCT_PERFORMANCE as KPITrend[]),
  getAnalyticsData: () =>
    wait({
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
    }),

  // Leads / Customers
  getLeads: () => wait(M.LEADS as Lead[]),
  getLeadById: (id: string) => wait((M.LEADS as Lead[]).find((l) => l.id === id)),
  getCustomers: () => wait(M.CUSTOMERS as Customer[]),
  getCustomerById: (id: string) => wait((M.CUSTOMERS as Customer[]).find((c) => c.id === id)),

  // Orders
  getOrders: () => wait(M.ORDERS as Order[]),
  getOrderPipeline: () => wait(M.ORDERS as Order[]),

  // Calls
  getCalls: () => wait(M.CALLS as Call[]),
  getActiveCall: () => wait(M.ACTIVE_CALL as ActiveCall),
  getCallTranscripts: () => wait(M.ACTIVE_CALL.transcript),

  // Confirmation
  getConfirmationQueue: () => wait(M.CONFIRMATION_QUEUE as Array<Order & { hoursWaiting: number; addressConfidence: number; checklist: Record<string, boolean> }>),

  // Payments / Shipments / RTO
  getPayments: () => wait(M.PAYMENTS as Payment[]),
  getShipments: () => wait(M.SHIPMENTS as Shipment[]),
  getRtoRiskOrders: () => wait(M.RTO_RISK_ORDERS as Array<Order & { riskReasons: string[]; rescueStatus: string }>),

  // Agents
  getAgentStatus: () => wait(M.AGENTS as unknown as Agent[]),
  getAgentHierarchy: () =>
    wait({
      root: "Prarit Sidana (Director)",
      ceo: "CEO AI Agent",
      caio: "CAIO Agent",
      departments: (M.AGENTS as unknown as Agent[]).filter((a) => a.id !== "ceo" && a.id !== "caio"),
    }),

  // AI
  getCeoBriefing: () => wait(M.CEO_BRIEFING as CeoBriefing),
  getCaioAudits: () => wait(M.CAIO_AUDITS as CaioAudit[]),

  // Rewards / Compliance / Learning
  getRewardPenaltyScores: () => wait(M.REWARD_LEADERBOARD as RewardPenalty[]),
  getClaimVault: () => wait(M.CLAIM_VAULT as Claim[]),
  getHumanCallLearningItems: () => wait(M.LEARNING_RECORDINGS as LearningRecording[]),

  // Settings
  getSettingsMock: () =>
    wait({ approvalMatrix: M.APPROVAL_MATRIX, integrations: M.INTEGRATIONS }),
};

export type Api = typeof api;
