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

const wait = <T,>(data: T, ms = 0): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(data), ms));

export const api = {
  // Dashboard
  getDashboardMetrics: () => wait(M.DASHBOARD_METRICS),
  getLiveActivityFeed: () => wait(M.ACTIVITY_FEED),
  getFunnel: () => wait(M.FUNNEL),
  getRevenueTrend: () => wait(M.REVENUE_TREND),
  getStateRto: () => wait(M.STATE_RTO),
  getProductPerformance: () => wait(M.PRODUCT_PERFORMANCE),

  // Leads / Customers
  getLeads: () => wait(M.LEADS),
  getLeadById: (id: string) => wait(M.LEADS.find((l) => l.id === id)),
  getCustomers: () => wait(M.CUSTOMERS),
  getCustomerById: (id: string) => wait(M.CUSTOMERS.find((c) => c.id === id)),

  // Orders
  getOrders: () => wait(M.ORDERS),
  getOrderPipeline: () => wait(M.ORDERS),

  // Calls
  getCalls: () => wait(M.CALLS),
  getActiveCall: () => wait(M.ACTIVE_CALL),

  // Confirmation
  getConfirmationQueue: () => wait(M.CONFIRMATION_QUEUE),

  // Payments / Shipments / RTO
  getPayments: () => wait(M.PAYMENTS),
  getShipments: () => wait(M.SHIPMENTS),
  getRtoRiskOrders: () => wait(M.RTO_RISK_ORDERS),

  // Agents
  getAgentStatus: () => wait(M.AGENTS),
  getAgentHierarchy: () =>
    wait({
      root: "Prarit Sidana (Director)",
      ceo: "CEO AI Agent",
      caio: "CAIO Agent",
      departments: M.AGENTS.filter((a) => a.id !== "ceo" && a.id !== "caio"),
    }),

  // AI
  getCeoBriefing: () => wait(M.CEO_BRIEFING),
  getCaioAudits: () => wait(M.CAIO_AUDITS),

  // Rewards / Compliance / Learning
  getRewardPenaltyScores: () => wait(M.REWARD_LEADERBOARD),
  getClaimVault: () => wait(M.CLAIM_VAULT),
  getHumanCallLearningItems: () => wait(M.LEARNING_RECORDINGS),

  // Settings
  getSettingsMock: () =>
    wait({ approvalMatrix: M.APPROVAL_MATRIX, integrations: M.INTEGRATIONS }),
};

export type Api = typeof api;