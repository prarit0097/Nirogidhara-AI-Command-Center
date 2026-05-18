import { useEffect, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  SaasAdminOverview,
  SaasAiProviderRoutePreview,
  SaasAiProviderRoutingPreview,
  SaasProviderReadiness,
  SaasProviderExecutionAttempt,
  SaasProviderExecutionReadiness,
  SaasProviderTestPlan,
  SaasProviderTestPlanReadiness,
  McpGatewayReadiness,
  McpInvocationsResponse,
  McpSecurityPosture,
  McpToolDefinitionDto,
  McpToolInvocationDto,
  McpToolsResponse,
  SaasRazorpayAuditReview,
  SaasRazorpayWebhookEventDto,
  SaasRazorpayBusinessMutationSandboxPlan,
  SaasRazorpayBusinessMutationSandboxReadiness,
  SaasRazorpayPaymentDispatchPilotPlanReadiness,
  SaasRazorpayPaymentDispatchPilotPlansResponse,
  SaasRazorpayPaymentDispatchReadiness,
  SaasRazorpayPaymentDispatchReadinessGatesResponse,
  SaasRazorpayControlledPilotExecutionAttemptsResponse,
  SaasRazorpayControlledPilotExecutionReadiness,
  SaasRazorpayControlledPilotGateReadiness,
  SaasRazorpayControlledPilotGatesResponse,
  SaasRazorpayCourierReadiness,
  SaasRazorpayCourierReadinessGatesResponse,
  SaasRazorpayCourierExecutionAttemptsResponse,
  SaasRazorpayCourierExecutionReadiness,
  SaasRazorpayCourierExecutionEvidenceLockReadiness,
  SaasRazorpayCourierExecutionEvidenceLocksResponse,
  SaasPhase7ELiveInternalSendReadiness,
  SaasPhase7ELiveInternalSendAttemptsResponse,
  SaasPhase7ELiveBRealCustomerGatesResponse,
  SaasPhase7GLiveRealCustomerDispatchGatesResponse,
  CustomerSuccessCohortsResponse,
  RtoPreventionCohortsResponse,
  CfoLatestResponse,
  DataAnalystLatestResponse,
  CallingTeamLeaderLatestResponse,
  CeoOrchestrationLatestResponse,
  CaioAuditSnapshot,
  LearningProposalsListResponse,
  LearningProposalSummary,
  SaasPhase7IFinalAuditLockReadiness,
  SaasPhase7IFinalAuditLocksResponse,
  SaasPhase8APaymentOrderMutationSandboxReadiness,
  SaasPhase8APaymentOrderMutationSandboxGatesResponse,
  SaasPhase8BPaymentOrderMutationReviewReadiness,
  SaasPhase8BPaymentOrderMutationReviewGatesResponse,
  SaasPhase8CPaymentOrderControlledMutationReadiness,
  SaasPhase8CPaymentOrderControlledMutationGatesResponse,
  SaasPhase8DControlledMutationEvidenceLockReadiness,
  SaasPhase8DControlledMutationEvidenceLocksResponse,
  SaasPhase8ERealCustomerPaymentOrderPilotReadiness,
  SaasPhase8ERealCustomerPaymentOrderPilotGatesResponse,
  SaasPhase8ERealCustomerCandidatePoolResponse,
  SaasPhase8ERealCustomerCandidatePoolRow,
  SaasPhase8FRealCustomerControlledMutationReadiness,
  SaasPhase8FRealCustomerControlledMutationGatesResponse,
  SaasRazorpayWhatsAppInternalNotificationGatesResponse,
  SaasRazorpayWhatsAppInternalNotificationReadiness,
  SaasRazorpayPhase6FinalAuditLockReadiness,
  SaasRazorpayPhase6FinalAuditLocksResponse,
  SaasRazorpayPaymentOrderWorkflowGateReadiness,
  SaasRazorpayPaymentOrderWorkflowGatesResponse,
  SaasRazorpaySandboxPaidStatusMutationAttemptsResponse,
  SaasRazorpaySandboxPaidStatusMutationReadiness,
  SaasRazorpaySandboxStatusMappingReadiness,
  SaasRazorpaySandboxStatusReviewDto,
  SaasRazorpaySandboxStatusReviewsResponse,
  SaasRazorpayWebhookEventsResponse,
  SaasRazorpayWebhookHandlerReadiness,
  SaasRazorpayWebhookPlan,
  SaasRazorpayWebhookReadiness,
  SaasRuntimeLiveGateSummary,
  SaasLiveGatePolicy,
  SaasRuntimeDryRunOperationDecision,
  SaasRuntimeDryRunReport,
  SaasRuntimeLiveGateSimulation,
  SaasRuntimeLiveGateSimulationsResponse,
  SaasRuntimeRoutingProviderPreview,
  SaasRuntimeRoutingReadiness,
} from "@/types/domain";
import {
  Building2,
  CheckCircle2,
  Cpu,
  AlertTriangle,
  Bot,
  ClipboardList,
  CreditCard,
  FileSearch,
  KeyRound,
  Network,
  Webhook,
  LockKeyhole,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  SlidersHorizontal,
  Workflow,
  type LucideIcon,
} from "lucide-react";

function boolTone(
  value: boolean,
  successWhenTrue = true,
): "success" | "danger" {
  return value === successWhenTrue ? "success" : "danger";
}

export default function SaasAdminPage() {
  const [overview, setOverview] = useState<SaasAdminOverview | null>(null);
  const [routing, setRouting] =
    useState<SaasRuntimeRoutingReadiness | null>(null);
  const [dryRun, setDryRun] = useState<SaasRuntimeDryRunReport | null>(null);
  const [aiRouting, setAiRouting] =
    useState<SaasAiProviderRoutingPreview | null>(null);
  const [liveGate, setLiveGate] =
    useState<SaasRuntimeLiveGateSummary | null>(null);
  const [simulations, setSimulations] =
    useState<SaasRuntimeLiveGateSimulationsResponse | null>(null);
  const [providerTestPlans, setProviderTestPlans] =
    useState<SaasProviderTestPlanReadiness | null>(null);
  const [providerExecutionGate, setProviderExecutionGate] =
    useState<SaasProviderExecutionReadiness | null>(null);
  const [razorpayWebhookReadiness, setRazorpayWebhookReadiness] =
    useState<SaasRazorpayWebhookReadiness | null>(null);
  const [razorpayWebhookPlan, setRazorpayWebhookPlan] =
    useState<SaasRazorpayWebhookPlan | null>(null);
  const [razorpayAuditReview, setRazorpayAuditReview] =
    useState<SaasRazorpayAuditReview | null>(null);
  const [mcpReadiness, setMcpReadiness] =
    useState<McpGatewayReadiness | null>(null);
  const [mcpSecurityPosture, setMcpSecurityPosture] =
    useState<McpSecurityPosture | null>(null);
  const [mcpTools, setMcpTools] = useState<McpToolsResponse | null>(null);
  const [mcpInvocations, setMcpInvocations] =
    useState<McpInvocationsResponse | null>(null);
  const [razorpayWebhookHandlerReadiness, setRazorpayWebhookHandlerReadiness] =
    useState<SaasRazorpayWebhookHandlerReadiness | null>(null);
  const [razorpayWebhookEvents, setRazorpayWebhookEvents] =
    useState<SaasRazorpayWebhookEventsResponse | null>(null);
  const [
    razorpayBusinessMutationSandboxPlan,
    setRazorpayBusinessMutationSandboxPlan,
  ] = useState<SaasRazorpayBusinessMutationSandboxPlan | null>(null);
  const [
    razorpayBusinessMutationSandboxReadiness,
    setRazorpayBusinessMutationSandboxReadiness,
  ] = useState<SaasRazorpayBusinessMutationSandboxReadiness | null>(null);
  const [
    razorpaySandboxStatusMappingReadiness,
    setRazorpaySandboxStatusMappingReadiness,
  ] = useState<SaasRazorpaySandboxStatusMappingReadiness | null>(null);
  const [
    razorpaySandboxStatusReviews,
    setRazorpaySandboxStatusReviews,
  ] = useState<SaasRazorpaySandboxStatusReviewsResponse | null>(null);
  const [phase6oActionPending, setPhase6oActionPending] = useState<number | null>(
    null,
  );
  const [phase6oActionMessage, setPhase6oActionMessage] = useState<string>("");
  const [
    razorpaySandboxPaidStatusReadiness,
    setRazorpaySandboxPaidStatusReadiness,
  ] = useState<SaasRazorpaySandboxPaidStatusMutationReadiness | null>(null);
  const [
    razorpaySandboxPaidStatusAttempts,
    setRazorpaySandboxPaidStatusAttempts,
  ] = useState<SaasRazorpaySandboxPaidStatusMutationAttemptsResponse | null>(
    null,
  );
  const [
    razorpayPaymentOrderWorkflowReadiness,
    setRazorpayPaymentOrderWorkflowReadiness,
  ] = useState<SaasRazorpayPaymentOrderWorkflowGateReadiness | null>(null);
  const [
    razorpayPaymentOrderWorkflowGates,
    setRazorpayPaymentOrderWorkflowGates,
  ] = useState<SaasRazorpayPaymentOrderWorkflowGatesResponse | null>(null);
  const [
    razorpayPaymentDispatchReadiness,
    setRazorpayPaymentDispatchReadiness,
  ] = useState<SaasRazorpayPaymentDispatchReadiness | null>(null);
  const [
    razorpayPaymentDispatchReadinessGates,
    setRazorpayPaymentDispatchReadinessGates,
  ] = useState<SaasRazorpayPaymentDispatchReadinessGatesResponse | null>(null);
  const [
    razorpayPaymentDispatchPilotPlanReadiness,
    setRazorpayPaymentDispatchPilotPlanReadiness,
  ] = useState<SaasRazorpayPaymentDispatchPilotPlanReadiness | null>(null);
  const [
    razorpayPaymentDispatchPilotPlans,
    setRazorpayPaymentDispatchPilotPlans,
  ] = useState<SaasRazorpayPaymentDispatchPilotPlansResponse | null>(null);
  const [
    razorpayPhase6FinalAuditLockReadiness,
    setRazorpayPhase6FinalAuditLockReadiness,
  ] = useState<SaasRazorpayPhase6FinalAuditLockReadiness | null>(null);
  const [
    razorpayPhase6FinalAuditLocks,
    setRazorpayPhase6FinalAuditLocks,
  ] = useState<SaasRazorpayPhase6FinalAuditLocksResponse | null>(null);
  const [
    razorpayControlledPilotGateReadiness,
    setRazorpayControlledPilotGateReadiness,
  ] = useState<SaasRazorpayControlledPilotGateReadiness | null>(null);
  const [
    razorpayControlledPilotGates,
    setRazorpayControlledPilotGates,
  ] = useState<SaasRazorpayControlledPilotGatesResponse | null>(null);
  const [
    razorpayControlledPilotExecutionReadiness,
    setRazorpayControlledPilotExecutionReadiness,
  ] = useState<SaasRazorpayControlledPilotExecutionReadiness | null>(null);
  const [
    razorpayControlledPilotExecutionAttempts,
    setRazorpayControlledPilotExecutionAttempts,
  ] = useState<SaasRazorpayControlledPilotExecutionAttemptsResponse | null>(
    null,
  );
  const [
    razorpayWhatsAppInternalNotificationReadiness,
    setRazorpayWhatsAppInternalNotificationReadiness,
  ] = useState<SaasRazorpayWhatsAppInternalNotificationReadiness | null>(
    null,
  );
  const [
    razorpayWhatsAppInternalNotificationGates,
    setRazorpayWhatsAppInternalNotificationGates,
  ] = useState<SaasRazorpayWhatsAppInternalNotificationGatesResponse | null>(
    null,
  );
  const [
    razorpayCourierReadiness,
    setRazorpayCourierReadiness,
  ] = useState<SaasRazorpayCourierReadiness | null>(null);
  const [
    razorpayCourierReadinessGates,
    setRazorpayCourierReadinessGates,
  ] = useState<SaasRazorpayCourierReadinessGatesResponse | null>(null);
  const [
    razorpayCourierExecutionReadiness,
    setRazorpayCourierExecutionReadiness,
  ] = useState<SaasRazorpayCourierExecutionReadiness | null>(null);
  const [
    razorpayCourierExecutionAttempts,
    setRazorpayCourierExecutionAttempts,
  ] = useState<SaasRazorpayCourierExecutionAttemptsResponse | null>(null);
  const [
    razorpayCourierExecutionEvidenceLockReadiness,
    setRazorpayCourierExecutionEvidenceLockReadiness,
  ] = useState<SaasRazorpayCourierExecutionEvidenceLockReadiness | null>(
    null,
  );
  const [
    razorpayCourierExecutionEvidenceLocks,
    setRazorpayCourierExecutionEvidenceLocks,
  ] = useState<SaasRazorpayCourierExecutionEvidenceLocksResponse | null>(
    null,
  );
  const [
    phase7eLiveInternalSendReadiness,
    setPhase7eLiveInternalSendReadiness,
  ] = useState<SaasPhase7ELiveInternalSendReadiness | null>(null);
  const [
    phase7eLiveInternalSendAttempts,
    setPhase7eLiveInternalSendAttempts,
  ] = useState<SaasPhase7ELiveInternalSendAttemptsResponse | null>(null);
  const [
    phase7eLiveBRealCustomerGates,
    setPhase7eLiveBRealCustomerGates,
  ] = useState<SaasPhase7ELiveBRealCustomerGatesResponse | null>(null);
  const [
    phase7gLiveRealCustomerDispatchGates,
    setPhase7gLiveRealCustomerDispatchGates,
  ] = useState<SaasPhase7GLiveRealCustomerDispatchGatesResponse | null>(null);
  const [
    customerSuccessCohorts,
    setCustomerSuccessCohorts,
  ] = useState<CustomerSuccessCohortsResponse | null>(null);
  const [
    rtoPreventionCohorts,
    setRtoPreventionCohorts,
  ] = useState<RtoPreventionCohortsResponse | null>(null);
  const [
    cfoLatest,
    setCfoLatest,
  ] = useState<CfoLatestResponse | null>(null);
  const [
    dataAnalystLatest,
    setDataAnalystLatest,
  ] = useState<DataAnalystLatestResponse | null>(null);
  const [
    callingTeamLeaderLatest,
    setCallingTeamLeaderLatest,
  ] = useState<CallingTeamLeaderLatestResponse | null>(null);
  const [
    ceoOrchestrationLatest,
    setCeoOrchestrationLatest,
  ] = useState<CeoOrchestrationLatestResponse | null>(null);
  // Phase 11C — CAIO Audit Agent (read-only).
  const [
    caioLatestSnapshot,
    setCaioLatestSnapshot,
  ] = useState<CaioAuditSnapshot | null>(null);
  // Phase 11D — Learning Loop Gate (read-only).
  const [
    learningProposals,
    setLearningProposals,
  ] = useState<LearningProposalsListResponse | null>(null);
  const [
    learningProposalSummary,
    setLearningProposalSummary,
  ] = useState<LearningProposalSummary | null>(null);
  const [
    phase7iFinalAuditLockReadiness,
    setPhase7iFinalAuditLockReadiness,
  ] = useState<SaasPhase7IFinalAuditLockReadiness | null>(null);
  const [
    phase7iFinalAuditLocks,
    setPhase7iFinalAuditLocks,
  ] = useState<SaasPhase7IFinalAuditLocksResponse | null>(null);
  const [
    phase8aPaymentOrderMutationSandboxReadiness,
    setPhase8aPaymentOrderMutationSandboxReadiness,
  ] = useState<SaasPhase8APaymentOrderMutationSandboxReadiness | null>(null);
  const [
    phase8aPaymentOrderMutationSandboxGates,
    setPhase8aPaymentOrderMutationSandboxGates,
  ] = useState<SaasPhase8APaymentOrderMutationSandboxGatesResponse | null>(null);
  const [
    phase8bPaymentOrderMutationReviewReadiness,
    setPhase8bPaymentOrderMutationReviewReadiness,
  ] = useState<SaasPhase8BPaymentOrderMutationReviewReadiness | null>(null);
  const [
    phase8bPaymentOrderMutationReviewGates,
    setPhase8bPaymentOrderMutationReviewGates,
  ] = useState<SaasPhase8BPaymentOrderMutationReviewGatesResponse | null>(null);
  const [
    phase8cPaymentOrderControlledMutationReadiness,
    setPhase8cPaymentOrderControlledMutationReadiness,
  ] = useState<SaasPhase8CPaymentOrderControlledMutationReadiness | null>(
    null,
  );
  const [
    phase8cPaymentOrderControlledMutationGates,
    setPhase8cPaymentOrderControlledMutationGates,
  ] = useState<SaasPhase8CPaymentOrderControlledMutationGatesResponse | null>(
    null,
  );
  const [
    phase8dControlledMutationEvidenceLockReadiness,
    setPhase8dControlledMutationEvidenceLockReadiness,
  ] = useState<SaasPhase8DControlledMutationEvidenceLockReadiness | null>(
    null,
  );
  const [
    phase8dControlledMutationEvidenceLocks,
    setPhase8dControlledMutationEvidenceLocks,
  ] = useState<SaasPhase8DControlledMutationEvidenceLocksResponse | null>(
    null,
  );
  const [
    phase8eRealCustomerPaymentOrderPilotReadiness,
    setPhase8eRealCustomerPaymentOrderPilotReadiness,
  ] = useState<SaasPhase8ERealCustomerPaymentOrderPilotReadiness | null>(
    null,
  );
  const [
    phase8eRealCustomerPaymentOrderPilotGates,
    setPhase8eRealCustomerPaymentOrderPilotGates,
  ] = useState<SaasPhase8ERealCustomerPaymentOrderPilotGatesResponse | null>(
    null,
  );
  const [
    phase8eRealCustomerCandidatePool,
    setPhase8eRealCustomerCandidatePool,
  ] = useState<SaasPhase8ERealCustomerCandidatePoolResponse | null>(null);
  const [
    phase8fRealCustomerControlledMutationReadiness,
    setPhase8fRealCustomerControlledMutationReadiness,
  ] = useState<SaasPhase8FRealCustomerControlledMutationReadiness | null>(
    null,
  );
  const [
    phase8fRealCustomerControlledMutationGates,
    setPhase8fRealCustomerControlledMutationGates,
  ] = useState<SaasPhase8FRealCustomerControlledMutationGatesResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getSaasAdminOverview(),
      api.getSaasRuntimeRoutingReadiness(),
      api.getSaasRuntimeDryRun(),
      api.getSaasAiProviderRouting(),
      api.getSaasRuntimeLiveGate(),
      api.getSaasRuntimeLiveGateSimulations(),
      api.getSaasProviderTestPlans(),
      api.getSaasProviderExecutionAttempts(),
      api.getSaasRazorpayWebhookReadiness(),
      api.getSaasRazorpayWebhookPlan(),
      api.getMcpReadiness(),
      api.getMcpSecurityPosture(),
      api.getMcpTools(),
      api.getMcpInvocations(25),
      api.getSaasRazorpayWebhookHandlerReadiness(),
      api.getSaasRazorpayWebhookEvents(25),
      api.getSaasRazorpayBusinessMutationSandboxPlan(),
      api.getSaasRazorpayBusinessMutationSandboxReadiness(),
      api.getSaasRazorpaySandboxStatusMappingReadiness(),
      api.getSaasRazorpaySandboxStatusReviews(25),
      api.getSaasRazorpaySandboxPaidStatusMutationReadiness(),
      api.getSaasRazorpaySandboxPaidStatusMutationAttempts(25),
      api.getSaasRazorpayPaymentOrderWorkflowGateReadiness(),
      api.getSaasRazorpayPaymentOrderWorkflowGates(25),
      api.getSaasRazorpayPaymentDispatchReadiness(),
      api.getSaasRazorpayPaymentDispatchReadinessGates(25),
      api.getSaasRazorpayPaymentDispatchPilotPlanReadiness(),
      api.getSaasRazorpayPaymentDispatchPilotPlans(25),
      api.getSaasRazorpayPhase6FinalAuditLockReadiness(),
      api.getSaasRazorpayPhase6FinalAuditLocks(25),
      api.getSaasRazorpayControlledPilotGateReadiness(),
      api.getSaasRazorpayControlledPilotGates(25),
      api.getSaasRazorpayControlledPilotExecutionReadiness(),
      api.getSaasRazorpayControlledPilotExecutionAttempts(25),
      api.getSaasRazorpayWhatsAppInternalNotificationReadiness(),
      api.getSaasRazorpayWhatsAppInternalNotificationGates(25),
      api.getSaasRazorpayCourierReadiness(),
      api.getSaasRazorpayCourierReadinessGates(25),
      api.getSaasRazorpayCourierExecutionReadiness(),
      api.getSaasRazorpayCourierExecutionAttempts(25),
      api.getSaasRazorpayCourierExecutionEvidenceLockReadiness(),
      api.getSaasRazorpayCourierExecutionEvidenceLocks(25),
      api.getSaasPhase7ELiveInternalSendReadiness(),
      api.getSaasPhase7ELiveInternalSendAttempts(25),
      api.getSaasPhase7ELiveBRealCustomerGates(25),
      api.getSaasPhase7GLiveRealCustomerDispatchGates(25),
      api.getCustomerSuccessCohorts(),
      api.getRtoPreventionCohorts(),
      api.getCfoLatest(),
      api.getDataAnalystLatest(),
      api.getCallingTeamLeaderLatest(),
      api.getCeoOrchestrationLatest(),
      api.getCaioLatestSnapshot(),
      api.getLearningProposals({ status: "pending", limit: 5 }),
      api.getLearningProposalSummary(),
      api.getSaasPhase7IFinalAuditLockReadiness(),
      api.getSaasPhase7IFinalAuditLocks(25),
      api.getSaasPhase8APaymentOrderMutationSandboxReadiness(),
      api.getSaasPhase8APaymentOrderMutationSandboxGates(25),
      api.getSaasPhase8BPaymentOrderMutationReviewReadiness(),
      api.getSaasPhase8BPaymentOrderMutationReviewGates(25),
      api.getSaasPhase8CPaymentOrderControlledMutationReadiness(),
      api.getSaasPhase8CPaymentOrderControlledMutationGates(25),
      api.getSaasPhase8DControlledMutationEvidenceLockReadiness(),
      api.getSaasPhase8DControlledMutationEvidenceLocks(25),
      api.getSaasPhase8ERealCustomerPaymentOrderPilotReadiness(),
      api.getSaasPhase8ERealCustomerPaymentOrderPilotGates(25),
      api.getSaasPhase8ERealCustomerCandidatePool(50, false),
      api.getSaasPhase8FRealCustomerControlledMutationReadiness(),
      api.getSaasPhase8FRealCustomerControlledMutationGates(25),
    ])
      .then(
        ([
          ov,
          rt,
          dr,
          ai,
          gate,
          sims,
          ptp,
          exec,
          wbr,
          wbp,
          mcpR,
          mcpSp,
          mcpT,
          mcpInv,
          hr,
          wbe,
          bmPlan,
          bmRead,
          smRead,
          smReviews,
          spsRead,
          spsAttempts,
          poRead,
          poGates,
          pdRead,
          pdGates,
          ppRead,
          ppPlans,
          p6tRead,
          p6tLocks,
          p7bRead,
          p7bGates,
          p7dRead,
          p7dAttempts,
          p7eRead,
          p7eGates,
          p7fRead,
          p7fGates,
          p7gRead,
          p7gAttempts,
          p7hRead,
          p7hLocks,
          p7eLiveRead,
          p7eLiveAttempts,
          p7eLiveBGates,
          p7gLiveGates,
          p9aCohorts,
          p9bCohorts,
          p9cLatest,
          p9dLatest,
          p9eLatest,
          p9fLatest,
          p11cCaio,
          p11dProposals,
          p11dSummary,
          p7iRead,
          p7iLocks,
          p8aRead,
          p8aGates,
          p8bRead,
          p8bGates,
          p8cRead,
          p8cGates,
          p8dRead,
          p8dLocks,
          p8eRead,
          p8eGates,
          p8ePool,
          p8fRead,
          p8fGates,
        ]) => {
          setOverview(ov);
          setRouting(rt);
          setDryRun(dr);
          setAiRouting(ai);
          setLiveGate(gate);
          setSimulations(sims);
          setProviderTestPlans(ptp);
          setProviderExecutionGate(exec);
          setRazorpayWebhookReadiness(wbr);
          setRazorpayWebhookPlan(wbp);
          setMcpReadiness(mcpR);
          setMcpSecurityPosture(mcpSp);
          setMcpTools(mcpT);
          setMcpInvocations(mcpInv);
          setRazorpayWebhookHandlerReadiness(hr);
          setRazorpayWebhookEvents(wbe);
          setRazorpayBusinessMutationSandboxPlan(bmPlan);
          setRazorpayBusinessMutationSandboxReadiness(bmRead);
          setRazorpaySandboxStatusMappingReadiness(smRead);
          setRazorpaySandboxStatusReviews(smReviews);
          setRazorpaySandboxPaidStatusReadiness(spsRead);
          setRazorpaySandboxPaidStatusAttempts(spsAttempts);
          setRazorpayPaymentOrderWorkflowReadiness(poRead);
          setRazorpayPaymentOrderWorkflowGates(poGates);
          setRazorpayPaymentDispatchReadiness(pdRead);
          setRazorpayPaymentDispatchReadinessGates(pdGates);
          setRazorpayPaymentDispatchPilotPlanReadiness(ppRead);
          setRazorpayPaymentDispatchPilotPlans(ppPlans);
          setRazorpayPhase6FinalAuditLockReadiness(p6tRead);
          setRazorpayPhase6FinalAuditLocks(p6tLocks);
          setRazorpayControlledPilotGateReadiness(p7bRead);
          setRazorpayControlledPilotGates(p7bGates);
          setRazorpayControlledPilotExecutionReadiness(p7dRead);
          setRazorpayControlledPilotExecutionAttempts(p7dAttempts);
          setRazorpayWhatsAppInternalNotificationReadiness(p7eRead);
          setRazorpayWhatsAppInternalNotificationGates(p7eGates);
          setRazorpayCourierReadiness(p7fRead);
          setRazorpayCourierReadinessGates(p7fGates);
          setRazorpayCourierExecutionReadiness(p7gRead);
          setRazorpayCourierExecutionAttempts(p7gAttempts);
          setRazorpayCourierExecutionEvidenceLockReadiness(p7hRead);
          setRazorpayCourierExecutionEvidenceLocks(p7hLocks);
          setPhase7eLiveInternalSendReadiness(p7eLiveRead);
          setPhase7eLiveInternalSendAttempts(p7eLiveAttempts);
          setPhase7eLiveBRealCustomerGates(p7eLiveBGates);
          setPhase7gLiveRealCustomerDispatchGates(p7gLiveGates);
          setCustomerSuccessCohorts(p9aCohorts);
          setRtoPreventionCohorts(p9bCohorts);
          setCfoLatest(p9cLatest);
          setDataAnalystLatest(p9dLatest);
          setCallingTeamLeaderLatest(p9eLatest);
          setCeoOrchestrationLatest(p9fLatest);
          setCaioLatestSnapshot(p11cCaio);
          setLearningProposals(p11dProposals);
          setLearningProposalSummary(p11dSummary);
          setPhase7iFinalAuditLockReadiness(p7iRead);
          setPhase7iFinalAuditLocks(p7iLocks);
          setPhase8aPaymentOrderMutationSandboxReadiness(p8aRead);
          setPhase8aPaymentOrderMutationSandboxGates(p8aGates);
          setPhase8bPaymentOrderMutationReviewReadiness(p8bRead);
          setPhase8bPaymentOrderMutationReviewGates(p8bGates);
          setPhase8cPaymentOrderControlledMutationReadiness(p8cRead);
          setPhase8cPaymentOrderControlledMutationGates(p8cGates);
          setPhase8dControlledMutationEvidenceLockReadiness(p8dRead);
          setPhase8dControlledMutationEvidenceLocks(p8dLocks);
          setPhase8eRealCustomerPaymentOrderPilotReadiness(p8eRead);
          setPhase8eRealCustomerPaymentOrderPilotGates(p8eGates);
          setPhase8eRealCustomerCandidatePool(p8ePool);
          setPhase8fRealCustomerControlledMutationReadiness(p8fRead);
          setPhase8fRealCustomerControlledMutationGates(p8fGates);
          // Auto-load the audit review for the latest succeeded
          // execution if present.
          const latestSucceeded = wbr?.latestSucceededExecutionId;
          if (latestSucceeded) {
            api
              .getSaasRazorpayExecutionAudit(latestSucceeded)
              .then(setRazorpayAuditReview)
              .catch(() => setRazorpayAuditReview(null));
          } else {
            setRazorpayAuditReview(null);
          }
        },
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  if (loading && overview === null) {
    return (
      <div className="grid h-96 place-items-center text-muted-foreground">
        Loading...
      </div>
    );
  }

  if (overview === null) {
    return (
      <div className="grid h-96 place-items-center text-muted-foreground">
        SaaS admin data unavailable.
      </div>
    );
  }

  const org = overview.organization;
  const writeReadiness = overview.writePathReadiness;
  const orgReadiness = overview.orgScopeReadiness;

  return (
    <>
      <PageHeader
        eyebrow="SaaS Control"
        title="SaaS Admin Panel"
        description="Read-only organization scope, write-path, integration readiness, and safety-lock visibility for the current single-tenant deployment."
        actions={
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-4">
        <MetricCard
          icon={Building2}
          label="Active org"
          value={org?.code ?? "missing"}
          detail={org?.name ?? "Default organization not found"}
        />
        <MetricCard
          icon={ShieldCheck}
          label="Org coverage"
          value={`${orgReadiness.organizationCoveragePercent.toFixed(2)}%`}
          detail={`Branch ${orgReadiness.branchCoveragePercent.toFixed(2)}%`}
        />
        <MetricCard
          icon={Workflow}
          label="Write enforcement"
          value={writeReadiness.enforcementMode ?? "advisory"}
          detail={`${writeReadiness.recentRowsWithoutOrganizationLast24h} recent unscoped writes`}
        />
        <MetricCard
          icon={KeyRound}
          label="Integration settings"
          value={String(overview.integrationSettingsCount)}
          detail="Runtime still uses env/config"
        />
      </div>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Panel title="Organization Overview" icon={Building2}>
          <KeyValue label="Organization" value={org?.name ?? "Missing"} />
          <KeyValue label="Code" value={org?.code ?? "missing"} />
          <KeyValue
            label="Default branch"
            value={org?.defaultBranch?.name ?? "Missing"}
          />
          <KeyValue
            label="Memberships"
            value={String(org?.membershipSummary.active ?? 0)}
          />
          <StatusPill tone={toneForStatus(org?.status ?? "missing")}>
            {org?.status ?? "missing"}
          </StatusPill>
        </Panel>

        <Panel title="Org Scope Readiness" icon={ShieldCheck}>
          <KeyValue
            label="Global tenant filtering"
            value={String(orgReadiness.globalTenantFilteringEnabled)}
          />
          <KeyValue
            label="Scoped models"
            value={String(orgReadiness.scopedModels.length)}
          />
          <KeyValue
            label="Unscoped APIs"
            value={String(orgReadiness.unscopedApis.length)}
          />
          <StatusPill
            tone={boolTone(orgReadiness.safeToStartPhase6D)}
          >
            {orgReadiness.safeToStartPhase6D
              ? "Ready"
              : "Needs attention"}
          </StatusPill>
        </Panel>
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Panel title="Write Path Readiness" icon={Workflow}>
          <div className="grid gap-3 sm:grid-cols-3">
            <KeyValue
              label="Covered paths"
              value={String(
                writeReadiness.coveredSafeCreatePaths?.length ??
                  writeReadiness.safeCreatePathsCovered.length,
              )}
            />
            <KeyValue
              label="Deferred paths"
              value={String(writeReadiness.deferredCreatePaths.length)}
            />
            <KeyValue
              label="Recent unscoped"
              value={String(
                writeReadiness.recentUnscopedWritesLast24h ??
                  writeReadiness.recentRowsWithoutOrganizationLast24h,
              )}
            />
          </div>
          <div className="mt-4 rounded-md border border-border bg-muted/20 p-3 text-sm">
            <div className="text-xs uppercase text-muted-foreground">
              Next action
            </div>
            <div className="mt-1 font-medium">{writeReadiness.nextAction}</div>
          </div>
          <IssueList items={writeReadiness.blockers} empty="No blockers" />
        </Panel>

        <Panel title="Safety Locks" icon={LockKeyhole}>
          <LockRow
            label="WhatsApp auto-reply"
            safe={!overview.safetyLocks.whatsappAutoReplyEnabled}
          />
          <LockRow label="Campaigns" safe={overview.safetyLocks.campaignsLocked} />
          <LockRow label="Broadcast" safe={overview.safetyLocks.broadcastLocked} />
          <LockRow
            label="Lifecycle automation"
            safe={!overview.safetyLocks.lifecycleAutomationEnabled}
          />
          <LockRow
            label="Call handoff"
            safe={!overview.safetyLocks.callHandoffEnabled}
          />
          <LockRow
            label="Rescue / RTO / reorder"
            safe={
              !overview.safetyLocks.rescueDiscountEnabled &&
              !overview.safetyLocks.rtoRescueEnabled &&
              !overview.safetyLocks.reorderDay20Enabled
            }
          />
        </Panel>
      </section>

      <section className="mt-6 surface-card overflow-hidden">
        <div className="border-b border-border px-6 py-4">
          <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
            <SlidersHorizontal className="h-5 w-5 text-primary" />
            Integration Readiness
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
              <tr>
                <th className="px-6 py-3 text-left font-medium">Provider</th>
                <th className="py-3 text-left font-medium">Status</th>
                <th className="py-3 text-left font-medium">Secret refs</th>
                <th className="py-3 text-left font-medium">Validation</th>
                <th className="px-6 py-3 text-left font-medium">Runtime</th>
              </tr>
            </thead>
            <tbody>
              {overview.integrationReadiness.providers.map((provider) => (
                <ProviderRow key={provider.providerType} provider={provider} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {routing && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="runtime-routing-preview"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <SlidersHorizontal className="h-5 w-5 text-primary" />
                Runtime Integration Routing Preview
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6F preview only. Per-org runtime routing is not
                active — runtime still uses env/config. Secret refs are
                checked for presence only; raw values are never exposed.
              </p>
            </div>
            <StatusPill
              tone={routing.global.safeToStartPhase6G ? "success" : "warning"}
            >
              {routing.global.safeToStartPhase6G
                ? "Phase 6G ready"
                : "Phase 6G blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-3">
            <KeyValue
              label="Runtime source"
              value="Env/config (active)"
            />
            <KeyValue
              label="Per-org runtime enabled"
              value="false (Phase 6F)"
            />
            <KeyValue
              label="Next action"
              value={routing.nextAction}
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">
                    Provider
                  </th>
                  <th className="py-3 text-left font-medium">Setting</th>
                  <th className="py-3 text-left font-medium">Status</th>
                  <th className="py-3 text-left font-medium">
                    Secret refs
                  </th>
                  <th className="py-3 text-left font-medium">
                    Resolvable
                  </th>
                  <th className="px-6 py-3 text-left font-medium">
                    Runtime source
                  </th>
                </tr>
              </thead>
              <tbody>
                {routing.providers.map((provider) => (
                  <RuntimeProviderRow
                    key={provider.providerType}
                    provider={provider}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Per-org runtime routing is not active. Runtime still uses
            env/config.
          </div>
        </section>
      )}

      {dryRun && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="runtime-dry-run-preview"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <PlayCircle className="h-5 w-5 text-primary" />
                Controlled Runtime Routing Dry Run
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6G preview only. No external provider calls, no
                customer-facing side effects. Runtime stays on env/config
                — per-org runtime routing is not active.
              </p>
            </div>
            <StatusPill
              tone={dryRun.global.safeToStartPhase6H ? "success" : "warning"}
            >
              {dryRun.global.safeToStartPhase6H
                ? "Phase 6H ready"
                : "Phase 6H blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue label="Operations" value={String(dryRun.operations.length)} />
            <KeyValue
              label="Live execution"
              value="false (Phase 6G)"
            />
            <KeyValue label="External call" value="false" />
            <KeyValue label="Next action" value={dryRun.nextAction} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">
                    Operation
                  </th>
                  <th className="py-3 text-left font-medium">Provider</th>
                  <th className="py-3 text-left font-medium">Risk</th>
                  <th className="py-3 text-left font-medium">Setting</th>
                  <th className="py-3 text-left font-medium">Dry-run</th>
                  <th className="py-3 text-left font-medium">Live</th>
                  <th className="px-6 py-3 text-left font-medium">
                    Next action
                  </th>
                </tr>
              </thead>
              <tbody>
                {dryRun.operations.map((op) => (
                  <RuntimeOperationRow
                    key={op.operationType}
                    decision={op}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Phase 6G is preview only. PayU + Delhivery are deferred until
            credentials are provisioned. Vapi awaits phone_number_id +
            webhook_secret.
          </div>
        </section>
      )}

      {aiRouting && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="ai-provider-routing"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Cpu className="h-5 w-5 text-primary" />
                AI Provider Routing Preview
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                NVIDIA primary models with OpenAI / Anthropic fallback.
                Customer-facing drafts must still pass Claim Vault, safety
                stack, and approval matrix before any future live send.
              </p>
            </div>
            <StatusPill tone={aiRouting.safeToStartAiDryRun ? "success" : "warning"}>
              {aiRouting.runtime.runtimeMode === "preview"
                ? "Preview mode"
                : aiRouting.runtime.runtimeMode}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue
              label="Primary"
              value={aiRouting.runtime.primaryProvider}
            />
            <KeyValue
              label="Fallback"
              value={aiRouting.runtime.fallbackProvider}
            />
            <KeyValue
              label="NVIDIA key"
              value={
                aiRouting.runtime.envKeyPresence?.NVIDIA_API_KEY
                  ? "present"
                  : "missing"
              }
            />
            <KeyValue
              label="OpenAI fallback"
              value={
                aiRouting.runtime.envKeyPresence?.OPENAI_API_KEY
                  ? "present"
                  : "missing"
              }
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">Task</th>
                  <th className="py-3 text-left font-medium">Primary</th>
                  <th className="py-3 text-left font-medium">Fallback</th>
                  <th className="py-3 text-left font-medium">Max tokens</th>
                  <th className="py-3 text-left font-medium">Safety</th>
                  <th className="px-6 py-3 text-left font-medium">
                    Next action
                  </th>
                </tr>
              </thead>
              <tbody>
                {aiRouting.tasks.map((task) => (
                  <AiTaskRow key={task.taskType} task={task} />
                ))}
              </tbody>
            </table>
          </div>
          {aiRouting.blockers.length > 0 && (
            <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
              {aiRouting.blockers.join(" · ")}
            </div>
          )}
        </section>
      )}

      {liveGate && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="runtime-live-gate"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldAlert className="h-5 w-5 text-primary" />
                Controlled Runtime Live Audit Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Approving in Phase 6H does not execute external calls. The
                gate records readiness, approvals, blockers, and kill-switch
                state before any future provider-side execution.
              </p>
            </div>
            <StatusPill
              tone={liveGate.killSwitch.globalEnabled ? "success" : "warning"}
            >
              Global kill switch {liveGate.killSwitch.globalEnabled ? "enabled" : "disabled"}
            </StatusPill>
          </div>

          <div className="grid gap-3 px-6 py-4 sm:grid-cols-5">
            <KeyValue label="Runtime source" value={liveGate.runtimeSource} />
            <KeyValue
              label="Per-org runtime"
              value={String(liveGate.perOrgRuntimeEnabled)}
            />
            <KeyValue
              label="Default dry-run"
              value={String(liveGate.defaultDryRun)}
            />
            <KeyValue
              label="Live execution"
              value={String(liveGate.liveExecutionAllowed)}
            />
            <KeyValue
              label="External calls"
              value={String(liveGate.externalCallWillBeMade)}
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">Operation</th>
                  <th className="py-3 text-left font-medium">Provider</th>
                  <th className="py-3 text-left font-medium">Risk</th>
                  <th className="py-3 text-left font-medium">Approval</th>
                  <th className="py-3 text-left font-medium">CAIO</th>
                  <th className="py-3 text-left font-medium">Consent</th>
                  <th className="py-3 text-left font-medium">Claim Vault</th>
                  <th className="py-3 text-left font-medium">Webhook</th>
                  <th className="py-3 text-left font-medium">Decision</th>
                  <th className="px-6 py-3 text-left font-medium">Live now</th>
                </tr>
              </thead>
              <tbody>
                {liveGate.operationPolicies.map((policy) => (
                  <LiveGatePolicyRow
                    key={policy.operationType}
                    policy={policy}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-4 border-t border-border px-6 py-4 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="space-y-3">
              <h4 className="flex items-center gap-2 font-display text-base font-semibold">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                Approval Queue
              </h4>
              <KeyValue
                label="Pending"
                value={String(liveGate.approvalQueue.approvalPendingCount)}
              />
              <KeyValue
                label="Approved but not executed"
                value={String(liveGate.approvalQueue.approvedButNotExecutedCount)}
              />
              <KeyValue
                label="Rejected"
                value={String(liveGate.approvalQueue.rejectedCount)}
              />
              <KeyValue
                label="Blocked"
                value={String(liveGate.approvalQueue.blockedCount)}
              />
            </div>

            <div className="space-y-3">
              <h4 className="flex items-center gap-2 font-display text-base font-semibold">
                <ShieldCheck className="h-4 w-4 text-primary" />
                Recent Gate Audit Events
              </h4>
              {liveGate.recentGateAuditEvents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No live gate audit events yet.
                </p>
              ) : (
                liveGate.recentGateAuditEvents.map((event) => (
                  <div
                    key={event.id}
                    className="rounded-md border border-border bg-muted/20 p-3"
                  >
                    <div className="text-sm font-medium">
                      {event.kind} - {event.operationType || "runtime"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {event.gateDecision || "recorded"} -{" "}
                      {new Date(event.createdAt).toLocaleString()}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="border-t border-border bg-warning/5 px-6 py-4">
            <div className="flex items-center gap-2 text-sm font-medium text-warning">
              <AlertTriangle className="h-4 w-4" />
              Phase 6H warnings
            </div>
            <IssueList items={liveGate.warnings} empty="No warnings" />
          </div>
        </section>
      )}

      {simulations && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="single-internal-live-gate-simulation"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Single Internal Live Gate Simulation
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6I prepares, approves, runs, and rolls back an
                internal-only simulation. It does not call WhatsApp,
                Razorpay, PayU, Delhivery, Vapi, NVIDIA, or OpenAI
                side-effect endpoints.
              </p>
            </div>
            <StatusPill tone={simulations.killSwitchActive ? "success" : "danger"}>
              Kill switch {simulations.killSwitchActive ? "active" : "inactive"}
            </StatusPill>
          </div>

          <div className="grid gap-3 px-6 py-4 sm:grid-cols-5">
            <KeyValue
              label="Default operation"
              value={simulations.defaultOperation}
            />
            <KeyValue label="Dry-run" value={String(simulations.dryRun)} />
            <KeyValue
              label="Live allowed"
              value={String(simulations.liveExecutionAllowed)}
            />
            <KeyValue
              label="External call"
              value={String(simulations.externalCallWillBeMade)}
            />
            <KeyValue
              label="Provider attempted"
              value={String(simulations.providerCallAttempted)}
            />
          </div>

          <div className="grid gap-4 border-t border-border px-6 py-4 lg:grid-cols-[0.8fr_1.2fr]">
            <div className="space-y-3">
              <h4 className="flex items-center gap-2 font-display text-base font-semibold">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                Simulation Controls State
              </h4>
              <KeyValue
                label="Allowed operations"
                value={String(simulations.allowedOperations.length)}
              />
              <KeyValue
                label="Simulations"
                value={String(simulations.count)}
              />
              <KeyValue
                label="External call made"
                value={String(simulations.externalCallWasMade)}
              />
              <KeyValue
                label="Next action"
                value={simulations.summary?.nextAction ?? "prepare_simulation"}
              />
              <div className="rounded-md border border-border bg-warning/5 p-3 text-xs text-muted-foreground">
                Approving or running a Phase 6I simulation does not execute
                external calls.
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                  <tr>
                    <th className="px-6 py-3 text-left font-medium">
                      Operation
                    </th>
                    <th className="py-3 text-left font-medium">Provider</th>
                    <th className="py-3 text-left font-medium">Status</th>
                    <th className="py-3 text-left font-medium">Approval</th>
                    <th className="py-3 text-left font-medium">Decision</th>
                    <th className="px-6 py-3 text-left font-medium">
                      Provider call
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {simulations.simulations.map((simulation) => (
                    <LiveGateSimulationRow
                      key={simulation.id}
                      simulation={simulation}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Allowed operations: {simulations.allowedOperations.join(", ")}.
            Global kill switch remains active; all execution flags remain
            false.
          </div>
        </section>
      )}

      {providerTestPlans && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="provider-test-plan-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ClipboardList className="h-5 w-5 text-primary" />
                Single Internal Provider Test Plan
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6J planning only. Razorpay test-mode create_order
                is the implementation target. No external provider call
                is made in Phase 6J. Approval here unlocks the future
                Phase 6K execution gate, NOT execution itself.
              </p>
            </div>
            <StatusPill
              tone={
                providerTestPlans.safeToStartPhase6K ? "success" : "warning"
              }
            >
              {providerTestPlans.safeToStartPhase6K
                ? "Phase 6K ready"
                : "Phase 6K blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue
              label="Latest plan"
              value={
                providerTestPlans.latestPlan?.planId ?? "no plan yet"
              }
            />
            <KeyValue label="Provider" value="Razorpay" />
            <KeyValue label="Operation" value="razorpay.create_order" />
            <KeyValue
              label="Environment"
              value={
                providerTestPlans.latestPlan?.providerEnvironment ?? "test"
              }
            />
          </div>
          <div className="grid gap-4 px-6 pb-4 lg:grid-cols-2">
            <ProviderTestPlanInvariants plan={providerTestPlans.latestPlan} />
            <ProviderTestPlanEnvReadiness
              plan={providerTestPlans.latestPlan}
            />
          </div>
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Execute Razorpay" / "Create
            Order" / "Create Payment Link" buttons exist on this page.
            Approval only marks the plan as ready for the future Phase
            6K execution gate.
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Next action:{" "}
            <span className="font-medium">
              {providerTestPlans.nextAction}
            </span>
          </div>
        </section>
      )}

      {providerExecutionGate && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="provider-execution-gate-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <CreditCard className="h-5 w-5 text-primary" />
                Single Internal Razorpay Test-Mode Execution Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6K. Razorpay test-mode <code>create_order</code>{" "}
                only — synthetic ₹1.00 (100 paise) payload, no
                customer data, no payment link, no capture, no business
                mutation. Actual provider call is{" "}
                <strong>CLI-only</strong> via{" "}
                <code>manage.py execute_single_razorpay_test_order</code>{" "}
                with the <code>--confirm-test-execution</code> flag.
              </p>
            </div>
            <StatusPill
              tone={
                providerExecutionGate.safeToRunPhase6KExecution
                  ? "success"
                  : "warning"
              }
            >
              {providerExecutionGate.safeToRunPhase6KExecution
                ? "Ready (CLI only)"
                : "Gate blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue
              label="Approved plan"
              value={
                providerExecutionGate.latestApprovedPlan?.planId ??
                "no approved plan"
              }
            />
            <KeyValue
              label="Successful executions"
              value={String(providerExecutionGate.successfulExecutionCount)}
            />
            <KeyValue
              label="Provider calls attempted"
              value={String(providerExecutionGate.providerCallAttemptedCount)}
            />
            <KeyValue
              label="Business mutations"
              value={String(providerExecutionGate.businessMutationCount)}
            />
          </div>
          <div className="grid gap-4 px-6 pb-4 lg:grid-cols-2">
            <ProviderExecutionEnvCard
              env={providerExecutionGate.envReadiness}
            />
            <ProviderExecutionInvariants
              attempt={providerExecutionGate.latestAttempt}
            />
          </div>
          <ProviderExecutionAttemptsTable
            attempts={providerExecutionGate.attempts}
          />
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Execute Razorpay" / "Create
            Order" / "Create Payment Link" buttons exist on this page.
            Phase 6K provider execution is exclusively triggered by
            the CLI command after every gate is satisfied.
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Next action:{" "}
            <span className="font-medium">
              {providerExecutionGate.nextAction}
            </span>
          </div>
        </section>
      )}

      {(razorpayAuditReview || razorpayWebhookReadiness || razorpayWebhookPlan) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-audit-webhook-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <FileSearch className="h-5 w-5 text-primary" />
                Razorpay Test Execution Audit + Webhook Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6L — read-only review of the Phase 6K Razorpay
                test-mode execution audit trail + the planning policy
                for the future Razorpay webhook receiver. No new
                Razorpay calls. No payment / order status mutation.
              </p>
            </div>
            {razorpayAuditReview && (
              <StatusPill
                tone={razorpayAuditReview.passed ? "success" : "warning"}
              >
                {razorpayAuditReview.passed
                  ? "Audit PASS"
                  : "Audit FAIL"}
              </StatusPill>
            )}
          </div>
          {razorpayAuditReview && (
            <RazorpayAuditReviewCard review={razorpayAuditReview} />
          )}
          {razorpayWebhookReadiness && (
            <RazorpayWebhookReadinessCard
              readiness={razorpayWebhookReadiness}
            />
          )}
          {razorpayWebhookPlan && (
            <RazorpayWebhookPlanCard plan={razorpayWebhookPlan} />
          )}
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> Phase 6L never registers a
            webhook receiver, never calls Razorpay, never mutates a
            business row, never exposes raw secrets. Webhook handler
            ships in Phase 6M.
          </div>
        </section>
      )}

      {(razorpayWebhookHandlerReadiness || razorpayWebhookEvents) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-webhook-handler-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Webhook Handler (Test Mode)
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6M — receives, verifies, dedupes, and audits
                Razorpay test-mode webhook events. <strong>No business
                mutation</strong> in this phase. No customer
                notification. No raw payload / signature / secret in the
                UI. Phase 6N will own business-mutation sandbox.
              </p>
            </div>
            {razorpayWebhookHandlerReadiness && (
              <StatusPill
                tone={
                  razorpayWebhookHandlerReadiness.safeToReceiveTestWebhooks
                    ? "success"
                    : "warning"
                }
              >
                {razorpayWebhookHandlerReadiness.webhookTestModeEnabled
                  ? "Receiver enabled"
                  : "Receiver disabled (safe)"}
              </StatusPill>
            )}
          </div>
          {razorpayWebhookHandlerReadiness && (
            <RazorpayWebhookHandlerReadinessCard
              readiness={razorpayWebhookHandlerReadiness}
            />
          )}
          {razorpayWebhookEvents && (
            <RazorpayWebhookEventsTable response={razorpayWebhookEvents} />
          )}
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Capture Payment" / "Send
            WhatsApp" / "Mark Order Paid" / "Replay Event" buttons
            exist on this page. Even the simulator runs through the
            same Phase 6M handler — synthetic payload only, no
            external Razorpay call.
          </div>
        </section>
      )}

      {(razorpayBusinessMutationSandboxPlan ||
        razorpayBusinessMutationSandboxReadiness) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-business-mutation-sandbox-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Business Mutation Sandbox Plan
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6N — planning + readiness layer only.{" "}
                <strong>No business mutation</strong>, no customer
                notification, no Razorpay API call, no env-flag flip.
                Phase 6O will own any sandbox-only mutation against
                synthetic test orders, behind a new env flag, gated by
                Director sign-off.
              </p>
            </div>
            {razorpayBusinessMutationSandboxReadiness && (
              <div data-testid="phase6n-safe-to-start-phase6o-badge">
                <StatusPill
                  tone={
                    razorpayBusinessMutationSandboxReadiness.safeToStartPhase6O
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayBusinessMutationSandboxReadiness.safeToStartPhase6O
                    ? "Ready for Phase 6O planning"
                    : "Blocked — fix Phase 6M state first"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayBusinessMutationSandboxReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayBusinessMutationSandboxReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayBusinessMutationSandboxReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayBusinessMutationSandboxReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpayBusinessMutationSandboxReadiness.nextPhase}
              />
              <KeyValue label="Business mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Raw payload storage" value="Disabled" />
              <KeyValue
                label="Phase 6M flags locked off"
                value={
                  razorpayBusinessMutationSandboxReadiness.phase6MFlagsLockedOff
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Safety counters zero"
                value={
                  razorpayBusinessMutationSandboxReadiness.safetyCountersZero
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Plan complete"
                value={
                  razorpayBusinessMutationSandboxReadiness.planComplete
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Event mappings"
                value={String(
                  razorpayBusinessMutationSandboxReadiness.eventMappingCount,
                )}
              />
              <KeyValue
                label="Manual review items"
                value={String(
                  razorpayBusinessMutationSandboxReadiness.manualReviewChecklistSize,
                )}
              />
            </div>
          )}

          {razorpayBusinessMutationSandboxReadiness && (
            <div className="px-6 pb-3 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayBusinessMutationSandboxReadiness.nextAction}
            </div>
          )}

          {razorpayBusinessMutationSandboxPlan && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Event-to-status mapping (Phase 6O target)
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6n-event-mapping-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Future sandbox payment</th>
                      <th className="py-1 pr-3">Future order effect</th>
                      <th className="py-1 pr-3">Mutation in 6N</th>
                      <th className="py-1 pr-3">Manual review</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Shipment</th>
                      <th className="py-1 pr-3">Discount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayBusinessMutationSandboxPlan.eventMappings.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxPaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxOrderEffect}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">
                            {row.manualReviewRequired ? "Required" : "—"}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayBusinessMutationSandboxPlan && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-3">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Synthetic-order eligibility
                </h4>
                <ul className="text-xs space-y-1 list-disc pl-5">
                  {Object.entries(
                    razorpayBusinessMutationSandboxPlan.syntheticEligibilityPolicy,
                  )
                    .filter(([, value]) => value === true)
                    .slice(0, 12)
                    .map(([key]) => (
                      <li key={key} className="text-muted-foreground">
                        {key}
                      </li>
                    ))}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Manual review checklist
                </h4>
                <ul
                  className="text-xs space-y-1 list-disc pl-5"
                  data-testid="phase6n-manual-review-list"
                >
                  {razorpayBusinessMutationSandboxPlan.manualReviewChecklist.map(
                    (entry) => (
                      <li key={entry.key} className="text-muted-foreground">
                        <strong>{entry.key}</strong> — {entry.description}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Rollback plan</h4>
                <ol
                  className="text-xs space-y-1 list-decimal pl-5"
                  data-testid="phase6n-rollback-list"
                >
                  {razorpayBusinessMutationSandboxPlan.rollbackPlan.rollbackSteps.map(
                    (step) => (
                      <li key={step.order} className="text-muted-foreground">
                        {step.action}
                      </li>
                    ),
                  )}
                </ol>
                <p className="text-[11px] text-muted-foreground mt-2">
                  Rollback owned by operator; Phase 6N never executes
                  rollback automatically.
                </p>
              </div>
            </div>
          )}

          {razorpayBusinessMutationSandboxPlan && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
              <div
                className="flex flex-wrap gap-1 text-[11px]"
                data-testid="phase6n-forbidden-actions"
              >
                {razorpayBusinessMutationSandboxPlan.forbiddenActions.map(
                  (action) => (
                    <span
                      key={action}
                      className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                    >
                      {action}
                    </span>
                  ),
                )}
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Mark Paid" / "Capture
            Payment" / "Refund" / "Send WhatsApp" / "Create Payment
            Link" / "Mutate Order" / "Execute Webhook" / "Replay
            Event" / "Enable Mutation" / "Go Live" / "Run MCP Tool"
            buttons exist on this page. Phase 6N is planning only;
            Phase 6P remains future.
          </div>
        </section>
      )}

      {(razorpaySandboxStatusMappingReadiness || razorpaySandboxStatusReviews) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-sandbox-status-mapping-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Sandbox Status Mapping + Manual Review
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6O — sandbox-review-only.{" "}
                <strong>No business mutation</strong>, no customer
                notification, no Razorpay API call. Approving a review
                here only marks it{" "}
                <code>approved_for_future_phase6p</code> — Phase 6P
                will own any sandbox-only mutation against synthetic
                test orders, gated by Director sign-off.
              </p>
            </div>
            {razorpaySandboxStatusMappingReadiness && (
              <div data-testid="phase6o-safe-to-start-phase6p-badge">
                <StatusPill
                  tone={
                    razorpaySandboxStatusMappingReadiness.safeToStartPhase6P
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpaySandboxStatusMappingReadiness.safeToStartPhase6P
                    ? "Ready for Phase 6P planning"
                    : "Blocked — needs approved review for future Phase 6P"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpaySandboxStatusMappingReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpaySandboxStatusMappingReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpaySandboxStatusMappingReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpaySandboxStatusMappingReadiness.nextPhase}
              />
              <KeyValue
                label="Sandbox flag"
                value={
                  razorpaySandboxStatusMappingReadiness.razorpaySandboxStatusMappingEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Business mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Reviews pending"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Reviews approved (for 6P)"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts
                    .approvedForFuturePhase6P,
                )}
              />
              <KeyValue
                label="Reviews rejected"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts.rejected,
                )}
              />
              <KeyValue
                label="Reviews archived"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts.archived,
                )}
              />
            </div>
          )}

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 pb-2 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpaySandboxStatusMappingReadiness.nextAction}
            </div>
          )}

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Event-to-status mapping (Phase 6P target)
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6o-event-mapping-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Future sandbox payment</th>
                      <th className="py-1 pr-3">Future order effect</th>
                      <th className="py-1 pr-3">Mutation in 6O</th>
                      <th className="py-1 pr-3">Manual review</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Shipment</th>
                      <th className="py-1 pr-3">Discount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpaySandboxStatusMappingReadiness.eventMappings.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxPaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxOrderEffect}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">
                            {row.manualReviewRequired ? "Required" : "—"}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpaySandboxStatusReviews && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Sandbox status reviews ({razorpaySandboxStatusReviews.items.length})
              </h4>
              {razorpaySandboxStatusReviews.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No reviews prepared yet. Reviews are created via the
                  backend CLI / API only — there is no "Apply Mutation"
                  path in Phase 6O.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-xs"
                    data-testid="phase6o-reviews-table"
                  >
                    <thead className="text-muted-foreground">
                      <tr className="text-left">
                        <th className="py-1 pr-3">ID</th>
                        <th className="py-1 pr-3">Event</th>
                        <th className="py-1 pr-3">Source event id</th>
                        <th className="py-1 pr-3">Proposed payment</th>
                        <th className="py-1 pr-3">Proposed order effect</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1 pr-3">Mutation in 6O</th>
                        <th className="py-1 pr-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpaySandboxStatusReviews.items.map((row) => (
                        <Phase6OReviewRow
                          key={row.id}
                          row={row}
                          pending={phase6oActionPending === row.id}
                          onAction={async (action, reason) => {
                            setPhase6oActionPending(row.id);
                            setPhase6oActionMessage("");
                            try {
                              const fn =
                                action === "approve"
                                  ? api.approveSaasRazorpaySandboxStatusReview
                                  : action === "reject"
                                  ? api.rejectSaasRazorpaySandboxStatusReview
                                  : api.archiveSaasRazorpaySandboxStatusReview;
                              const result = await fn(row.id, reason);
                              if (result.ok) {
                                setPhase6oActionMessage(
                                  `Review ${row.id} ${action}d (review-only). Next: ${result.nextAction}`,
                                );
                                load();
                              } else {
                                setPhase6oActionMessage(
                                  `Action blocked: ${result.blockers.join(", ") || "see backend logs"}`,
                                );
                              }
                            } finally {
                              setPhase6oActionPending(null);
                            }
                          }}
                        />
                      ))}
                    </tbody>
                  </table>
                  {phase6oActionMessage && (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      {phase6oActionMessage}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Manual review checklist
                </h4>
                <ul
                  className="text-xs space-y-1 list-disc pl-5"
                  data-testid="phase6o-manual-review-list"
                >
                  {razorpaySandboxStatusMappingReadiness.manualReviewChecklist.map(
                    (entry) => (
                      <li key={entry.key} className="text-muted-foreground">
                        <strong>{entry.key}</strong> — {entry.description}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
                <div
                  className="flex flex-wrap gap-1 text-[11px]"
                  data-testid="phase6o-forbidden-actions"
                >
                  {razorpaySandboxStatusMappingReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Sandbox review only.</strong> The "Approve Review
            Only" / "Reject Review" / "Archive Review" buttons above
            change the review row's status only — they NEVER mark an
            Order paid, NEVER capture a Payment, NEVER create a
            Shipment, NEVER send a customer notification. No "Apply
            Mutation" / "Mark Paid" / "Execute Payment" / "Capture" /
            "Refund" / "Send WhatsApp" / "Run MCP Tool" buttons exist
            on this page. Phase 6P will own any sandbox-only mutation
            against synthetic test orders, behind a NEW env flag
            distinct from <code>RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED</code>.
          </div>
        </section>
      )}

      {(razorpaySandboxPaidStatusReadiness || razorpaySandboxPaidStatusAttempts) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-sandbox-paid-status-mutation-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Sandbox Paid-Status Mutation Test
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6P — sandbox-ledger-only.{" "}
                <strong>No real Order / Payment / Shipment / DiscountOfferLog mutation</strong>,
                no customer notification, no Razorpay API call.
                Execution is exclusively via CLI — no API endpoint and
                no frontend button can dispatch a Phase 6P mutation.
              </p>
            </div>
            {razorpaySandboxPaidStatusReadiness && (
              <div data-testid="phase6p-safe-to-start-phase6q-badge">
                <StatusPill
                  tone={
                    razorpaySandboxPaidStatusReadiness.safeToStartPhase6Q
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpaySandboxPaidStatusReadiness.safeToStartPhase6Q
                    ? "Ready for Phase 6Q planning"
                    : "Blocked — run a CLI execute + rollback first"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpaySandboxPaidStatusReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpaySandboxPaidStatusReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpaySandboxPaidStatusReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpaySandboxPaidStatusReadiness.nextPhase}
              />
              <KeyValue
                label="Sandbox flag"
                value={
                  razorpaySandboxPaidStatusReadiness.razorpaySandboxPaidStatusMutationEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Real Order mutation" value="Disabled" />
              <KeyValue label="Real Payment mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpaySandboxPaidStatusReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API endpoint can execute"
                value={
                  razorpaySandboxPaidStatusReadiness.apiEndpointCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={razorpaySandboxPaidStatusReadiness.executionPath}
              />
              <KeyValue
                label="Approved Phase 6O reviews"
                value={String(
                  razorpaySandboxPaidStatusReadiness.approvedPhase6OReviewCount,
                )}
              />
              <KeyValue
                label="Attempts ever executed"
                value={String(
                  razorpaySandboxPaidStatusReadiness.attemptCounts.everExecuted,
                )}
              />
              <KeyValue
                label="Attempts ever rolled back"
                value={String(
                  razorpaySandboxPaidStatusReadiness.attemptCounts.everRolledBack,
                )}
              />
              <KeyValue
                label="Ledger rows"
                value={String(
                  razorpaySandboxPaidStatusReadiness.ledgerCounts.totalLedgers,
                )}
              />
            </div>
          )}

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 pb-2 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpaySandboxPaidStatusReadiness.nextAction}
            </div>
          )}

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Sandbox event-to-ledger mapping
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6p-event-mapping-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Sandbox payment status</th>
                      <th className="py-1 pr-3">Sandbox order effect</th>
                      <th className="py-1 pr-3">Real Order mutation</th>
                      <th className="py-1 pr-3">Real Payment mutation</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Provider</th>
                      <th className="py-1 pr-3">Path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpaySandboxPaidStatusReadiness.eventMappings.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.sandboxPaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.sandboxOrderEffect}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 font-mono text-[11px]">
                            {row.executionPath}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpaySandboxPaidStatusAttempts && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Sandbox mutation attempts
                ({razorpaySandboxPaidStatusAttempts.items.length})
              </h4>
              {razorpaySandboxPaidStatusAttempts.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No attempts yet. Attempts are created and executed
                  exclusively via the Phase 6P CLI commands —{" "}
                  <code>prepare_razorpay_sandbox_paid_status_mutation</code>,{" "}
                  <code>execute_razorpay_sandbox_paid_status_mutation</code>,{" "}
                  <code>rollback_razorpay_sandbox_paid_status_mutation</code>.
                  This page renders read-only status only.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-xs"
                    data-testid="phase6p-attempts-table"
                  >
                    <thead className="text-muted-foreground">
                      <tr className="text-left">
                        <th className="py-1 pr-3">ID</th>
                        <th className="py-1 pr-3">Event</th>
                        <th className="py-1 pr-3">Source event id</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1 pr-3">Action</th>
                        <th className="py-1 pr-3">Real mutation</th>
                        <th className="py-1 pr-3">Notification</th>
                        <th className="py-1 pr-3">Executed at</th>
                        <th className="py-1 pr-3">Rolled back at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpaySandboxPaidStatusAttempts.items.map((row) => (
                        <tr
                          key={row.id}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3">{row.id}</td>
                          <td className="py-1 pr-3 font-mono">
                            {row.eventName}
                          </td>
                          <td className="py-1 pr-3 font-mono">
                            {row.sourceEventId}
                          </td>
                          <td className="py-1 pr-3">
                            <StatusPill
                              tone={
                                row.status === "executed"
                                  ? "success"
                                  : row.status === "rolled_back"
                                  ? "info"
                                  : row.status === "failed" ||
                                    row.status === "blocked"
                                  ? "danger"
                                  : row.status === "archived"
                                  ? "neutral"
                                  : "warning"
                              }
                            >
                              {row.status}
                            </StatusPill>
                          </td>
                          <td className="py-1 pr-3 font-mono text-[11px]">
                            {row.requestedAction}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">{row.executedAt ?? "—"}</td>
                          <td className="py-1 pr-3">
                            {row.rolledBackAt ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">CLI-only execution</h4>
                <p className="text-xs text-muted-foreground">
                  Phase 6P mutation paths are intentionally CLI-only.
                  Approving / rejecting in this UI never touches a real
                  business row. Use the operator runbook for the four
                  Phase 6P CLIs:
                </p>
                <ul
                  className="mt-2 text-[11px] font-mono space-y-1 list-disc pl-5"
                  data-testid="phase6p-cli-list"
                >
                  <li>preview_razorpay_sandbox_paid_status_mutation</li>
                  <li>prepare_razorpay_sandbox_paid_status_mutation</li>
                  <li>
                    execute_razorpay_sandbox_paid_status_mutation
                    --confirm-sandbox-paid-status-mutation --director-signoff
                    "..."
                  </li>
                  <li>
                    rollback_razorpay_sandbox_paid_status_mutation
                    --confirm-sandbox-rollback --reason "..."
                  </li>
                  <li>archive_razorpay_sandbox_paid_status_mutation_attempt</li>
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
                <div
                  className="flex flex-wrap gap-1 text-[11px]"
                  data-testid="phase6p-forbidden-actions"
                >
                  {razorpaySandboxPaidStatusReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Sandbox ledger only.</strong> No "Mark Paid" /
            "Capture Payment" / "Refund" / "Apply Payment" / "Apply
            Mutation" / "Mutate Order" / "Send WhatsApp" / "Create
            Payment Link" / "Execute Webhook" / "Replay Event" /
            "Enable Mutation" / "Go Live" / "Run MCP Tool" buttons exist
            on this page. Execution is exclusively via the Phase 6P CLI
            commands above; this page renders status only.
          </div>
        </section>
      )}

      {(razorpayPaymentOrderWorkflowReadiness || razorpayPaymentOrderWorkflowGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-payment-order-workflow-gate-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Payment → Order Workflow Safety Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6Q — audit-only safety gate.{" "}
                <strong>No real Order / Payment / Shipment / DiscountOfferLog mutation</strong>,
                no customer notification, no Razorpay API call.
                Approving a gate only marks it{" "}
                <code>approved_for_future_phase6r</code> — gate state
                changes are CLI-only; no API endpoint or frontend
                button dispatches Phase 6Q approval.
              </p>
            </div>
            {razorpayPaymentOrderWorkflowReadiness && (
              <div data-testid="phase6q-safe-to-start-phase6r-badge">
                <StatusPill
                  tone={
                    razorpayPaymentOrderWorkflowReadiness.safeToStartPhase6R
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPaymentOrderWorkflowReadiness.safeToStartPhase6R
                    ? "Ready for Phase 6R planning"
                    : "Blocked — needs approved gate review for future Phase 6R"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayPaymentOrderWorkflowReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayPaymentOrderWorkflowReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpayPaymentOrderWorkflowReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpayPaymentOrderWorkflowReadiness.nextPhase}
              />
              <KeyValue
                label="Gate flag"
                value={
                  razorpayPaymentOrderWorkflowReadiness.razorpayPaymentOrderWorkflowGateEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Real Order mutation" value="Disabled" />
              <KeyValue label="Real Payment mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpayPaymentOrderWorkflowReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API can approve"
                value={
                  razorpayPaymentOrderWorkflowReadiness.apiEndpointCanApprove
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={razorpayPaymentOrderWorkflowReadiness.executionPath}
              />
              <KeyValue
                label="Phase 6P executed"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.phase6PExecutedCount,
                )}
              />
              <KeyValue
                label="Phase 6P rolled back"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.phase6PRolledBackCount,
                )}
              />
              <KeyValue
                label="Gates pending"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.gateCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Gates approved (for 6R)"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.gateCounts
                    .approvedForFuturePhase6R,
                )}
              />
            </div>
          )}

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 pb-2 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayPaymentOrderWorkflowReadiness.nextAction}
            </div>
          )}

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Payment → Order workflow contract (Phase 6R target)
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6q-contract-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Future payment</th>
                      <th className="py-1 pr-3">Future order status</th>
                      <th className="py-1 pr-3">Workflow action</th>
                      <th className="py-1 pr-3">Mutation in 6Q</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Provider</th>
                      <th className="py-1 pr-3">Shipment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayPaymentOrderWorkflowReadiness.workflowContract.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futurePaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureOrderStatusCandidate}
                          </td>
                          <td className="py-1 pr-3 font-mono text-[11px]">
                            {row.workflowAction}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayPaymentOrderWorkflowGates && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Workflow gate review records (
                {razorpayPaymentOrderWorkflowGates.items.length})
              </h4>
              {razorpayPaymentOrderWorkflowGates.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No gate reviews yet. Gate reviews are prepared,
                  approved, rejected, and archived exclusively via
                  the Phase 6Q CLI commands —{" "}
                  <code>prepare_razorpay_payment_order_workflow_gate</code>,{" "}
                  <code>approve_razorpay_payment_order_workflow_gate</code>,{" "}
                  <code>reject_razorpay_payment_order_workflow_gate</code>,{" "}
                  <code>archive_razorpay_payment_order_workflow_gate</code>.
                  This page renders read-only status only.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-xs"
                    data-testid="phase6q-gates-table"
                  >
                    <thead className="text-muted-foreground">
                      <tr className="text-left">
                        <th className="py-1 pr-3">ID</th>
                        <th className="py-1 pr-3">Event</th>
                        <th className="py-1 pr-3">Source event id</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1 pr-3">Real mutation</th>
                        <th className="py-1 pr-3">Notification</th>
                        <th className="py-1 pr-3">Reviewed at</th>
                        <th className="py-1 pr-3">Archived at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPaymentOrderWorkflowGates.items.map((row) => (
                        <tr
                          key={row.id}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3">{row.id}</td>
                          <td className="py-1 pr-3 font-mono">
                            {row.eventName}
                          </td>
                          <td className="py-1 pr-3 font-mono">
                            {row.sourceEventId}
                          </td>
                          <td className="py-1 pr-3">
                            <StatusPill
                              tone={
                                row.status === "approved_for_future_phase6r"
                                  ? "success"
                                  : row.status === "rejected" ||
                                    row.status === "blocked"
                                  ? "danger"
                                  : row.status === "archived"
                                  ? "neutral"
                                  : "warning"
                              }
                            >
                              {row.status}
                            </StatusPill>
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">
                            {row.reviewedAt ?? "—"}
                          </td>
                          <td className="py-1 pr-3">
                            {row.archivedAt ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">CLI-only review</h4>
                <p className="text-xs text-muted-foreground">
                  Phase 6Q gate state changes are intentionally
                  CLI-only. Approving / rejecting / archiving in this
                  UI is not exposed. Use the operator runbook for the
                  Phase 6Q CLIs:
                </p>
                <ul
                  className="mt-2 text-[11px] font-mono space-y-1 list-disc pl-5"
                  data-testid="phase6q-cli-list"
                >
                  <li>preview_razorpay_payment_order_workflow_gate</li>
                  <li>prepare_razorpay_payment_order_workflow_gate</li>
                  <li>
                    approve_razorpay_payment_order_workflow_gate --reason "..."
                  </li>
                  <li>
                    reject_razorpay_payment_order_workflow_gate --reason "..."
                  </li>
                  <li>
                    archive_razorpay_payment_order_workflow_gate --reason "..."
                  </li>
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
                <div
                  className="flex flex-wrap gap-1 text-[11px]"
                  data-testid="phase6q-forbidden-actions"
                >
                  {razorpayPaymentOrderWorkflowReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Audit gate only.</strong> No "Mark Paid" /
            "Capture Payment" / "Refund" / "Apply Payment" / "Apply
            Mutation" / "Mutate Order" / "Send WhatsApp" / "Create
            Payment Link" / "Execute Webhook" / "Replay Event" /
            "Enable Mutation" / "Go Live" / "Run MCP Tool" / "Execute
            Workflow" / "Apply Order Update" / "Confirm Paid Order" /
            "Start Live Workflow" buttons exist on this page. Gate
            review state changes are exclusively via the Phase 6Q CLI
            commands above.
          </div>
        </section>
      )}

      {(razorpayPaymentDispatchReadiness ||
        razorpayPaymentDispatchReadinessGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-payment-dispatch-readiness-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Payment → WhatsApp / Courier Dispatch Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6R — readiness contract only.{" "}
                <strong>
                  No WhatsApp send, no Meta Cloud call, no Delhivery call,
                  no shipment / AWB creation, no real Order / Payment /
                  Customer / Lead mutation, no Razorpay API call
                </strong>
                . Approving a readiness gate only marks it{" "}
                <code>approved_for_future_phase6s</code> — review state
                changes are CLI-only; no API endpoint or frontend button
                dispatches Phase 6R approval.
              </p>
            </div>
            {razorpayPaymentDispatchReadiness && (
              <div data-testid="phase6r-safe-to-start-phase6s-badge">
                <StatusPill
                  tone={
                    razorpayPaymentDispatchReadiness.safeToStartPhase6S
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPaymentDispatchReadiness.safeToStartPhase6S
                    ? "Ready for Phase 6S planning"
                    : "Blocked — needs approved readiness review for future Phase 6S"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayPaymentDispatchReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayPaymentDispatchReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpayPaymentDispatchReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpayPaymentDispatchReadiness.nextPhase}
              />
              <KeyValue
                label="Readiness flag"
                value={
                  razorpayPaymentDispatchReadiness.razorpayPaymentDispatchReadinessEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="WhatsApp send" value="Disabled" />
              <KeyValue label="Meta Cloud call" value="Disabled" />
              <KeyValue label="Delhivery call" value="Disabled" />
              <KeyValue label="Shipment creation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpayPaymentDispatchReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API can approve"
                value={
                  razorpayPaymentDispatchReadiness.apiEndpointCanApprove
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={razorpayPaymentDispatchReadiness.executionPath}
              />
              <KeyValue
                label="Phase 6Q approved gates"
                value={String(
                  razorpayPaymentDispatchReadiness.phase6QApprovedGateCount,
                )}
              />
              <KeyValue
                label="Pending readiness reviews"
                value={String(
                  razorpayPaymentDispatchReadiness.readinessCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Approved for future 6S"
                value={String(
                  razorpayPaymentDispatchReadiness.readinessCounts
                    .approvedForFuturePhase6S,
                )}
              />
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayPaymentDispatchReadiness.nextAction}
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Readiness contract (9 events)
              </h4>
              <div className="overflow-x-auto rounded border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40">
                    <tr className="text-left">
                      <th className="px-3 py-2">Event</th>
                      <th className="px-3 py-2">WhatsApp readiness</th>
                      <th className="px-3 py-2">Courier readiness</th>
                      <th className="px-3 py-2">Dispatch readiness</th>
                      <th className="px-3 py-2">Send allowed in 6R</th>
                      <th className="px-3 py-2">Courier in 6R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayPaymentDispatchReadiness.readinessContract.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="px-3 py-2 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureWhatsAppReadinessAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureCourierReadinessAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureDispatchReadinessAction}
                          </td>
                          <td className="px-3 py-2">No</td>
                          <td className="px-3 py-2">No</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchReadinessGates && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Recent readiness gates ({" "}
                {razorpayPaymentDispatchReadinessGates.items.length})
              </h4>
              {razorpayPaymentDispatchReadinessGates.items.length === 0 ? (
                <div className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
                  No readiness gates recorded yet. Run the Phase 6R CLI
                  commands —{" "}
                  <code>
                    inspect_razorpay_payment_dispatch_readiness
                  </code>
                  ,{" "}
                  <code>
                    prepare_razorpay_payment_dispatch_readiness_gate
                  </code>
                  ,{" "}
                  <code>
                    approve_razorpay_payment_dispatch_readiness_gate
                  </code>
                  ,{" "}
                  <code>
                    reject_razorpay_payment_dispatch_readiness_gate
                  </code>
                  .
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">WhatsApp action</th>
                        <th className="px-3 py-2">Courier action</th>
                        <th className="px-3 py-2">Dispatch action</th>
                        <th className="px-3 py-2">Sent / Queued / Shipped</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPaymentDispatchReadinessGates.items.map(
                        (row) => (
                          <tr
                            key={row.id}
                            className="border-t border-border"
                          >
                            <td className="px-3 py-2 font-mono">{row.id}</td>
                            <td className="px-3 py-2 font-mono">
                              {row.eventName}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.status}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedWhatsAppAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedCourierAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedDispatchReadinessAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.whatsAppMessageCreated ? "S" : "-"}
                              {row.whatsAppMessageQueued ? "Q" : "-"}
                              {row.shipmentCreated ? "X" : "-"}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4 grid gap-3 lg:grid-cols-3">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  WhatsApp readiness checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchReadiness.whatsAppReadinessChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Courier readiness checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchReadiness.courierReadinessChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Dispatch readiness checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchReadiness.dispatchReadinessChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4">
              <details className="text-xs">
                <summary className="cursor-pointer font-semibold">
                  Phase 6R forbidden actions ({" "}
                  {razorpayPaymentDispatchReadiness.forbiddenActions.length}
                  )
                </summary>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {razorpayPaymentDispatchReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </details>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Readiness contract only.</strong> No "Send WhatsApp"
            / "Queue WhatsApp" / "Create Shipment" / "Create AWB" /
            "Book Courier" / "Dispatch Order" / "Notify Customer" /
            "Mark Paid" / "Capture Payment" / "Refund" / "Apply
            Mutation" / "Mutate Order" / "Create Payment Link" /
            "Execute Webhook" / "Replay Event" / "Enable Mutation" /
            "Go Live" / "Run MCP Tool" / "Execute Workflow" / "Apply
            Order Update" / "Confirm Paid Order" / "Start Live
            Workflow" buttons exist on this page. Readiness review
            state changes are exclusively via the Phase 6R CLI commands
            above.
          </div>
        </section>
      )}

      {(razorpayPaymentDispatchPilotPlanReadiness ||
        razorpayPaymentDispatchPilotPlans) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-payment-dispatch-pilot-plan-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Limited Internal Dispatch Pilot Plan
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6S — pilot planning only.{" "}
                <strong>
                  No pilot execution, no WhatsApp send, no Meta Cloud
                  call, no Delhivery call, no shipment / AWB creation,
                  no real Order / Payment / Customer / Lead mutation,
                  no Razorpay API call
                </strong>
                . Approving a pilot plan only marks it{" "}
                <code>approved_for_future_phase6t</code> — review state
                changes are CLI-only; no API endpoint or frontend button
                dispatches Phase 6S approval.
              </p>
            </div>
            {razorpayPaymentDispatchPilotPlanReadiness && (
              <div data-testid="phase6s-safe-to-start-phase6t-badge">
                <StatusPill
                  tone={
                    razorpayPaymentDispatchPilotPlanReadiness.safeToStartPhase6T
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPaymentDispatchPilotPlanReadiness.safeToStartPhase6T
                    ? "Ready for Phase 6T planning"
                    : "Blocked — needs approved pilot plan for future Phase 6T"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayPaymentDispatchPilotPlanReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayPaymentDispatchPilotPlanReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpayPaymentDispatchPilotPlanReadiness.nextPhase}
              />
              <KeyValue
                label="Pilot plan flag"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.razorpayPaymentDispatchPilotPlanEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Pilot execution" value="Disabled" />
              <KeyValue label="WhatsApp send" value="Disabled" />
              <KeyValue label="WhatsApp queue" value="Disabled" />
              <KeyValue label="Meta Cloud call" value="Disabled" />
              <KeyValue label="Delhivery call" value="Disabled" />
              <KeyValue label="Shipment created" value="Disabled" />
              <KeyValue label="AWB created" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API can approve"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.apiEndpointCanApprove
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.executionPath
                }
              />
              <KeyValue
                label="Phase 6R approved gates"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.phase6RApprovedReadinessGateCount,
                )}
              />
              <KeyValue
                label="Pending pilot plans"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.pilotPlanCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Approved for future 6T"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.pilotPlanCounts
                    .approvedForFuturePhase6T,
                )}
              />
              <KeyValue
                label="Max pilot orders"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.maxPilotOrders,
                )}
              />
              <KeyValue
                label="Max amount (paise)"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.maxSafeAmountPaise,
                )}
              />
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayPaymentDispatchPilotPlanReadiness.nextAction}
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div
              className="px-6 pb-4"
              data-testid="phase6s-pilot-contract-table"
            >
              <h4 className="text-sm font-semibold mb-2">
                Limited internal pilot contract (9 events)
              </h4>
              <div className="overflow-x-auto rounded border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40">
                    <tr className="text-left">
                      <th className="px-3 py-2">Event</th>
                      <th className="px-3 py-2">Pilot eligibility</th>
                      <th className="px-3 py-2">WhatsApp pilot action</th>
                      <th className="px-3 py-2">Courier pilot action</th>
                      <th className="px-3 py-2">Dispatch pilot action</th>
                      <th className="px-3 py-2">Pilot in 6S</th>
                      <th className="px-3 py-2">Send in 6S</th>
                      <th className="px-3 py-2">Courier in 6S</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayPaymentDispatchPilotPlanReadiness.pilotContract.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="px-3 py-2 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futurePilotEligibility}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureWhatsAppPilotAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureCourierPilotAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureDispatchPilotAction}
                          </td>
                          <td className="px-3 py-2">No</td>
                          <td className="px-3 py-2">No</td>
                          <td className="px-3 py-2">No</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchPilotPlans && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Recent pilot plans (
                {razorpayPaymentDispatchPilotPlans.items.length})
              </h4>
              {razorpayPaymentDispatchPilotPlans.items.length === 0 ? (
                <div className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
                  No pilot plans recorded yet. Run the Phase 6S CLI
                  commands —{" "}
                  <code>
                    inspect_razorpay_payment_dispatch_pilot_plan_readiness
                  </code>
                  ,{" "}
                  <code>
                    prepare_razorpay_payment_dispatch_pilot_plan
                  </code>
                  ,{" "}
                  <code>
                    approve_razorpay_payment_dispatch_pilot_plan
                  </code>
                  ,{" "}
                  <code>
                    reject_razorpay_payment_dispatch_pilot_plan
                  </code>
                  .
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">Pilot mode</th>
                        <th className="px-3 py-2">WhatsApp action</th>
                        <th className="px-3 py-2">Courier action</th>
                        <th className="px-3 py-2">Dispatch action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPaymentDispatchPilotPlans.items.map(
                        (row) => (
                          <tr
                            key={row.id}
                            className="border-t border-border"
                          >
                            <td className="px-3 py-2 font-mono">
                              {row.id}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.eventName}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.status}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.pilotMode}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedWhatsAppAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedCourierAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedDispatchAction}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Internal staff cohort checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.internalStaffCohortChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  WhatsApp pilot checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.whatsAppPilotChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Courier pilot checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.courierPilotChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Dispatch pilot checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.dispatchPilotChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Abort criteria
                </h4>
                <ul className="space-y-1 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.abortCriteria.map(
                    (item) => (
                      <li
                        key={item}
                        className="font-mono rounded border border-border bg-muted/20 px-2 py-1"
                      >
                        {item}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Verification checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.verificationChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4">
              <details className="text-xs">
                <summary
                  className="cursor-pointer font-semibold"
                  data-testid="phase6s-forbidden-actions"
                >
                  Phase 6S forbidden actions ({" "}
                  {
                    razorpayPaymentDispatchPilotPlanReadiness.forbiddenActions
                      .length
                  }
                  )
                </summary>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {razorpayPaymentDispatchPilotPlanReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </details>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Pilot plan only.</strong> No "Start Pilot" / "Run
            Pilot" / "Execute Pilot" / "Start Live Workflow" / "Send
            WhatsApp" / "Queue WhatsApp" / "Notify Customer" / "Create
            Shipment" / "Create AWB" / "Book Courier" / "Dispatch
            Order" / "Call Delhivery" / "Call Meta" / "Mark Paid" /
            "Capture Payment" / "Refund" / "Create Payment Link" /
            "Mutate Order" / "Apply Payment" / "Apply Mutation" /
            "Replay Event" / "Enable Mutation" / "Go Live" / "Run MCP
            Tool" buttons exist on this page. Pilot plan review state
            changes are exclusively via the Phase 6S CLI commands
            above.
          </div>
        </section>
      )}

      {(razorpayPhase6FinalAuditLockReadiness ||
        razorpayPhase6FinalAuditLocks) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-phase6-final-audit-lock-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Razorpay Phase 6 Final Audit + Lock
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6T - <strong>Final Audit Only</strong>. The view
                composes Phase 6N through Phase 6S into an audit-chain
                attestation and future controlled pilot contract. Review
                state changes are CLI-only; this page is read-only.
              </p>
            </div>
            {razorpayPhase6FinalAuditLockReadiness && (
              <div data-testid="phase6t-safe-to-start-future-controlled-pilot-badge">
                <StatusPill
                  tone={
                    razorpayPhase6FinalAuditLockReadiness.safeToStartFutureControlledPilot
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPhase6FinalAuditLockReadiness.safeToStartFutureControlledPilot
                    ? "Decision gate reviewable"
                    : "Decision gate blocked"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPhase6FinalAuditLockReadiness && (
            <>
              <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <KeyValue
                  label="Phase"
                  value={razorpayPhase6FinalAuditLockReadiness.phase}
                />
                <KeyValue
                  label="Status"
                  value={razorpayPhase6FinalAuditLockReadiness.status}
                />
                <KeyValue
                  label="Latest completed"
                  value={
                    razorpayPhase6FinalAuditLockReadiness.latestCompletedPreviousPhase
                  }
                />
                <KeyValue
                  label="Next phase"
                  value={razorpayPhase6FinalAuditLockReadiness.nextPhase}
                />
                <KeyValue
                  label="Audit-lock flag"
                  value={
                    razorpayPhase6FinalAuditLockReadiness.razorpayPhase6FinalAuditLockEnabled
                      ? "Enabled"
                      : "Disabled"
                  }
                />
                <KeyValue label="Future controlled pilot by 6T" value="No" />
                <KeyValue label="Pilot execution" value="No" />
                <KeyValue label="Real business mutation" value="No" />
                <KeyValue label="Real Order mutation" value="No" />
                <KeyValue label="Real Payment mutation" value="No" />
                <KeyValue label="WhatsApp send" value="No" />
                <KeyValue label="WhatsApp queued" value="No" />
                <KeyValue label="Meta Cloud call" value="No" />
                <KeyValue label="Delhivery call" value="No" />
                <KeyValue label="Razorpay call" value="No" />
                <KeyValue label="Shipment created" value="No" />
                <KeyValue label="AWB created" value="No" />
                <KeyValue label="Customer notification" value="No" />
                <KeyValue label="Provider call" value="No" />
                <KeyValue
                  label="Locked records"
                  value={String(
                    razorpayPhase6FinalAuditLockReadiness.finalAuditLockCounts
                      .lockedForFutureControlledPilotReview,
                  )}
                />
              </div>

              <div className="px-6 pb-4 text-xs text-muted-foreground">
                <strong>Next action:</strong>{" "}
                {razorpayPhase6FinalAuditLockReadiness.nextAction}
              </div>

              <div
                className="px-6 pb-4"
                data-testid="phase6t-audit-chain-table"
              >
                <h4 className="text-sm font-semibold mb-2">
                  Audit chain attestation
                </h4>
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">Phase</th>
                        <th className="px-3 py-2">Required status</th>
                        <th className="px-3 py-2">Actual status</th>
                        <th className="px-3 py-2">Verified</th>
                        <th className="px-3 py-2">Mutation</th>
                        <th className="px-3 py-2">Provider</th>
                        <th className="px-3 py-2">Notification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPhase6FinalAuditLockReadiness.auditChain.map(
                        (row) => (
                          <tr key={row.phase} className="border-t border-border">
                            <td className="px-3 py-2 font-mono">
                              Phase {row.phase}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.requiredStatus}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.actualStatus}
                            </td>
                            <td className="px-3 py-2">
                              {row.verified ? "Yes" : "No"}
                            </td>
                            <td className="px-3 py-2">No</td>
                            <td className="px-3 py-2">No</td>
                            <td className="px-3 py-2">No</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2">
                <ContractList
                  title="Director signoff contract"
                  data={razorpayPhase6FinalAuditLockReadiness.directorSignoffContract}
                  testId="phase6t-director-signoff-contract"
                />
                <ContractList
                  title="Kill-switch contract"
                  data={razorpayPhase6FinalAuditLockReadiness.killSwitchContract}
                  testId="phase6t-kill-switch-contract"
                />
                <ContractList
                  title="Rollback contract"
                  data={razorpayPhase6FinalAuditLockReadiness.rollbackContract}
                  testId="phase6t-rollback-contract"
                />
                <ContractList
                  title="Safety invariants"
                  data={razorpayPhase6FinalAuditLockReadiness.safetyInvariants}
                  testId="phase6t-safety-invariants"
                />
              </div>

              <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2">
                <div data-testid="phase6t-abort-criteria">
                  <h4 className="text-sm font-semibold mb-2">
                    Abort criteria
                  </h4>
                  <ul className="space-y-1 text-xs">
                    {razorpayPhase6FinalAuditLockReadiness.abortCriteria.map(
                      (item) => (
                        <li
                          key={`${item.if}-${item.then}`}
                          className="font-mono rounded border border-border bg-muted/20 px-2 py-1"
                        >
                          {item.if} - {item.then}
                        </li>
                      ),
                    )}
                  </ul>
                </div>
                <div data-testid="phase6t-operator-checklist">
                  <h4 className="text-sm font-semibold mb-2">
                    Operator checklist
                  </h4>
                  <ul className="space-y-1 text-xs">
                    {razorpayPhase6FinalAuditLockReadiness.operatorChecklist.map(
                      (item) => (
                        <li
                          key={`${item.step}-${item.surface}`}
                          className="font-mono rounded border border-border bg-muted/20 px-2 py-1"
                        >
                          {item.step} - {item.surface}
                        </li>
                      ),
                    )}
                  </ul>
                </div>
              </div>
            </>
          )}

          {razorpayPhase6FinalAuditLocks && (
            <div
              className="px-6 pb-4"
              data-testid="phase6t-lock-records-table"
            >
              <h4 className="text-sm font-semibold mb-2">
                Final audit lock records (
                {razorpayPhase6FinalAuditLocks.items.length})
              </h4>
              {razorpayPhase6FinalAuditLocks.items.length === 0 ? (
                <div className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
                  No final audit lock records yet. Use the Phase 6T CLI
                  review commands after an eligible Phase 6S plan exists.
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">Chain</th>
                        <th className="px-3 py-2">Provider</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPhase6FinalAuditLocks.items.map((row) => (
                        <tr key={row.id} className="border-t border-border">
                          <td className="px-3 py-2 font-mono">{row.id}</td>
                          <td className="px-3 py-2 font-mono">
                            {row.eventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.status}
                          </td>
                          <td className="px-3 py-2">
                            {row.fullChainVerified ? "Verified" : "Pending"}
                          </td>
                          <td className="px-3 py-2">No call</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase6t-cli-only-reminder"
          >
            <strong>CLI-only review.</strong> Inspect Final Audit, Lock
            Audit Record Only, Decision Gate Only, Future Controlled
            Pilot Contract, Audit Chain Attestation, No Live Execution,
            No Provider Call.
          </div>
        </section>
      )}

      {(razorpayControlledPilotGateReadiness ||
        razorpayControlledPilotGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-controlled-pilot-execution-gate-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Razorpay Controlled Pilot Execution Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7B - <strong>Gate Only</strong>. Approving a gate
                only marks it{" "}
                <code>approved_for_future_phase7c_execution_review</code>{" "}
                - it does <strong>not</strong> execute a pilot, send
                WhatsApp, call Razorpay / Meta Cloud / Delhivery, create
                a shipment / AWB, or mutate any real business row.
                Review state changes are CLI-only; this page is
                read-only. Phase 7C / live execution is{" "}
                <strong>not approved</strong>.
              </p>
            </div>
            {razorpayControlledPilotGateReadiness && (
              <div data-testid="phase7b-safe-to-start-phase7c-review-badge">
                <StatusPill
                  tone={
                    razorpayControlledPilotGateReadiness.safeToStartPhase7CExecutionReviewFlow
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayControlledPilotGateReadiness.safeToStartPhase7CExecutionReviewFlow
                    ? "Future Phase 7C review reachable"
                    : "Future Phase 7C review blocked"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayControlledPilotGateReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayControlledPilotGateReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayControlledPilotGateReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayControlledPilotGateReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpayControlledPilotGateReadiness.nextPhase}
              />
              <KeyValue
                label="Phase 7B gate flag"
                value={
                  razorpayControlledPilotGateReadiness.phase7ControlledPilotGateEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Pilot execution in 7B" value="No" />
              <KeyValue label="Live execution in 7B" value="No" />
              <KeyValue label="Provider call in 7B" value="No" />
              <KeyValue label="Business mutation in 7B" value="No" />
              <KeyValue label="WhatsApp send in 7B" value="No" />
              <KeyValue label="WhatsApp queue in 7B" value="No" />
              <KeyValue label="Meta Cloud call in 7B" value="No" />
              <KeyValue label="Delhivery call in 7B" value="No" />
              <KeyValue label="Razorpay call in 7B" value="No" />
              <KeyValue label="Shipment creation in 7B" value="No" />
              <KeyValue label="AWB creation in 7B" value="No" />
              <KeyValue label="Customer notification in 7B" value="No" />
              <KeyValue
                label="Razorpay key validation in 7B"
                value="No (deferred to Phase 7C+)"
              />
              <KeyValue label="Frontend can execute" value="No" />
              <KeyValue label="API can execute" value="No" />
              <KeyValue
                label="Phase 6T locks for 7B review"
                value={String(
                  razorpayControlledPilotGateReadiness.phase6TLockedForFutureControlledPilotReviewCount,
                )}
              />
              <KeyValue
                label="Pending review gates"
                value={String(
                  razorpayControlledPilotGateReadiness.controlledPilotGateCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Approved for future 7C"
                value={String(
                  razorpayControlledPilotGateReadiness.controlledPilotGateCounts
                    .approvedForFuturePhase7CExecutionReview,
                )}
              />
              <KeyValue
                label="Max pilot orders"
                value={String(
                  razorpayControlledPilotGateReadiness.maxPilotOrders,
                )}
              />
              <KeyValue
                label="Max amount (paise)"
                value={String(
                  razorpayControlledPilotGateReadiness.maxSafeAmountPaise,
                )}
              />
            </div>
          )}

          {razorpayControlledPilotGateReadiness && (
            <div className="px-6 pb-4 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayControlledPilotGateReadiness.nextAction}
            </div>
          )}

          {razorpayControlledPilotGateReadiness && (
            <div
              className="px-6 pb-4"
              data-testid="phase7b-env-posture"
            >
              <h4 className="text-sm font-semibold mb-2">
                Environment posture
              </h4>
              <p className="text-xs text-muted-foreground">
                {razorpayControlledPilotGateReadiness.envPosture}
              </p>
            </div>
          )}

          {razorpayControlledPilotGates && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Recent controlled pilot gates ({" "}
                {razorpayControlledPilotGates.items.length})
              </h4>
              {razorpayControlledPilotGates.items.length === 0 ? (
                <div
                  className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground"
                  data-testid="phase7b-cli-only-reminder"
                >
                  No gates recorded yet. Run the Phase 7B CLI commands -{" "}
                  <code>
                    inspect_razorpay_controlled_pilot_gate_readiness
                  </code>
                  ,{" "}
                  <code>preview_razorpay_controlled_pilot_gate</code>,{" "}
                  <code>prepare_razorpay_controlled_pilot_gate</code>,{" "}
                  <code>dry_run_razorpay_controlled_pilot_gate</code>,{" "}
                  <code>
                    rollback_dry_run_razorpay_controlled_pilot_gate
                  </code>
                  ,{" "}
                  <code>approve_razorpay_controlled_pilot_gate</code>,{" "}
                  <code>reject_razorpay_controlled_pilot_gate</code>,{" "}
                  <code>archive_razorpay_controlled_pilot_gate</code>,{" "}
                  <code>inspect_razorpay_controlled_pilot_gates</code>.
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table
                    className="w-full text-xs"
                    data-testid="phase7b-gates-table"
                  >
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Lock ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">Dry-run</th>
                        <th className="px-3 py-2">Rollback dry-run</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayControlledPilotGates.items.map((row) => (
                        <tr
                          key={row.id}
                          className="border-t border-border"
                        >
                          <td className="px-3 py-2 font-mono">{row.id}</td>
                          <td className="px-3 py-2 font-mono">
                            {row.sourceFinalAuditLockId ?? "-"}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.eventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.status}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.dryRunPassed ? "passed" : "pending"}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.rollbackDryRunPassed
                              ? "passed"
                              : "pending"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayControlledPilotGateReadiness && (
            <div className="px-6 pb-4">
              <details className="text-xs">
                <summary
                  className="cursor-pointer font-semibold"
                  data-testid="phase7b-forbidden-actions"
                >
                  Phase 7B forbidden actions ({" "}
                  {
                    razorpayControlledPilotGateReadiness.forbiddenActions
                      .length
                  }
                  )
                </summary>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {razorpayControlledPilotGateReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </details>
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7b-cli-only-banner"
          >
            <strong>CLI-only Review.</strong> Inspect Gate, Preview
            Gate, Gate Only, Dry-run Only, Rollback Dry-run Only, No
            Live Execution, No Provider Call, Future Phase 7C Review
            Only. No "Start Pilot" / "Run Pilot" / "Execute Pilot" /
            "Send WhatsApp" / "Queue WhatsApp" / "Notify Customer" /
            "Create Shipment" / "Create AWB" / "Book Courier" /
            "Dispatch Order" / "Mark Paid" / "Capture Payment" /
            "Refund" / "Create Payment Link" / "Mutate Order" /
            "Replay Event" / "Enable Mutation" / "Go Live" / "Run MCP
            Tool" / "Approve Gate" / "Reject Gate" buttons exist on
            this page.
          </div>
        </section>
      )}

      {(razorpayControlledPilotExecutionReadiness ||
        razorpayControlledPilotExecutionAttempts) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-controlled-pilot-execution-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Razorpay Controlled Pilot Execution (One-shot TEST)
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7D - <strong>One-shot Razorpay TEST execution
                only</strong>. The execute path is{" "}
                <strong>CLI-only</strong> and refuses unless every
                Phase 7D env flag is true, the Director sign-off names
                the exact Phase 7B gate id, the kill switch is
                enabled, the Razorpay key starts with{" "}
                <code>rzp_test_</code>, and the source chain (Phase 7B
                -&gt; 6T -&gt; 6S -&gt; 6R -&gt; 6Q -&gt; 6P -&gt; 6O
                -&gt; 6M) is green. Phase 7D{" "}
                <strong>never</strong> sends WhatsApp, calls Meta
                Cloud / Delhivery / Vapi, creates a shipment / AWB,
                creates a payment link, captures, refunds, mutates a
                real Order / Payment / Customer / Lead row, edits any{" "}
                <code>.env*</code> file, or sends a customer
                notification. Review state changes are CLI-only; this
                page is read-only.
              </p>
            </div>
            {razorpayControlledPilotExecutionReadiness && (
              <div data-testid="phase7d-status-badge">
                <StatusPill
                  tone={
                    razorpayControlledPilotExecutionReadiness.killSwitch
                      .enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayControlledPilotExecutionReadiness.killSwitch
                    .enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayControlledPilotExecutionReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayControlledPilotExecutionReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayControlledPilotExecutionReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayControlledPilotExecutionReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={
                  razorpayControlledPilotExecutionReadiness.nextPhase
                }
              />
              <KeyValue
                label="Lifecycle flag"
                value={
                  razorpayControlledPilotExecutionReadiness.envFlags
                    .lifecycleEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue
                label="Director one-shot"
                value={
                  razorpayControlledPilotExecutionReadiness.envFlags
                    .directorOneShotApproved
                    ? "Approved"
                    : "Not approved"
                }
              />
              <KeyValue
                label="Allow Razorpay test order"
                value={
                  razorpayControlledPilotExecutionReadiness.envFlags
                    .allowRazorpayTestOrder
                    ? "Allowed"
                    : "Disallowed"
                }
              />
              <KeyValue
                label="Razorpay key mode"
                value={
                  razorpayControlledPilotExecutionReadiness
                    .razorpayKeyAdvisory.razorpayKeyMode
                }
              />
              <KeyValue
                label="Razorpay key id"
                value={
                  razorpayControlledPilotExecutionReadiness
                    .razorpayKeyAdvisory.razorpayKeyIdMasked || "-"
                }
              />
              <KeyValue
                label="Approved Phase 7B gates"
                value={String(
                  razorpayControlledPilotExecutionReadiness.approvedPhase7BGateCount,
                )}
              />
              <KeyValue label="Provider call in 7D" value="No" />
              <KeyValue label="Business mutation in 7D" value="No" />
              <KeyValue label="WhatsApp send in 7D" value="No" />
              <KeyValue label="WhatsApp queue in 7D" value="No" />
              <KeyValue label="Meta Cloud call in 7D" value="No" />
              <KeyValue label="Delhivery call in 7D" value="No" />
              <KeyValue label="Shipment / AWB in 7D" value="No" />
              <KeyValue label="Payment link in 7D" value="No" />
              <KeyValue label="Capture / refund in 7D" value="No" />
              <KeyValue
                label="Customer notification in 7D"
                value="No"
              />
            </div>
          )}

          {razorpayControlledPilotExecutionAttempts && (
            <div className="border-t border-border px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6 text-xs">
              <KeyValue
                label="Draft"
                value={String(
                  razorpayControlledPilotExecutionAttempts.counts.draft,
                )}
              />
              <KeyValue
                label="Pending sign-off"
                value={String(
                  razorpayControlledPilotExecutionAttempts.counts
                    .pendingDirectorSignoff,
                )}
              />
              <KeyValue
                label="Approved one-shot"
                value={String(
                  razorpayControlledPilotExecutionAttempts.counts
                    .approvedForOneShotRun,
                )}
              />
              <KeyValue
                label="Executed"
                value={String(
                  razorpayControlledPilotExecutionAttempts.counts
                    .executed,
                )}
              />
              <KeyValue
                label="Failed"
                value={String(
                  razorpayControlledPilotExecutionAttempts.counts.failed,
                )}
              />
              <KeyValue
                label="Rolled back"
                value={String(
                  razorpayControlledPilotExecutionAttempts.counts
                    .rolledBack,
                )}
              />
            </div>
          )}

          {razorpayControlledPilotExecutionReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {razorpayControlledPilotExecutionReadiness.nextAction}
              </code>
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7d-cli-only-banner"
          >
            <strong>CLI-only Execution Path.</strong> No "Execute
            Razorpay" / "Create Order" / "Approve Attempt" / "Reject
            Attempt" / "Send WhatsApp" / "Notify Customer" / "Create
            Shipment" / "Create AWB" / "Book Courier" / "Mark Paid" /
            "Capture Payment" / "Refund" / "Apply Mutation" / "Mutate
            Order" / "Create Payment Link" / "Replay Event" / "Enable
            Mutation" / "Go Live" / "Run MCP Tool" / "Edit .env"
            buttons exist on this page.
          </div>
        </section>
      )}

      {(razorpayWhatsAppInternalNotificationReadiness ||
        razorpayWhatsAppInternalNotificationGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-whatsapp-internal-notification-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Razorpay → WhatsApp Internal Notification Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7E - <strong>Gate Only</strong>. Approval flips
                a gate to{" "}
                <code>
                  approved_for_future_phase7f_or_7e_send_review
                </code>
                . Phase 7E <strong>never</strong> sends a WhatsApp
                message, never queues an outbound, never calls Meta
                Cloud / Delhivery / Vapi, never creates a shipment /
                AWB / payment link, never captures, never refunds,
                never mutates real <code>Order</code> /{" "}
                <code>Payment</code> / <code>Shipment</code> /{" "}
                <code>Customer</code> / <code>Lead</code> rows, never
                sends a customer notification, and never edits any{" "}
                <code>.env*</code> file. Review state changes are
                CLI-only; this page is read-only. Phase 7F (Delhivery
                shipment) / Phase 7E-Live (real customer WhatsApp
                send) remain <strong>not approved</strong>; any
                future provider-touching command requires Phase 7D-
                Hotfix-1 (structured UTC window guard) to ship first.
              </p>
            </div>
            {razorpayWhatsAppInternalNotificationReadiness && (
              <div data-testid="phase7e-status-badge">
                <StatusPill
                  tone={
                    razorpayWhatsAppInternalNotificationReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayWhatsAppInternalNotificationReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayWhatsAppInternalNotificationReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayWhatsAppInternalNotificationReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={
                  razorpayWhatsAppInternalNotificationReadiness.status
                }
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayWhatsAppInternalNotificationReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={
                  razorpayWhatsAppInternalNotificationReadiness.nextPhase
                }
              />
              <KeyValue
                label="Phase 7E gate flag"
                value={
                  razorpayWhatsAppInternalNotificationReadiness
                    .envFlags.phase7eGateEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue
                label="Phase 7D rolled-back source"
                value={String(
                  razorpayWhatsAppInternalNotificationReadiness.phase7DRolledBackEligibleCount,
                )}
              />
              <KeyValue
                label="Phase 7D Hotfix-1 required"
                value={
                  razorpayWhatsAppInternalNotificationReadiness
                    .phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Legacy free-text signoff allowed (with ack)"
                value={
                  razorpayWhatsAppInternalNotificationReadiness
                    .phase7DSourceSignoffMayBeLegacyFreeTextWithAck
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue label="WhatsApp send in 7E" value="No" />
              <KeyValue label="WhatsApp queue in 7E" value="No" />
              <KeyValue label="Meta Cloud call in 7E" value="No" />
              <KeyValue label="Delhivery call in 7E" value="No" />
              <KeyValue label="Shipment / AWB in 7E" value="No" />
              <KeyValue label="Payment link in 7E" value="No" />
              <KeyValue label="Capture / refund in 7E" value="No" />
              <KeyValue
                label="Customer notification in 7E"
                value="No"
              />
              <KeyValue label="Business mutation in 7E" value="No" />
              <KeyValue
                label="Real customer phone in 7E"
                value="No"
              />
            </div>
          )}

          {razorpayWhatsAppInternalNotificationGates && (
            <div className="border-t border-border px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6 text-xs">
              <KeyValue
                label="Draft"
                value={String(
                  razorpayWhatsAppInternalNotificationGates.counts.draft,
                )}
              />
              <KeyValue
                label="Pending review"
                value={String(
                  razorpayWhatsAppInternalNotificationGates.counts
                    .pending_manual_review,
                )}
              />
              <KeyValue
                label="Approved (future send review)"
                value={String(
                  razorpayWhatsAppInternalNotificationGates.counts
                    .approved_for_future_phase7f_or_7e_send_review,
                )}
              />
              <KeyValue
                label="Rejected"
                value={String(
                  razorpayWhatsAppInternalNotificationGates.counts.rejected,
                )}
              />
              <KeyValue
                label="Archived"
                value={String(
                  razorpayWhatsAppInternalNotificationGates.counts.archived,
                )}
              />
              <KeyValue
                label="Blocked"
                value={String(
                  razorpayWhatsAppInternalNotificationGates.counts.blocked,
                )}
              />
            </div>
          )}

          {razorpayWhatsAppInternalNotificationReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  razorpayWhatsAppInternalNotificationReadiness.nextAction
                }
              </code>
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7e-cli-only-banner"
          >
            <strong>CLI-only Review.</strong> No "Send WhatsApp" /
            "Queue WhatsApp" / "Send Template" / "Send Notification" /
            "Notify Staff" / "Route to WhatsApp" / "Approve Gate" /
            "Reject Gate" / "Approve Attempt" / "Execute" / "Notify
            Customer" / "Create Shipment" / "Create AWB" / "Book
            Courier" / "Mark Paid" / "Capture Payment" / "Refund" /
            "Apply Mutation" / "Mutate Order" / "Create Payment Link"
            / "Replay Event" / "Enable Mutation" / "Go Live" / "Run
            MCP Tool" / "Edit .env" buttons exist on this page.
            Phase 7E approval is a status transition only - it does
            NOT enable any send path.
          </div>
        </section>
      )}

      {(razorpayCourierReadiness || razorpayCourierReadinessGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="delhivery-courier-readiness-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Delhivery / Courier Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7F - <strong>Gate Only</strong>. Approval flips
                a gate to{" "}
                <code>
                  approved_for_future_phase7g_or_courier_execution_review
                </code>
                . Phase 7F <strong>never</strong> calls the Delhivery
                API, never creates a <code>Shipment</code> /{" "}
                <code>WorkflowStep</code> / <code>RescueAttempt</code>{" "}
                row, never creates an AWB, never books a pickup,
                never generates a courier label, never sends or
                queues WhatsApp, never calls Meta Cloud / Razorpay /
                Vapi, never sends a customer notification, never
                mutates real <code>Order</code> / <code>Payment</code>{" "}
                / <code>Customer</code> / <code>Lead</code> rows,
                never edits any <code>.env*</code> file. Review state
                changes are CLI-only; this page is read-only. Phase
                7G (live courier execution) requires a separate
                Director directive AND a future execute-window guard
                reusing{" "}
                <code>apps.saas.utc_window.validate_within_director_window</code>
                . Phase 7G remains <strong>not approved</strong>.
              </p>
            </div>
            {razorpayCourierReadiness && (
              <div data-testid="phase7f-status-badge">
                <StatusPill
                  tone={
                    razorpayCourierReadiness.killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayCourierReadiness.killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayCourierReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayCourierReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayCourierReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpayCourierReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpayCourierReadiness.nextPhase}
              />
              <KeyValue
                label="Phase 7F gate flag"
                value={
                  razorpayCourierReadiness.envFlags
                    .phase7fCourierReadinessGateEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue
                label="Delhivery mode"
                value={String(
                  razorpayCourierReadiness.envFlagSnapshot
                    .DELHIVERY_MODE,
                )}
              />
              <KeyValue
                label="Phase 7E approved gates"
                value={String(
                  razorpayCourierReadiness.phase7EApprovedGateCount,
                )}
              />
              <KeyValue
                label="Phase 7D Hotfix-1 present"
                value={
                  razorpayCourierReadiness.phase7DHotfix1Present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery token (presence)"
                value={
                  razorpayCourierReadiness.delhiveryEnvPresence
                    .DELHIVERY_API_TOKEN_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery base URL (presence)"
                value={
                  razorpayCourierReadiness.delhiveryEnvPresence
                    .DELHIVERY_API_BASE_URL_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery pickup loc (presence)"
                value={
                  razorpayCourierReadiness.delhiveryEnvPresence
                    .DELHIVERY_PICKUP_LOCATION_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery return addr (presence)"
                value={
                  razorpayCourierReadiness.delhiveryEnvPresence
                    .DELHIVERY_RETURN_ADDRESS_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue label="Delhivery call in 7F" value="No" />
              <KeyValue label="Shipment row in 7F" value="No" />
              <KeyValue label="AWB in 7F" value="No" />
              <KeyValue label="Pickup booking in 7F" value="No" />
              <KeyValue label="Label generation in 7F" value="No" />
              <KeyValue
                label="Customer notification in 7F"
                value="No"
              />
              <KeyValue label="WhatsApp send in 7F" value="No" />
              <KeyValue label="WhatsApp queue in 7F" value="No" />
              <KeyValue label="Meta Cloud call in 7F" value="No" />
              <KeyValue label="Razorpay call in 7F" value="No" />
              <KeyValue label="Business mutation in 7F" value="No" />
              <KeyValue
                label="Real customer in 7F"
                value="No"
              />
            </div>
          )}

          {razorpayCourierReadinessGates && (
            <div className="border-t border-border px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6 text-xs">
              <KeyValue
                label="Draft"
                value={String(
                  razorpayCourierReadinessGates.counts.draft,
                )}
              />
              <KeyValue
                label="Pending review"
                value={String(
                  razorpayCourierReadinessGates.counts
                    .pending_manual_review,
                )}
              />
              <KeyValue
                label="Approved (future courier review)"
                value={String(
                  razorpayCourierReadinessGates.counts
                    .approved_for_future_phase7g_or_courier_execution_review,
                )}
              />
              <KeyValue
                label="Rejected"
                value={String(
                  razorpayCourierReadinessGates.counts.rejected,
                )}
              />
              <KeyValue
                label="Archived"
                value={String(
                  razorpayCourierReadinessGates.counts.archived,
                )}
              />
              <KeyValue
                label="Blocked"
                value={String(
                  razorpayCourierReadinessGates.counts.blocked,
                )}
              />
            </div>
          )}

          {razorpayCourierReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>{razorpayCourierReadiness.nextAction}</code>
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7f-cli-only-banner"
          >
            <strong>CLI-only Review.</strong> No "Create Shipment" /
            "Create AWB" / "Book Pickup" / "Generate Label" / "Print
            Label" / "Call Delhivery" / "Track AWB" / "Cancel AWB" /
            "Send WhatsApp" / "Queue WhatsApp" / "Notify Customer" /
            "Notify Staff" / "Route to Courier" / "Approve Gate" /
            "Reject Gate" / "Approve Readiness" / "Reject Readiness"
            / "Execute" / "Mark Paid" / "Capture Payment" / "Refund"
            / "Apply Mutation" / "Mutate Order" / "Create Payment
            Link" / "Replay Event" / "Enable Mutation" / "Go Live" /
            "Run MCP Tool" / "Edit .env" buttons exist on this page.
            Phase 7F approval is a status transition only - it does
            NOT enable any provider call.
          </div>
        </section>
      )}

      {(razorpayCourierExecutionReadiness ||
        razorpayCourierExecutionAttempts) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-courier-execution-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Razorpay Delhivery Courier One-shot TEST/MOCK Execution
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7G — <strong>One-shot TEST/MOCK execution gate
                only</strong>. The execute path is{" "}
                <strong>CLI-only</strong> and lives behind three locked-OFF
                env flags (
                <code>PHASE7G_COURIER_EXECUTION_ENABLED</code>,{" "}
                <code>PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION</code>
                , <code>PHASE7G_ALLOW_DELHIVERY_TEST_AWB</code>). Phase 7G
                is the only currently approved design path in this
                controlled Phase 7 chain that may later issue one Delhivery
                TEST/MOCK API request after fresh Director approval. Phase
                7G-Live (real customer courier execution) remains{" "}
                <strong>not approved</strong>. Phase 7G{" "}
                <strong>never</strong> creates a <code>Shipment</code> row,
                never books a courier pickup separately, never generates /
                prints a courier label, never sends or queues WhatsApp,
                never calls Meta Cloud / Razorpay / Vapi, never sends a
                customer notification, never mutates real{" "}
                <code>Order</code> / <code>Payment</code> /{" "}
                <code>Customer</code> / <code>Lead</code> /{" "}
                <code>DiscountOfferLog</code> rows, never edits any{" "}
                <code>.env*</code> file. Provider/AWB summary lives on the
                attempt row only. Synthetic payload customer name is the
                literal "Phase 7G TEST"; phone is last-4 only ("0000");
                address line is "[redacted]". Review state changes are
                CLI-only; this page is read-only.
              </p>
            </div>
            {razorpayCourierExecutionReadiness && (
              <div data-testid="phase7g-status-badge">
                <StatusPill
                  tone={
                    razorpayCourierExecutionReadiness.killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayCourierExecutionReadiness.killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayCourierExecutionReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayCourierExecutionReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayCourierExecutionReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayCourierExecutionReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpayCourierExecutionReadiness.nextPhase}
              />
              <KeyValue
                label="Phase 7G lifecycle flag"
                value={
                  razorpayCourierExecutionReadiness.phase7GCourierExecutionEnabled
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Director-approved one-shot"
                value={
                  razorpayCourierExecutionReadiness.phase7GDirectorApprovedOneShotCourierExecution
                    ? "Approved"
                    : "Not approved (safe)"
                }
              />
              <KeyValue
                label="Allow Delhivery TEST AWB"
                value={
                  razorpayCourierExecutionReadiness.phase7GAllowDelhiveryTestAwb
                    ? "Allowed"
                    : "Locked (safe)"
                }
              />
              <KeyValue
                label="Allowed Delhivery modes"
                value={razorpayCourierExecutionReadiness.phase7GAllowedDelhiveryModes.join(
                  ", ",
                )}
              />
              <KeyValue
                label="Live customer courier"
                value="Not approved"
              />
              <KeyValue
                label="Delhivery mode"
                value={String(
                  razorpayCourierExecutionReadiness.envFlagSnapshot
                    .DELHIVERY_MODE,
                )}
              />
              <KeyValue
                label="Phase 7F approved gates"
                value={String(
                  razorpayCourierExecutionReadiness.approvedPhase7FGateCount,
                )}
              />
              <KeyValue
                label="Delhivery token (presence)"
                value={
                  razorpayCourierExecutionReadiness.delhiveryEnvPresence
                    .DELHIVERY_API_TOKEN_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery base URL (presence)"
                value={
                  razorpayCourierExecutionReadiness.delhiveryEnvPresence
                    .DELHIVERY_API_BASE_URL_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery pickup loc (presence)"
                value={
                  razorpayCourierExecutionReadiness.delhiveryEnvPresence
                    .DELHIVERY_PICKUP_LOCATION_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Delhivery return addr (presence)"
                value={
                  razorpayCourierExecutionReadiness.delhiveryEnvPresence
                    .DELHIVERY_RETURN_ADDRESS_present
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Safe to run execution"
                value={
                  razorpayCourierExecutionReadiness.safeToRunPhase7GExecution
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue label="Shipment row in 7G" value="No" />
              <KeyValue label="Pickup booking in 7G" value="No" />
              <KeyValue label="Label generation in 7G" value="No" />
              <KeyValue
                label="Customer notification in 7G"
                value="No"
              />
              <KeyValue label="WhatsApp send in 7G" value="No" />
              <KeyValue label="WhatsApp queue in 7G" value="No" />
              <KeyValue label="Meta Cloud call in 7G" value="No" />
              <KeyValue label="Razorpay call in 7G" value="No" />
              <KeyValue label="Vapi call in 7G" value="No" />
              <KeyValue label="Business mutation in 7G" value="No" />
            </div>
          )}

          {razorpayCourierExecutionAttempts && (
            <div className="border-t border-border px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6 text-xs">
              <KeyValue
                label="Draft"
                value={String(
                  razorpayCourierExecutionAttempts.counts.draft,
                )}
              />
              <KeyValue
                label="Pending sign-off"
                value={String(
                  razorpayCourierExecutionAttempts.counts
                    .pendingDirectorSignoff,
                )}
              />
              <KeyValue
                label="Approved (one-shot)"
                value={String(
                  razorpayCourierExecutionAttempts.counts
                    .approvedForOneShotRun,
                )}
              />
              <KeyValue
                label="Executed"
                value={String(
                  razorpayCourierExecutionAttempts.counts.executed,
                )}
              />
              <KeyValue
                label="Failed"
                value={String(
                  razorpayCourierExecutionAttempts.counts.failed,
                )}
              />
              <KeyValue
                label="Rolled back (recorded)"
                value={String(
                  razorpayCourierExecutionAttempts.counts
                    .rolledBackRecorded,
                )}
              />
              <KeyValue
                label="Rejected"
                value={String(
                  razorpayCourierExecutionAttempts.counts.rejected,
                )}
              />
              <KeyValue
                label="Archived"
                value={String(
                  razorpayCourierExecutionAttempts.counts.archived,
                )}
              />
              <KeyValue
                label="AWB created"
                value={String(
                  razorpayCourierExecutionAttempts.counts.awbCreated,
                )}
              />
              <KeyValue
                label="Shipment created (must be 0)"
                value={String(
                  razorpayCourierExecutionAttempts.counts.shipmentCreated,
                )}
              />
              <KeyValue
                label="Business mutation (must be 0)"
                value={String(
                  razorpayCourierExecutionAttempts.counts
                    .businessMutationWasMade,
                )}
              />
              <KeyValue
                label="Customer notification (must be 0)"
                value={String(
                  razorpayCourierExecutionAttempts.counts
                    .customerNotificationSent,
                )}
              />
            </div>
          )}

          {razorpayCourierExecutionReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {razorpayCourierExecutionReadiness.nextAction}
              </code>
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7g-cli-only-banner"
          >
            <strong>CLI-only Execute.</strong> No "Execute Courier" /
            "Run One-shot" / "Create AWB" / "Create Shipment" / "Book
            Pickup" / "Generate Label" / "Print Label" / "Cancel AWB" /
            "Send WhatsApp" / "Queue WhatsApp" / "Notify Customer" /
            "Approve Attempt" / "Reject Attempt" / "Rollback" / "Mark
            Paid" / "Capture Payment" / "Refund" / "Apply Mutation" /
            "Mutate Order" / "Replay Event" / "Enable Mutation" / "Go
            Live" / "Run MCP Tool" / "Edit .env" buttons exist on this
            page. Phase 7G execution lives only behind the locked-OFF{" "}
            <code>execute_delhivery_courier_one_shot</code> CLI command
            and requires three Phase 7G env flags + non-empty Director
            sign-off mentioning the Phase 7F gate id + non-empty
            operator name + DELHIVERY_MODE acknowledgement matching
            <code>mock</code> or <code>test</code> + record-only
            rollback acknowledgement + RuntimeKillSwitch enabled +
            full source-chain green.
          </div>
        </section>
      )}

      {(razorpayCourierExecutionEvidenceLockReadiness ||
        razorpayCourierExecutionEvidenceLocks) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase7h-courier-evidence-lock-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 7H Courier Execution Evidence Lock
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7H — <strong>lock-only</strong>. Snapshots the
                immutable fields off a completed Phase 7G TEST/MOCK
                courier execution attempt (status =
                <code>rolled_back_recorded</code> with{" "}
                <code>provider_call_attempted=true</code> +{" "}
                <code>awb_created=true</code> AND every locked-False
                boolean still <code>false</code>). Approval flips
                status to <code>locked</code>; it does NOT enable any
                live execution. Phase 7H NEVER calls Delhivery, NEVER
                creates a <code>Shipment</code> / AWB row, NEVER
                sends or queues WhatsApp, NEVER calls Meta Cloud /
                Razorpay / Vapi, NEVER sends a customer notification,
                NEVER mutates real <code>Order</code> /{" "}
                <code>Payment</code> / <code>Customer</code> /{" "}
                <code>Lead</code> rows, NEVER edits any{" "}
                <code>.env*</code> file. Review state changes are
                CLI-only. Phase 7G-Live (real customer courier
                execution) remains <strong>not approved</strong>.
              </p>
            </div>
            {razorpayCourierExecutionEvidenceLockReadiness && (
              <div data-testid="phase7h-status-badge">
                <StatusPill
                  tone={
                    razorpayCourierExecutionEvidenceLockReadiness.killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayCourierExecutionEvidenceLockReadiness.killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {razorpayCourierExecutionEvidenceLockReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={
                  razorpayCourierExecutionEvidenceLockReadiness.phase
                }
              />
              <KeyValue
                label="Status"
                value={
                  razorpayCourierExecutionEvidenceLockReadiness.status
                }
              />
              <KeyValue
                label="Eligible 7G attempts"
                value={String(
                  razorpayCourierExecutionEvidenceLockReadiness.eligiblePhase7GAttemptCount,
                )}
              />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue label="Creates AWB" value="No" />
              <KeyValue label="Creates Shipment row" value="No" />
              <KeyValue label="Sends WhatsApp" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Business mutation" value="No" />
              <KeyValue
                label="Live customer courier"
                value="Not approved"
              />
            </div>
          )}
          {razorpayCourierExecutionEvidenceLocks &&
            razorpayCourierExecutionEvidenceLocks.items.length > 0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {razorpayCourierExecutionEvidenceLocks.items.map(
                  (lock) => (
                    <div
                      key={lock.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5 py-1 border-b border-border last:border-0"
                    >
                      <span>
                        id=<strong>{lock.id}</strong>
                      </span>
                      <span>status={lock.status}</span>
                      <span>
                        7G attempt={lock.sourcePhase7GAttemptId}
                      </span>
                      <span>
                        AWB={lock.providerObjectIdSnapshot || "-"}
                      </span>
                      <span>
                        rollback={lock.rollbackStatusSnapshot}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {razorpayCourierExecutionEvidenceLockReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  razorpayCourierExecutionEvidenceLockReadiness.nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7h-cli-only-banner"
          >
            <strong>Lock-only · CLI-only Review.</strong> No "Lock
            Evidence" / "Approve Lock" / "Reject Lock" / "Archive
            Lock" / "Execute" / "Send" / "Notify" buttons exist on
            this page. Phase 7H approval is a status transition only —
            it does NOT enable any provider call.
          </div>
        </section>
      )}

      {(phase7eLiveInternalSendReadiness ||
        phase7eLiveInternalSendAttempts) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase7e-live-internal-send-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 7E-Live-A Internal WhatsApp One-shot
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7E-Live-A — <strong>internal-staff only</strong>.
                Recipient MUST be on{" "}
                <code>WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS</code>;
                template MUST be approved with Claim Vault grounding;
                no freeform medical text. Execute path is{" "}
                <strong>CLI-only</strong> and requires a fresh
                Director sign-off with structured{" "}
                <code>BEGIN_UTC=</code> / <code>END_UTC=</code>{" "}
                markers (≤ 15 min). Phase 7E-Live-A NEVER sends to a
                real customer phone, NEVER queues broad automation,
                NEVER mutates real <code>Order</code> /{" "}
                <code>Payment</code> / <code>Customer</code> /{" "}
                <code>Lead</code> rows, NEVER edits any{" "}
                <code>.env*</code> file. Phase 7E-Live-B (real
                customer WhatsApp send) remains{" "}
                <strong>not approved</strong>.
              </p>
            </div>
            {phase7eLiveInternalSendReadiness && (
              <div data-testid="phase7e-live-status-badge">
                <StatusPill
                  tone={
                    phase7eLiveInternalSendReadiness.killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase7eLiveInternalSendReadiness.killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase7eLiveInternalSendReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={phase7eLiveInternalSendReadiness.phase}
              />
              <KeyValue
                label="Recipient scope"
                value={
                  phase7eLiveInternalSendReadiness.phase7ELiveRecipientScope
                }
              />
              <KeyValue
                label="Send flag"
                value={
                  phase7eLiveInternalSendReadiness.phase7ELiveInternalWhatsAppSendEnabled
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Limited test mode"
                value={
                  phase7eLiveInternalSendReadiness.whatsAppLiveMetaLimitedTestMode
                    ? "On"
                    : "Off"
                }
              />
              <KeyValue
                label="Allow-list size"
                value={String(
                  phase7eLiveInternalSendReadiness.allowedTestNumbersCount,
                )}
              />
              <KeyValue label="Sends to real customer" value="No" />
              <KeyValue label="Mutates business rows" value="No" />
              <KeyValue label="Customer notification" value="No" />
              <KeyValue
                label="Supports freeform medical text"
                value="No"
              />
              <KeyValue
                label="Safe to run send"
                value={
                  phase7eLiveInternalSendReadiness.safeToRunPhase7ELiveSend
                    ? "Yes"
                    : "No"
                }
              />
            </div>
          )}
          {phase7eLiveInternalSendAttempts && (
            <div className="border-t border-border px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-5 text-xs">
              {Object.entries(
                phase7eLiveInternalSendAttempts.counts,
              ).map(([status, count]) => (
                <KeyValue
                  key={status}
                  label={status}
                  value={String(count)}
                />
              ))}
            </div>
          )}
          {phase7eLiveInternalSendReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {phase7eLiveInternalSendReadiness.nextAction}
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7e-live-cli-only-banner"
          >
            <strong>CLI-only Execute.</strong> No "Send WhatsApp" /
            "Queue WhatsApp" / "Send Template" / "Notify Customer" /
            "Approve Send" / "Reject Send" / "Execute" / "Run
            One-shot" / "Approve Attempt" / "Reject Attempt" /
            "Rollback" / "Mutate Order" / "Apply Mutation" / "Go
            Live" / "Edit .env" buttons exist on this page. The
            actual send lives only behind the locked-OFF{" "}
            <code>execute_phase7e_live_internal_whatsapp_send</code>{" "}
            CLI command and requires three structured Director
            sign-off conditions + the allow-list recipient + the
            structured UTC window.
          </div>
        </section>
      )}

      {phase7eLiveBRealCustomerGates && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase7e-live-b-real-customer-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 7E-Live-B Real Customer WhatsApp One-shot
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                One approved template to one real customer per gate. The
                lifecycle is CLI-only, requires Director sign-off with a
                structured UTC window, and has no rollback because WhatsApp
                messages cannot be unsent.
              </p>
            </div>
            <StatusPill tone="warning">CLI-only</StatusPill>
          </div>
          <div className="px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-5 text-xs">
            {Object.entries(phase7eLiveBRealCustomerGates.counts).map(
              ([status, count]) => (
                <KeyValue
                  key={status}
                  label={status}
                  value={String(count)}
                />
              ),
            )}
          </div>
          {phase7eLiveBRealCustomerGates.items.length > 0 && (
            <div className="border-t border-border px-6 py-4 overflow-x-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4">Gate</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Template</th>
                    <th className="py-2 pr-4">Target</th>
                    <th className="py-2 pr-4">Executed</th>
                    <th className="py-2 pr-4">Meta message</th>
                  </tr>
                </thead>
                <tbody>
                  {phase7eLiveBRealCustomerGates.items.map((gate) => (
                    <tr key={gate.id} data-testid="phase7e-live-b-gate-row">
                      <td className="py-2 pr-4">{gate.id}</td>
                      <td className="py-2 pr-4">{gate.status}</td>
                      <td className="py-2 pr-4">{gate.templateName}</td>
                      <td className="py-2 pr-4">{gate.targetMasked}</td>
                      <td className="py-2 pr-4">
                        {gate.executedAt ?? "Not executed"}
                      </td>
                      <td className="py-2 pr-4">
                        {gate.metaMessageId || "None"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7e-live-b-cli-only-banner"
          >
            <strong>CLI-only Execute.</strong> No "Send WhatsApp" /
            "Approve Send" / "Execute" / "Cancel" / "Broadcast" /
            "Campaign" / "Bulk Send" / "AI Freeform" buttons exist on
            this page.
          </div>
        </section>
      )}

      {phase7gLiveRealCustomerDispatchGates && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase7g-live-real-customer-dispatch-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 7G-Live Real Customer Delhivery One-shot Dispatch
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                One confirmed order per gate. The lifecycle is CLI-only,
                requires Director sign-off with a structured 15-minute UTC
                window, and runs only when{" "}
                <code>DELHIVERY_MODE=live</code> is supplied via runtime env
                prefix. Rollback attempts AWB cancellation honestly —
                Delhivery may refuse if the shipment is already in transit.
              </p>
            </div>
            <StatusPill tone="warning">CLI-only</StatusPill>
          </div>
          <div className="px-6 py-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6 text-xs">
            {Object.entries(phase7gLiveRealCustomerDispatchGates.counts).map(
              ([status, count]) => (
                <KeyValue
                  key={status}
                  label={status}
                  value={String(count)}
                />
              ),
            )}
          </div>
          {phase7gLiveRealCustomerDispatchGates.items.length > 0 && (
            <div className="border-t border-border px-6 py-4 overflow-x-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4">Gate</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Order</th>
                    <th className="py-2 pr-4">AWB</th>
                    <th className="py-2 pr-4">Executed</th>
                    <th className="py-2 pr-4">Rollback</th>
                  </tr>
                </thead>
                <tbody>
                  {phase7gLiveRealCustomerDispatchGates.items.map((gate) => (
                    <tr
                      key={gate.id}
                      data-testid="phase7g-live-dispatch-gate-row"
                    >
                      <td className="py-2 pr-4">{gate.id}</td>
                      <td className="py-2 pr-4">{gate.status}</td>
                      <td className="py-2 pr-4">{gate.targetOrderId}</td>
                      <td className="py-2 pr-4">
                        {gate.awbNumber || "None"}
                      </td>
                      <td className="py-2 pr-4">
                        {gate.executedAt ?? "Not executed"}
                      </td>
                      <td className="py-2 pr-4">
                        {gate.cancellationAttemptedAt
                          ? String(
                              (gate.cancellationResult as { status?: string })
                                ?.status ?? "recorded",
                            )
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7g-live-cli-only-banner"
          >
            <strong>CLI-only Execute + Rollback.</strong> No "Dispatch" /
            "Create AWB" / "Approve" / "Execute" / "Rollback" / "Cancel
            AWB" / "Bulk Dispatch" / "Auto Dispatch" / "AI Dispatch"
            buttons exist on this page.
          </div>
        </section>
      )}

      {ceoOrchestrationLatest && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="ceo-orchestration-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                CEO AI — Daily Director Briefing
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Recommendations-only. Deterministic daily synthesis over
                Phase 9A–9E agent snapshots producing a composite
                business health score, cross-cutting alerts, top-3
                priorities, and an internal-only briefing text. The
                agent NEVER triggers WhatsApp, calls, payments, or
                shipments; downstream gates (Phase 5D / 5E / 7E-Live-B
                / 7G-Live) remain the only paths to real customer
                action.
              </p>
            </div>
            <StatusPill tone="success">Recs-only</StatusPill>
          </div>
          {ceoOrchestrationLatest.snapshot ? (
            <>
              <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 text-xs">
                <div
                  className="rounded border border-border px-3 py-3"
                  data-testid="ceo-orchestration-health-score"
                >
                  <div className="text-muted-foreground">
                    Business health score
                  </div>
                  <div className="text-2xl font-semibold">
                    {String(
                      ceoOrchestrationLatest.snapshot.businessHealthScore,
                    )}
                  </div>
                  <div className="text-xs uppercase tracking-wide">
                    {ceoOrchestrationLatest.snapshot.healthTier}
                  </div>
                </div>
                <KeyValue
                  label="Snapshot timestamp"
                  value={
                    ceoOrchestrationLatest.snapshot.snapshotAt
                      ? String(
                          ceoOrchestrationLatest.snapshot.snapshotAt,
                        )
                      : "—"
                  }
                />
                <KeyValue
                  label="Last agent run status"
                  value={
                    ceoOrchestrationLatest.lastAgentRunStatus || "n/a"
                  }
                />
              </div>
              <div className="border-t border-border px-6 py-4 overflow-x-auto">
                <p className="text-xs font-medium mb-2">
                  Agent status summary
                </p>
                <table className="min-w-full text-left text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-4">Agent</th>
                      <th className="py-2 pr-4">Status</th>
                      <th className="py-2 pr-4">Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(
                      ceoOrchestrationLatest.snapshot.agentStatusSummary,
                    ).map(([key, entry]) => (
                      <tr
                        key={key}
                        data-testid="ceo-orchestration-agent-row"
                      >
                        <td className="py-2 pr-4">{key}</td>
                        <td className="py-2 pr-4">{entry.status}</td>
                        <td className="py-2 pr-4">{entry.summary}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {ceoOrchestrationLatest.snapshot.top3Priorities.length >
              0 && (
                <div className="border-t border-border px-6 py-4">
                  <p className="text-xs font-medium mb-2">
                    Top priorities
                  </p>
                  <ol className="space-y-1 text-xs list-decimal pl-5">
                    {ceoOrchestrationLatest.snapshot.top3Priorities.map(
                      (entry) => (
                        <li
                          key={entry.priority}
                          data-testid="ceo-orchestration-priority-row"
                        >
                          <strong>{entry.issue}</strong>{" "}
                          (source: {entry.source_agent}) —{" "}
                          {entry.recommended_action}
                        </li>
                      ),
                    )}
                  </ol>
                </div>
              )}
              {ceoOrchestrationLatest.snapshot.crossCuttingAlerts.length >
              0 && (
                <div className="border-t border-border px-6 py-4">
                  <p className="text-xs font-medium mb-2">
                    Cross-cutting alerts
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {ceoOrchestrationLatest.snapshot.crossCuttingAlerts.map(
                      (entry, idx) => (
                        <span
                          key={`${entry.code}-${idx}`}
                          data-testid="ceo-orchestration-alert-pill"
                          className="rounded-full border border-border px-2 py-1 text-xs"
                        >
                          [{entry.severity}] {entry.code}{" "}
                          ({entry.source_agent})
                        </span>
                      ),
                    )}
                  </div>
                </div>
              )}
              <div className="border-t border-border px-6 py-4">
                <p className="text-xs font-medium mb-2">
                  Briefing text
                </p>
                <pre
                  data-testid="ceo-orchestration-briefing-text"
                  className="max-h-64 overflow-auto rounded bg-muted/30 p-3 text-xs whitespace-pre-wrap"
                >
                  {ceoOrchestrationLatest.snapshot.briefingText}
                </pre>
              </div>
            </>
          ) : (
            <div className="px-6 py-4 text-xs text-muted-foreground">
              No CEO orchestration snapshot yet. The daily Celery task
              will produce one at the configured time.
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="ceo-orchestration-recs-only-banner"
          >
            <strong>Recommendations-only.</strong> No "Approve
            Priority" / "Trigger Workflow" / "Send Briefing" / "Run
            Agent" / "Apply Recommendation" buttons exist on this
            page.
          </div>
        </section>
      )}

      {/* Phase 11C — CAIO Audit Agent V1 (read-only). */}
      {caioLatestSnapshot && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="caio-audit-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                CAIO — AI Governance Audit
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Reads Phase 9A–9F + Phase 11A/11B. Reports to Director.
                No execution power.
              </p>
            </div>
            <span
              data-testid="caio-severity-badge"
              className={
                caioLatestSnapshot.severity === "red"
                  ? "rounded-full px-3 py-1 text-xs font-semibold bg-red-100 text-red-800"
                  : caioLatestSnapshot.severity === "amber"
                  ? "rounded-full px-3 py-1 text-xs font-semibold bg-amber-100 text-amber-800"
                  : "rounded-full px-3 py-1 text-xs font-semibold bg-green-100 text-green-800"
              }
            >
              {caioLatestSnapshot.severity.toUpperCase()}
            </span>
          </div>
          <div className="px-6 py-3 text-xs text-muted-foreground">
            Last audit:{" "}
            {caioLatestSnapshot.snapshot_at
              ? new Date(caioLatestSnapshot.snapshot_at).toLocaleString()
              : "—"}
          </div>
          <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <KeyValue
              label="Compliance risk calls"
              value={String(
                caioLatestSnapshot.compliance_risk_call_count,
              )}
            />
            <KeyValue
              label="Transcript backlog"
              value={String(caioLatestSnapshot.transcript_backlog_count)}
            />
            <KeyValue
              label="Agent data gaps"
              value={String(caioLatestSnapshot.agent_data_gaps)}
            />
            <KeyValue
              label="Quality trend"
              value={caioLatestSnapshot.call_quality_trend}
            />
          </div>
          {Object.keys(caioLatestSnapshot.agent_anomaly_flags || {})
            .length > 0 && (
            <div
              className="border-t border-border px-6 py-4"
              data-testid="caio-agent-anomalies"
            >
              <p className="text-xs font-medium mb-2">Agent anomalies</p>
              <ul className="space-y-1 text-xs">
                {Object.entries(caioLatestSnapshot.agent_anomaly_flags)
                  .slice(0, 5)
                  .map(([agent, codes]) => (
                    <li key={agent}>
                      <strong>{agent}:</strong> {codes.join(", ")}
                    </li>
                  ))}
                {Object.keys(caioLatestSnapshot.agent_anomaly_flags)
                  .length > 5 && (
                  <li className="text-muted-foreground">
                    +
                    {Object.keys(caioLatestSnapshot.agent_anomaly_flags)
                      .length - 5}{" "}
                    more
                  </li>
                )}
              </ul>
            </div>
          )}
          {caioLatestSnapshot.weak_learning_indicators.length > 0 && (
            <div
              className="border-t border-border px-6 py-4"
              data-testid="caio-weak-learning"
            >
              <p className="text-xs font-medium mb-2">
                Weak learning indicators
              </p>
              <div className="flex flex-wrap gap-2">
                {caioLatestSnapshot.weak_learning_indicators.map(
                  (code) => (
                    <span
                      key={code}
                      className="rounded-full border border-border bg-muted/30 px-2 py-1 text-xs"
                    >
                      {code}
                    </span>
                  ),
                )}
              </div>
            </div>
          )}
          {caioLatestSnapshot.ceo_audit_notes.length > 0 && (
            <div
              className="border-t border-border px-6 py-4"
              data-testid="caio-ceo-audit"
            >
              <p className="text-xs font-medium mb-1">CEO AI audit</p>
              <p className="text-xs italic text-muted-foreground">
                {caioLatestSnapshot.ceo_audit_notes[0]}
              </p>
            </div>
          )}
          {caioLatestSnapshot.recommendation_text && (
            <div
              className="border-t border-border px-6 py-4"
              data-testid="caio-recommendation"
            >
              <p className="text-xs font-medium mb-2">Recommendation</p>
              <p className="text-xs text-muted-foreground whitespace-pre-line">
                {caioLatestSnapshot.recommendation_text.slice(0, 200)}
                {caioLatestSnapshot.recommendation_text.length > 200
                  ? "…"
                  : ""}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                See full report via:{" "}
                <code className="rounded bg-muted/30 px-1">
                  GET /api/v1/caio/snapshots/latest/
                </code>
              </p>
            </div>
          )}
          <div className="border-t border-border px-6 py-3 text-xs">
            <a
              href="/operations/learning-proposals"
              className="text-primary underline"
              data-testid="caio-view-learning-proposals-link"
            >
              View learning proposals →
            </a>
          </div>
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="caio-read-only-banner"
          >
            <strong>Internal governance report — CLI-only management.</strong>{" "}
            No "Run Audit" / "Force Refresh" / "Apply Recommendation"
            buttons exist on this page.
          </div>
        </section>
      )}

      {/* Phase 11D — Learning Proposals mini-card (read-only). */}
      {learningProposalSummary && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="learning-proposals-mini-card"
        >
          <div className="border-b border-border px-6 py-4">
            <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
              <ShieldCheck className="h-5 w-5 text-primary" />
              Learning Proposals
            </h3>
            <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
              CAIO-generated governance improvement proposals awaiting
              Director review.
            </p>
          </div>
          <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <KeyValue
              label="Pending"
              value={String(learningProposalSummary.pending)}
            />
            <KeyValue
              label="Approved"
              value={String(learningProposalSummary.approved)}
            />
            <KeyValue
              label="Implemented"
              value={String(learningProposalSummary.implemented)}
            />
            <KeyValue
              label="High-impact pending"
              value={String(learningProposalSummary.high_impact_pending)}
            />
          </div>
          <div className="border-t border-border px-6 py-4">
            <p className="text-xs font-medium mb-2">
              Top pending proposals
            </p>
            {learningProposals &&
            learningProposals.results.filter((p) => p.status === "pending")
              .length > 0 ? (
              <ul className="space-y-2 text-xs">
                {learningProposals.results
                  .filter((p) => p.status === "pending")
                  .slice(0, 3)
                  .map((p) => (
                    <li
                      key={p.id}
                      data-testid="learning-proposal-row"
                      className="flex items-start justify-between gap-3 rounded border border-border px-3 py-2"
                    >
                      <div className="flex-1">
                        <div className="font-medium">{p.title}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px]">
                          <span className="rounded-full border border-border px-2 py-0.5">
                            {p.proposal_type}
                          </span>
                          <span
                            className={
                              p.impact_scope === "high"
                                ? "rounded-full bg-red-100 text-red-800 px-2 py-0.5"
                                : p.impact_scope === "medium"
                                ? "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5"
                                : "rounded-full bg-muted/40 px-2 py-0.5"
                            }
                          >
                            {p.impact_scope}
                          </span>
                          <span className="text-muted-foreground">
                            {new Date(p.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                    </li>
                  ))}
              </ul>
            ) : (
              <p
                className="text-xs text-emerald-700"
                data-testid="learning-proposals-empty"
              >
                ✓ No pending proposals. System is current.
              </p>
            )}
          </div>
          <div className="border-t border-border px-6 py-3 text-xs">
            <a
              href="/operations/learning-proposals"
              className="text-primary underline"
              data-testid="learning-proposals-view-all-link"
            >
              View all proposals →
            </a>
          </div>
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="learning-proposals-read-only-banner"
          >
            <strong>Review and act via CLI:</strong>{" "}
            <code className="rounded bg-muted/30 px-1">
              python manage.py list_learning_proposals
            </code>{" "}
            — no Approve / Reject / Implement buttons exist on this
            page.
          </div>
        </section>
      )}

      {customerSuccessCohorts && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="customer-success-reorder-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Customer Success / Reorder Agent V1
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Recommendations-only. Deterministic daily sweep scores each
                delivered customer's reorder readiness, lifecycle stage, and
                at-risk signals. The agent NEVER directly sends WhatsApp,
                makes a call, creates a payment link, or dispatches an
                order; downstream gates (Phase 5D / 7E-Live-B / 7G-Live)
                remain the only paths to real customer action.
              </p>
            </div>
            <StatusPill tone="success">Recs-only</StatusPill>
          </div>
          <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <KeyValue
              label="Reorder candidates"
              value={String(customerSuccessCohorts.reorderCandidateCount)}
            />
            <KeyValue
              label="At-risk"
              value={String(customerSuccessCohorts.atRiskCount)}
            />
            <KeyValue
              label="Last agent run"
              value={
                customerSuccessCohorts.lastAgentRunAt
                  ? String(customerSuccessCohorts.lastAgentRunAt)
                  : "Not yet run"
              }
            />
            <KeyValue
              label="Last run status"
              value={customerSuccessCohorts.lastAgentRunStatus || "n/a"}
            />
          </div>
          <div className="border-t border-border px-6 py-4 overflow-x-auto">
            <p className="text-xs font-medium mb-2">
              Lifecycle stage cohort
            </p>
            <table className="min-w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4">Stage</th>
                  <th className="py-2 pr-4">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(
                  customerSuccessCohorts.stageCounts || {},
                ).map(([stage, count]) => (
                  <tr key={stage} data-testid="customer-success-stage-row">
                    <td className="py-2 pr-4">{stage}</td>
                    <td className="py-2 pr-4">{String(count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {customerSuccessCohorts.topReorderCandidates.length > 0 && (
            <div className="border-t border-border px-6 py-4 overflow-x-auto">
              <p className="text-xs font-medium mb-2">
                Top reorder candidates (masked customer id)
              </p>
              <table className="min-w-full text-left text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4">Customer</th>
                    <th className="py-2 pr-4">Score</th>
                    <th className="py-2 pr-4">Days since delivery</th>
                  </tr>
                </thead>
                <tbody>
                  {customerSuccessCohorts.topReorderCandidates.map((c) => (
                    <tr
                      key={c.id}
                      data-testid="customer-success-reorder-row"
                    >
                      <td className="py-2 pr-4">{c.customerIdMasked}</td>
                      <td className="py-2 pr-4">{String(c.score)}</td>
                      <td className="py-2 pr-4">
                        {String(c.daysSinceDelivery)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="customer-success-recs-only-banner"
          >
            <strong>Recommendations-only.</strong> No "Send WhatsApp" /
            "Trigger Call" / "Run Agent" / "Execute" / "Push Reorder" /
            "Auto-dispatch" buttons exist on this page.
          </div>
        </section>
      )}

      {rtoPreventionCohorts && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="rto-prevention-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                RTO Prevention Agent V1
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Recommendations-only. Deterministic daily sweep scores each
                in-flight order's return-to-origin risk (0–100), classifies
                tier and lifecycle stage, and suggests an intervention.
                The agent NEVER directly triggers a call, WhatsApp send,
                discount creation, shipment mutation, or payment mutation;
                Phase 5D / 5E / 7E-Live-B / 7G-Live gates remain the only
                paths to real customer action.
              </p>
            </div>
            <StatusPill tone="success">Recs-only</StatusPill>
          </div>
          <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <KeyValue
              label="Critical orders"
              value={String(
                rtoPreventionCohorts.tierCounts?.critical ?? 0,
              )}
            />
            <KeyValue
              label="High-risk orders"
              value={String(rtoPreventionCohorts.tierCounts?.high ?? 0)}
            />
            <KeyValue
              label="Last agent run"
              value={
                rtoPreventionCohorts.lastAgentRunAt
                  ? String(rtoPreventionCohorts.lastAgentRunAt)
                  : "Not yet run"
              }
            />
            <KeyValue
              label="Last run status"
              value={rtoPreventionCohorts.lastAgentRunStatus || "n/a"}
            />
          </div>
          <div className="border-t border-border px-6 py-4 overflow-x-auto">
            <p className="text-xs font-medium mb-2">Risk tier cohort</p>
            <table className="min-w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4">Tier</th>
                  <th className="py-2 pr-4">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(
                  rtoPreventionCohorts.tierCounts || {},
                ).map(([tier, count]) => (
                  <tr key={tier} data-testid="rto-prevention-tier-row">
                    <td className="py-2 pr-4">{tier}</td>
                    <td className="py-2 pr-4">{String(count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border px-6 py-4 overflow-x-auto">
            <p className="text-xs font-medium mb-2">Recommendation cohort</p>
            <table className="min-w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4">Kind</th>
                  <th className="py-2 pr-4">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(
                  rtoPreventionCohorts.recommendationCounts || {},
                ).map(([kind, count]) => (
                  <tr key={kind} data-testid="rto-prevention-kind-row">
                    <td className="py-2 pr-4">{kind}</td>
                    <td className="py-2 pr-4">{String(count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rtoPreventionCohorts.topCriticalOrders.length > 0 && (
            <div className="border-t border-border px-6 py-4 overflow-x-auto">
              <p className="text-xs font-medium mb-2">
                Top critical-tier orders (masked order id)
              </p>
              <table className="min-w-full text-left text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4">Order</th>
                    <th className="py-2 pr-4">Risk score</th>
                    <th className="py-2 pr-4">Days since order</th>
                  </tr>
                </thead>
                <tbody>
                  {rtoPreventionCohorts.topCriticalOrders.map((o) => (
                    <tr
                      key={o.id}
                      data-testid="rto-prevention-critical-row"
                    >
                      <td className="py-2 pr-4">{o.orderIdMasked}</td>
                      <td className="py-2 pr-4">{String(o.riskScore)}</td>
                      <td className="py-2 pr-4">
                        {String(o.daysSinceOrder)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="rto-prevention-recs-only-banner"
          >
            <strong>Recommendations-only.</strong> No "Call Customer" /
            "Send WhatsApp" / "Apply Discount" / "Force Dispatch" /
            "Run Agent" / "Auto-rescue" buttons exist on this page.
          </div>
        </section>
      )}

      {cfoLatest && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="cfo-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                CFO Agent V1 — Daily Financial Snapshot
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Recommendations-only. Deterministic daily aggregation of
                revenue, order counts, payment status breakdown, AOV, RTO
                impact, customer mix, and anomaly alert codes. The agent
                NEVER triggers WhatsApp, calls, payments, shipments, or
                discounts; downstream gates (Phase 5D / 5E / 7E-Live-B /
                7G-Live) remain the only paths to real customer action.
              </p>
            </div>
            <StatusPill tone="success">Recs-only</StatusPill>
          </div>
          {cfoLatest.snapshot ? (
            <>
              <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                <KeyValue
                  label="Revenue 24h"
                  value={`₹${cfoLatest.snapshot.revenue24h}`}
                />
                <KeyValue
                  label="Revenue 7d"
                  value={`₹${cfoLatest.snapshot.revenue7d}`}
                />
                <KeyValue
                  label="Revenue 30d"
                  value={`₹${cfoLatest.snapshot.revenue30d}`}
                />
                <KeyValue
                  label="AOV (30d)"
                  value={`₹${cfoLatest.snapshot.averageOrderValue}`}
                />
                <KeyValue
                  label="Orders 24h"
                  value={String(cfoLatest.snapshot.orderCount24h)}
                />
                <KeyValue
                  label="Orders 7d"
                  value={String(cfoLatest.snapshot.orderCount7d)}
                />
                <KeyValue
                  label="Orders 30d"
                  value={String(cfoLatest.snapshot.orderCount30d)}
                />
                <KeyValue
                  label="RTO 30d"
                  value={`${cfoLatest.snapshot.rtoCount30d} (₹${cfoLatest.snapshot.rtoLossAmount30d})`}
                />
                <KeyValue
                  label="Paid"
                  value={`${cfoLatest.snapshot.paidCount} / ₹${cfoLatest.snapshot.paidAmount}`}
                />
                <KeyValue
                  label="Partial"
                  value={`${cfoLatest.snapshot.partialCount} / ₹${cfoLatest.snapshot.partialAmount}`}
                />
                <KeyValue
                  label="Pending"
                  value={`${cfoLatest.snapshot.pendingCount} / ₹${cfoLatest.snapshot.pendingAmount}`}
                />
                <KeyValue
                  label="Customer mix (30d)"
                  value={`new ${cfoLatest.snapshot.newCustomerCount30d} / returning ${cfoLatest.snapshot.returningCustomerCount30d}`}
                />
              </div>
              <div className="border-t border-border px-6 py-4 overflow-x-auto">
                <p className="text-xs font-medium mb-2">Active alerts</p>
                <div className="flex flex-wrap gap-2">
                  {cfoLatest.snapshot.alerts.map((alert) => (
                    <span
                      key={alert}
                      data-testid="cfo-alert-pill"
                      className="rounded-full border border-border px-2 py-1 text-xs"
                    >
                      {alert}
                    </span>
                  ))}
                </div>
                {cfoLatest.snapshot.alertText && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {cfoLatest.snapshot.alertText}
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="px-6 py-4 text-xs text-muted-foreground">
              No CFO snapshot yet. The daily Celery task will produce one
              at the configured time.
            </div>
          )}
          <div className="px-6 py-3 grid gap-2 sm:grid-cols-2 text-xs">
            <KeyValue
              label="Snapshot timestamp"
              value={
                cfoLatest.snapshot?.snapshotAt
                  ? String(cfoLatest.snapshot.snapshotAt)
                  : "—"
              }
            />
            <KeyValue
              label="Last agent run status"
              value={cfoLatest.lastAgentRunStatus || "n/a"}
            />
          </div>
          <div className="border-t border-border px-6 py-3 text-xs">
            <a
              href="/operations/pending-payments"
              data-testid="cfo-pending-payments-link"
              className="text-primary underline-offset-2 hover:underline"
            >
              View pending payments →
            </a>
            <span className="ml-2 text-muted-foreground">
              (read-only diagnostic; no action buttons)
            </span>
          </div>
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="cfo-recs-only-banner"
          >
            <strong>Recommendations-only.</strong> No "Send Report" /
            "Trigger Refund" / "Apply Discount" / "Run Agent" /
            "Auto-collect" buttons exist on this page.
          </div>
        </section>
      )}

      {dataAnalystLatest && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="data-analyst-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Data Analyst Agent V1 — Funnel & Operational Snapshot
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Recommendations-only. Deterministic daily aggregation of
                lead → call → confirmed → delivered → reorder funnel,
                conversion rates, top geographic states, day-of-week
                order distribution, and operational anomaly alert codes.
                The agent NEVER triggers WhatsApp, calls, payments,
                shipments, or discounts; downstream gates (Phase 5D /
                5E / 7E-Live-B / 7G-Live) remain the only paths to real
                customer action.
              </p>
            </div>
            <StatusPill tone="success">Recs-only</StatusPill>
          </div>
          {dataAnalystLatest.snapshot ? (
            <>
              <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5 text-xs">
                <KeyValue
                  label="Leads (30d)"
                  value={String(dataAnalystLatest.snapshot.leadCount30d)}
                />
                <KeyValue
                  label="Calls (30d)"
                  value={String(dataAnalystLatest.snapshot.callCount30d)}
                />
                <KeyValue
                  label="Confirmed (30d)"
                  value={String(
                    dataAnalystLatest.snapshot.confirmedOrderCount30d,
                  )}
                />
                <KeyValue
                  label="Delivered (30d)"
                  value={String(
                    dataAnalystLatest.snapshot.deliveredOrderCount30d,
                  )}
                />
                <KeyValue
                  label="Reorders (30d)"
                  value={String(dataAnalystLatest.snapshot.reorderCount30d)}
                />
              </div>
              <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                <KeyValue
                  label="Lead → Call"
                  value={(
                    dataAnalystLatest.snapshot.leadToCallRate * 100
                  ).toFixed(1) + "%"}
                />
                <KeyValue
                  label="Call → Confirmed"
                  value={(
                    dataAnalystLatest.snapshot.callToConfirmedRate * 100
                  ).toFixed(1) + "%"}
                />
                <KeyValue
                  label="Confirmed → Delivered"
                  value={(
                    dataAnalystLatest.snapshot.confirmedToDeliveredRate * 100
                  ).toFixed(1) + "%"}
                />
                <KeyValue
                  label="Delivered → Reorder"
                  value={(
                    dataAnalystLatest.snapshot.deliveredToReorderRate * 100
                  ).toFixed(1) + "%"}
                />
              </div>
              {dataAnalystLatest.snapshot.topStates.length > 0 && (
                <div className="border-t border-border px-6 py-4 overflow-x-auto">
                  <p className="text-xs font-medium mb-2">
                    Top states by order volume (30d)
                  </p>
                  <table className="min-w-full text-left text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-2 pr-4">State</th>
                        <th className="py-2 pr-4">Orders</th>
                        <th className="py-2 pr-4">Revenue</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dataAnalystLatest.snapshot.topStates.map(
                        (row) => (
                          <tr
                            key={row.state}
                            data-testid="data-analyst-state-row"
                          >
                            <td className="py-2 pr-4">{row.state}</td>
                            <td className="py-2 pr-4">
                              {String(row.order_count)}
                            </td>
                            <td className="py-2 pr-4">₹{row.revenue}</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="border-t border-border px-6 py-4 overflow-x-auto">
                <p className="text-xs font-medium mb-2">
                  Day-of-week order counts (30d)
                </p>
                <div className="grid grid-cols-7 gap-2 text-xs">
                  {(
                    [
                      "mon",
                      "tue",
                      "wed",
                      "thu",
                      "fri",
                      "sat",
                      "sun",
                    ] as const
                  ).map((day) => (
                    <div
                      key={day}
                      className="rounded border border-border px-2 py-2"
                      data-testid="data-analyst-dow-cell"
                    >
                      <div className="text-muted-foreground">{day}</div>
                      <div className="text-base font-semibold">
                        {String(
                          dataAnalystLatest.snapshot?.dayOfWeekCounts?.[
                            day
                          ] ?? 0,
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="border-t border-border px-6 py-4">
                <p className="text-xs font-medium mb-2">Active alerts</p>
                <div className="flex flex-wrap gap-2">
                  {dataAnalystLatest.snapshot.alerts.map((alert) => (
                    <span
                      key={alert}
                      data-testid="data-analyst-alert-pill"
                      className="rounded-full border border-border px-2 py-1 text-xs"
                    >
                      {alert}
                    </span>
                  ))}
                </div>
                {dataAnalystLatest.snapshot.alertText && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {dataAnalystLatest.snapshot.alertText}
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="px-6 py-4 text-xs text-muted-foreground">
              No Data Analyst snapshot yet. The daily Celery task will
              produce one at the configured time.
            </div>
          )}
          <div className="px-6 py-3 grid gap-2 sm:grid-cols-2 text-xs">
            <KeyValue
              label="Snapshot timestamp"
              value={
                dataAnalystLatest.snapshot?.snapshotAt
                  ? String(dataAnalystLatest.snapshot.snapshotAt)
                  : "—"
              }
            />
            <KeyValue
              label="Last agent run status"
              value={dataAnalystLatest.lastAgentRunStatus || "n/a"}
            />
          </div>
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="data-analyst-recs-only-banner"
          >
            <strong>Recommendations-only.</strong> No "Send Report" /
            "Trigger Funnel Fix" / "Apply Discount" / "Run Agent" /
            "Auto-rebalance" buttons exist on this page.
          </div>
        </section>
      )}

      {callingTeamLeaderLatest && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="calling-team-leader-agent-v1-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Calling Team Leader Agent V1
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Recommendations-only. Deterministic daily aggregation of
                call counts, connection rate, avg duration, outcome
                breakdown, per-agent metrics, and transcript backlog.
                The agent NEVER triggers calls, WhatsApp, payments, or
                shipments; downstream gates (Phase 5D / 5E / 7E-Live-B /
                7G-Live) remain the only paths to real customer action.
              </p>
            </div>
            <StatusPill tone="success">Recs-only</StatusPill>
          </div>
          {callingTeamLeaderLatest.snapshot ? (
            <>
              <div className="px-6 py-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5 text-xs">
                <KeyValue
                  label="Calls 24h"
                  value={String(
                    callingTeamLeaderLatest.snapshot.callCount24h,
                  )}
                />
                <KeyValue
                  label="Calls 7d"
                  value={String(
                    callingTeamLeaderLatest.snapshot.callCount7d,
                  )}
                />
                <KeyValue
                  label="Calls 30d"
                  value={String(
                    callingTeamLeaderLatest.snapshot.callCount30d,
                  )}
                />
                <KeyValue
                  label="Connection rate"
                  value={(
                    callingTeamLeaderLatest.snapshot.connectionRate30d *
                    100
                  ).toFixed(1) + "%"}
                />
                <KeyValue
                  label="Avg duration"
                  value={
                    callingTeamLeaderLatest.snapshot.avgDurationSeconds30d.toFixed(
                      0,
                    ) + "s"
                  }
                />
                <KeyValue
                  label="Transcript backlog"
                  value={String(
                    callingTeamLeaderLatest.snapshot.transcriptBacklogCount,
                  )}
                />
              </div>
              {Object.keys(
                callingTeamLeaderLatest.snapshot.outcomeBreakdown,
              ).length > 0 && (
                <div className="border-t border-border px-6 py-4 overflow-x-auto">
                  <p className="text-xs font-medium mb-2">
                    Outcome breakdown (Call.status, 30d)
                  </p>
                  <table className="min-w-full text-left text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-2 pr-4">Status</th>
                        <th className="py-2 pr-4">Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        callingTeamLeaderLatest.snapshot.outcomeBreakdown,
                      ).map(([status, count]) => (
                        <tr
                          key={status}
                          data-testid="calling-team-leader-outcome-row"
                        >
                          <td className="py-2 pr-4">{status}</td>
                          <td className="py-2 pr-4">{String(count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {callingTeamLeaderLatest.snapshot.agentBreakdown.length >
              0 ? (
                <div className="border-t border-border px-6 py-4 overflow-x-auto">
                  <p className="text-xs font-medium mb-2">
                    Top agents (30d)
                  </p>
                  <table className="min-w-full text-left text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-2 pr-4">Agent</th>
                        <th className="py-2 pr-4">Calls</th>
                        <th className="py-2 pr-4">Connection</th>
                        <th className="py-2 pr-4">Avg duration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {callingTeamLeaderLatest.snapshot.agentBreakdown.map(
                        (row) => (
                          <tr
                            key={row.agent_id || row.agent_label}
                            data-testid="calling-team-leader-agent-row"
                          >
                            <td className="py-2 pr-4">{row.agent_label}</td>
                            <td className="py-2 pr-4">
                              {String(row.call_count)}
                            </td>
                            <td className="py-2 pr-4">
                              {(row.connection_rate * 100).toFixed(1) + "%"}
                            </td>
                            <td className="py-2 pr-4">
                              {row.avg_duration_seconds.toFixed(0) + "s"}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="border-t border-border px-6 py-4 text-xs text-muted-foreground">
                  No agent attribution field — per-agent metrics
                  unavailable in V1.
                </div>
              )}
              <div className="border-t border-border px-6 py-4">
                <p className="text-xs font-medium mb-2">Active alerts</p>
                <div className="flex flex-wrap gap-2">
                  {callingTeamLeaderLatest.snapshot.alerts.map((alert) => (
                    <span
                      key={alert}
                      data-testid="calling-team-leader-alert-pill"
                      className="rounded-full border border-border px-2 py-1 text-xs"
                    >
                      {alert}
                    </span>
                  ))}
                </div>
                {callingTeamLeaderLatest.snapshot.alertText && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {callingTeamLeaderLatest.snapshot.alertText}
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="px-6 py-4 text-xs text-muted-foreground">
              No Calling Team Leader snapshot yet. The daily Celery task
              will produce one at the configured time.
            </div>
          )}
          <div className="px-6 py-3 grid gap-2 sm:grid-cols-2 text-xs">
            <KeyValue
              label="Snapshot timestamp"
              value={
                callingTeamLeaderLatest.snapshot?.snapshotAt
                  ? String(callingTeamLeaderLatest.snapshot.snapshotAt)
                  : "—"
              }
            />
            <KeyValue
              label="Last agent run status"
              value={
                callingTeamLeaderLatest.lastAgentRunStatus || "n/a"
              }
            />
          </div>
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="calling-team-leader-recs-only-banner"
          >
            <strong>Recommendations-only.</strong> No "Trigger Call" /
            "Reassign Agent" / "Send Coaching Note" / "Run Agent" /
            "Auto-dial" buttons exist on this page.
          </div>
        </section>
      )}

      {(phase7iFinalAuditLockReadiness || phase7iFinalAuditLocks) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase7i-final-audit-lock-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 7I Final Audit Lock
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 7I — <strong>lock-only meta-audit</strong> over
                the full controlled Phase 7 chain: Phase 7D Razorpay
                TEST execution + Phase 7E-Live-A internal allowed-list
                WhatsApp one-shot send + Phase 7G Delhivery TEST/MOCK
                courier execution + Phase 7H courier execution
                evidence lock. Approval flips status to{" "}
                <code>locked</code> and freezes the composite snapshot.
                Phase 7I NEVER calls Razorpay / Meta Cloud /
                Delhivery / Vapi, NEVER sends or queues WhatsApp,
                NEVER creates a <code>Shipment</code> / AWB / payment
                link, NEVER captures, NEVER refunds, NEVER sends a
                customer notification, NEVER mutates real{" "}
                <code>Order</code> / <code>Payment</code> /{" "}
                <code>Customer</code> / <code>Lead</code> /{" "}
                <code>DiscountOfferLog</code> rows, NEVER edits any{" "}
                <code>.env*</code> file. Review state changes are
                CLI-only. Phase 7E-Live-B (real customer WhatsApp
                send) and Phase 7G-Live (real customer courier
                execution) remain <strong>not approved</strong>.
              </p>
            </div>
            {phase7iFinalAuditLockReadiness && (
              <div data-testid="phase7i-status-badge">
                <StatusPill
                  tone={
                    phase7iFinalAuditLockReadiness.killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase7iFinalAuditLockReadiness.killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase7iFinalAuditLockReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={phase7iFinalAuditLockReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={phase7iFinalAuditLockReadiness.status}
              />
              <KeyValue
                label="Eligible 7H locks"
                value={String(
                  phase7iFinalAuditLockReadiness.eligiblePhase7HEvidenceLockCount,
                )}
              />
              <KeyValue
                label="Eligible 7E-Live attempts"
                value={String(
                  phase7iFinalAuditLockReadiness.eligiblePhase7ELiveAttemptCount,
                )}
              />
              <KeyValue
                label="Eligible 7G attempts"
                value={String(
                  phase7iFinalAuditLockReadiness.eligiblePhase7GAttemptCount,
                )}
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue label="Sends WhatsApp" value="No" />
              <KeyValue label="Creates AWB" value="No" />
              <KeyValue label="Creates Shipment row" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Business mutation" value="No" />
              <KeyValue
                label="Phase 7E-Live-B approved"
                value="No"
              />
              <KeyValue label="Phase 7G-Live approved" value="No" />
            </div>
          )}
          {phase7iFinalAuditLocks &&
            phase7iFinalAuditLocks.items.length > 0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase7iFinalAuditLocks.items.map((lock) => (
                  <div
                    key={lock.id}
                    className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6 py-1 border-b border-border last:border-0"
                  >
                    <span>
                      id=<strong>{lock.id}</strong>
                    </span>
                    <span>status={lock.status}</span>
                    <span>
                      7D={lock.sourcePhase7DAttemptId}
                    </span>
                    <span>
                      7E-Live={lock.sourcePhase7ELiveSendAttemptId}
                    </span>
                    <span>
                      7G={lock.sourcePhase7GAttemptId}
                    </span>
                    <span>
                      7H={lock.sourcePhase7HEvidenceLockId}
                    </span>
                  </div>
                ))}
              </div>
            )}
          {phase7iFinalAuditLockReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {phase7iFinalAuditLockReadiness.nextAction}
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase7i-cli-only-banner"
          >
            <strong>Lock-only · CLI-only Review.</strong> No "Lock
            Final Audit" / "Approve Lock" / "Reject Lock" / "Archive
            Lock" / "Execute" / "Send WhatsApp" / "Call Razorpay" /
            "Call Delhivery" / "Notify" / "Refund" / "Capture" /
            "Apply Mutation" / "Go Live" / "Edit .env" buttons exist
            on this page. Phase 7I approval is a status transition
            only — it does NOT enable any provider call.
          </div>
        </section>
      )}

      {(phase8aPaymentOrderMutationSandboxReadiness ||
        phase8aPaymentOrderMutationSandboxGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase8a-payment-order-mutation-sandbox-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 8A Payment → Order Mutation Sandbox Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 8A — <strong>sandbox-only dry-runs</strong>{" "}
                against synthetic-only references (
                <code>phase8a::sandbox::...</code> /{" "}
                <code>phase8a-sandbox-...</code> /{" "}
                <code>sandbox::...</code>). Designs how a Razorpay
                paid event could map to a synthetic{" "}
                <code>Order</code> status change in a future phase.
                Phase 8A NEVER mutates real <code>Order</code> /{" "}
                <code>Payment</code> / <code>Shipment</code> /{" "}
                <code>Customer</code> / <code>Lead</code> /{" "}
                <code>DiscountOfferLog</code> rows, NEVER calls
                Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends
                or queues WhatsApp, NEVER creates a payment link,
                NEVER captures, NEVER refunds, NEVER sends a customer
                notification, NEVER edits any <code>.env*</code>{" "}
                file. Review state changes are CLI-only. Approval
                only unlocks a future Phase 8B review — it does NOT
                enable any real mutation. Phase 8B (real
                payment-to-order mutation) remains{" "}
                <strong>not approved</strong>.
              </p>
            </div>
            {phase8aPaymentOrderMutationSandboxReadiness && (
              <div data-testid="phase8a-status-badge">
                <StatusPill
                  tone={
                    phase8aPaymentOrderMutationSandboxReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase8aPaymentOrderMutationSandboxReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase8aPaymentOrderMutationSandboxReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={phase8aPaymentOrderMutationSandboxReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={phase8aPaymentOrderMutationSandboxReadiness.status}
              />
              <KeyValue
                label="Phase 8A flag"
                value={
                  phase8aPaymentOrderMutationSandboxReadiness
                    .phase8APaymentOrderMutationSandboxEnabled
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Eligible 7I locks"
                value={String(
                  phase8aPaymentOrderMutationSandboxReadiness
                    .eligiblePhase7ILockCount,
                )}
              />
              <KeyValue label="Mutates Order" value="No" />
              <KeyValue label="Mutates Payment" value="No" />
              <KeyValue label="Mutates Shipment" value="No" />
              <KeyValue label="Sends WhatsApp" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue
                label="Synthetic order required"
                value="Yes"
              />
              <KeyValue label="Manual review" value="Yes" />
              <KeyValue
                label="Frontend can execute"
                value="No"
              />
              <KeyValue
                label="API can execute"
                value="No"
              />
            </div>
          )}
          {phase8aPaymentOrderMutationSandboxGates &&
            phase8aPaymentOrderMutationSandboxGates.items.length > 0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase8aPaymentOrderMutationSandboxGates.items.map(
                  (gate) => (
                    <div
                      key={gate.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5 py-1 border-b border-border last:border-0"
                    >
                      <span>
                        id=<strong>{gate.id}</strong>
                      </span>
                      <span>status={gate.status}</span>
                      <span>
                        7I={gate.sourcePhase7ILockId}
                      </span>
                      <span>
                        7D={gate.sourcePhase7DAttemptId}
                      </span>
                      <span>
                        sandboxOnly=
                        {gate.sandboxOnly ? "yes" : "no"}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {phase8aPaymentOrderMutationSandboxReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  phase8aPaymentOrderMutationSandboxReadiness
                    .nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase8a-cli-only-banner"
          >
            <strong>Sandbox-only · CLI-only Review.</strong> No
            "Approve Gate" / "Reject Gate" / "Archive Gate" /
            "Execute Dry-Run" / "Apply Mutation" / "Mark Paid" /
            "Confirm Order" / "Send WhatsApp" / "Call Razorpay" /
            "Call Delhivery" / "Notify Customer" / "Refund" /
            "Capture" / "Go Live" / "Edit .env" buttons exist on this
            page. Phase 8A approval is a status transition only — it
            does NOT enable any real mutation.
          </div>
        </section>
      )}

      {(phase8bPaymentOrderMutationReviewReadiness ||
        phase8bPaymentOrderMutationReviewGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase8b-payment-order-mutation-review-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 8B Payment → Order Mutation Review Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 8B — <strong>review / dry-run only</strong>{" "}
                contract on top of an approved Phase 8A sandbox gate.
                Dry-runs against review-only references (
                <code>phase8b::review::order::...</code> /{" "}
                <code>phase8b-review-...</code> /{" "}
                <code>review::phase8b::...</code>). Approval flips
                status to{" "}
                <code>
                  approved_for_future_phase8c_controlled_mutation_review
                </code>{" "}
                — it does <strong>NOT</strong> enable any real
                mutation. Phase 8B NEVER mutates real{" "}
                <code>Order</code> / <code>Payment</code> /{" "}
                <code>Shipment</code> / <code>Customer</code> /{" "}
                <code>Lead</code> / <code>DiscountOfferLog</code>{" "}
                rows, NEVER calls Razorpay / Meta Cloud / Delhivery /
                Vapi, NEVER sends or queues WhatsApp, NEVER creates a
                payment link, NEVER captures, NEVER refunds, NEVER
                sends a customer notification, NEVER edits any{" "}
                <code>.env*</code> file. Review state changes are
                CLI-only. Phase 8C (controlled real mutation) remains{" "}
                <strong>not approved</strong>.
              </p>
            </div>
            {phase8bPaymentOrderMutationReviewReadiness && (
              <div data-testid="phase8b-status-badge">
                <StatusPill
                  tone={
                    phase8bPaymentOrderMutationReviewReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase8bPaymentOrderMutationReviewReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase8bPaymentOrderMutationReviewReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={phase8bPaymentOrderMutationReviewReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={phase8bPaymentOrderMutationReviewReadiness.status}
              />
              <KeyValue
                label="Phase 8B flag"
                value={
                  phase8bPaymentOrderMutationReviewReadiness
                    .phase8BPaymentOrderMutationReviewGateEnabled
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Eligible 8A gates"
                value={String(
                  phase8bPaymentOrderMutationReviewReadiness
                    .eligiblePhase8AGateCount,
                )}
              />
              <KeyValue
                label="Real mutation allowed"
                value="No"
              />
              <KeyValue
                label="Real order mutation"
                value="No"
              />
              <KeyValue
                label="Real payment mutation"
                value="No"
              />
              <KeyValue label="WhatsApp allowed" value="No" />
              <KeyValue label="Courier allowed" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue
                label="Future Phase 8C required"
                value="Yes"
              />
              <KeyValue
                label="Phase 8C approved"
                value="No"
              />
              <KeyValue
                label="Real customer automation"
                value="Not approved"
              />
              <KeyValue label="Manual review" value="Yes" />
              <KeyValue
                label="Frontend can execute"
                value="No"
              />
              <KeyValue
                label="API can execute"
                value="No"
              />
            </div>
          )}
          {phase8bPaymentOrderMutationReviewGates &&
            phase8bPaymentOrderMutationReviewGates.items.length > 0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase8bPaymentOrderMutationReviewGates.items.map(
                  (gate) => (
                    <div
                      key={gate.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6 py-1 border-b border-border last:border-0"
                    >
                      <span>
                        id=<strong>{gate.id}</strong>
                      </span>
                      <span>status={gate.status}</span>
                      <span>
                        8A={gate.sourcePhase8AGateId}
                      </span>
                      <span>
                        7I={gate.sourcePhase7ILockId}
                      </span>
                      <span>
                        7D={gate.sourcePhase7DAttemptId}
                      </span>
                      <span>
                        dryRun=
                        {gate.dryRunPassed ? "passed" : "pending"}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {phase8bPaymentOrderMutationReviewReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  phase8bPaymentOrderMutationReviewReadiness
                    .nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase8b-cli-only-banner"
          >
            <strong>Review-only · CLI-only Review.</strong> No
            "Approve Gate" / "Reject Gate" / "Archive Gate" /
            "Execute Dry-Run" / "Apply Mutation" / "Mark Paid" /
            "Confirm Order" / "Send WhatsApp" / "Call Razorpay" /
            "Call Delhivery" / "Notify Customer" / "Refund" /
            "Capture" / "Go Live" / "Approve Phase 8C" / "Edit .env"
            buttons exist on this page. Phase 8B approval is a
            status transition only — it does NOT enable any real
            mutation.
          </div>
        </section>
      )}

      {(phase8cPaymentOrderControlledMutationReadiness ||
        phase8cPaymentOrderControlledMutationGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase8c-payment-order-controlled-mutation-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 8C Controlled Payment → Order Mutation
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 8C — <strong>CLI-only one-shot</strong>{" "}
                controlled mutation against a single explicitly
                selected internal / sandbox / test{" "}
                <code>Order</code> + <code>Payment</code> pair.
                Execute requires three env flags ALL true, the kill
                switch enabled, a structured Director sign-off UTC
                window (<code>BEGIN_UTC=</code> / <code>END_UTC=</code>,
                ≤ 15 min), and runtime proof that the target rows
                are not real customer data (reference / id /{" "}
                <code>raw_response.phase8c_sandbox</code> markers).
                The only mutation performed is writing the target{" "}
                <code>Order.payment_status</code> and{" "}
                <code>Payment.status</code> to <code>Paid</code>.
                Phase 8C NEVER calls Razorpay / Meta Cloud /
                Delhivery / Vapi, NEVER sends or queues WhatsApp,
                NEVER creates a <code>Shipment</code> / AWB /
                payment link, NEVER captures / refunds, NEVER sends
                a customer notification, NEVER mutates real{" "}
                <code>Customer</code> / <code>Lead</code> /{" "}
                <code>Shipment</code> /{" "}
                <code>DiscountOfferLog</code> rows, NEVER edits any{" "}
                <code>.env*</code> file. Review state changes are
                CLI-only. Phase 7E-Live-B / 7G-Live / broad customer
                automation remain <strong>not approved</strong>.
              </p>
            </div>
            {phase8cPaymentOrderControlledMutationReadiness && (
              <div data-testid="phase8c-status-badge">
                <StatusPill
                  tone={
                    phase8cPaymentOrderControlledMutationReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase8cPaymentOrderControlledMutationReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase8cPaymentOrderControlledMutationReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={
                  phase8cPaymentOrderControlledMutationReadiness.phase
                }
              />
              <KeyValue
                label="Status"
                value={
                  phase8cPaymentOrderControlledMutationReadiness.status
                }
              />
              <KeyValue
                label="Phase 8C gate flag"
                value={
                  phase8cPaymentOrderControlledMutationReadiness.phase8CGateEnabled
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Director approved"
                value={
                  phase8cPaymentOrderControlledMutationReadiness.phase8CDirectorApproved
                    ? "Approved"
                    : "Not approved (safe)"
                }
              />
              <KeyValue
                label="Allow internal mutation"
                value={
                  phase8cPaymentOrderControlledMutationReadiness.phase8CAllowInternalMutation
                    ? "Allowed"
                    : "Locked off (safe)"
                }
              />
              <KeyValue
                label="Eligible 8B gates"
                value={String(
                  phase8cPaymentOrderControlledMutationReadiness
                    .eligiblePhase8BGateCount,
                )}
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue label="Sends WhatsApp" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Creates Shipment" value="No" />
              <KeyValue label="Creates AWB" value="No" />
              <KeyValue label="Captures payment" value="No" />
              <KeyValue label="Refunds payment" value="No" />
              <KeyValue
                label="Real customer automation"
                value="Not approved"
              />
              <KeyValue
                label="Frontend can execute"
                value="No"
              />
              <KeyValue
                label="API can execute"
                value="No"
              />
            </div>
          )}
          {phase8cPaymentOrderControlledMutationGates &&
            phase8cPaymentOrderControlledMutationGates.items.length > 0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase8cPaymentOrderControlledMutationGates.items.map(
                  (gate) => (
                    <div
                      key={gate.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6 py-1 border-b border-border last:border-0"
                    >
                      <span>
                        id=<strong>{gate.id}</strong>
                      </span>
                      <span>status={gate.status}</span>
                      <span>
                        8B={gate.sourcePhase8BGateId}
                      </span>
                      <span>
                        7I={gate.sourcePhase7ILockId}
                      </span>
                      <span>
                        dryRun=
                        {gate.dryRunPassed ? "passed" : "pending"}
                      </span>
                      <span>
                        old/new=
                        {gate.proposedOldOrderStatus.slice(0, 18)}
                        {" → "}
                        {gate.proposedNewOrderStatus.slice(0, 18)}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {phase8cPaymentOrderControlledMutationReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  phase8cPaymentOrderControlledMutationReadiness
                    .nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase8c-cli-only-banner"
          >
            <strong>CLI-only One-shot Controlled Mutation.</strong>{" "}
            No "Execute" / "Mark Paid" / "Apply Mutation" /
            "Rollback" / "Send WhatsApp" / "Create Shipment" /
            "Capture" / "Refund" / "Notify Customer" / "Call
            Razorpay" / "Call Delhivery" / "Approve Phase 8C" / "Go
            Live" / "Edit .env" buttons exist on this page. Phase 8C
            execute is CLI-only and refuses unless every safety gate
            is satisfied.
          </div>
        </section>
      )}

      {(phase8dControlledMutationEvidenceLockReadiness ||
        phase8dControlledMutationEvidenceLocks) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase8d-controlled-mutation-evidence-lock-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 8D Controlled Mutation Evidence Lock
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 8D — <strong>lock-only meta-audit</strong>{" "}
                over the completed Phase 8C executed +{" "}
                <code>rolled_back</code> chain. Freezes the full
                status timeline (Pending → Paid → Pending), the
                target Order + Payment ids, the Director sign-off
                window validity, and every locked-False contract
                boolean into a single immutable evidence row.
                Approval flips status to <code>locked</code> only
                — it does <strong>NOT</strong> execute Phase 8C
                again, NEVER rolls back Phase 8C again. Phase 8D
                NEVER calls Razorpay / Meta Cloud / Delhivery /
                Vapi, NEVER sends or queues WhatsApp, NEVER
                creates a <code>Shipment</code> / AWB / payment
                link, NEVER captures / refunds, NEVER sends a
                customer notification, NEVER mutates real{" "}
                <code>Order</code> / <code>Payment</code> /{" "}
                <code>Customer</code> / <code>Lead</code> /{" "}
                <code>Shipment</code> /{" "}
                <code>DiscountOfferLog</code> /{" "}
                <code>WhatsAppMessage</code> rows, NEVER edits
                any <code>.env*</code> file. Review state changes
                are CLI-only.
              </p>
            </div>
            {phase8dControlledMutationEvidenceLockReadiness && (
              <div data-testid="phase8d-status-badge">
                <StatusPill
                  tone={
                    phase8dControlledMutationEvidenceLockReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase8dControlledMutationEvidenceLockReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase8dControlledMutationEvidenceLockReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={
                  phase8dControlledMutationEvidenceLockReadiness.phase
                }
              />
              <KeyValue
                label="Status"
                value={
                  phase8dControlledMutationEvidenceLockReadiness.status
                }
              />
              <KeyValue
                label="Eligible 8C gates"
                value={String(
                  phase8dControlledMutationEvidenceLockReadiness
                    .eligiblePhase8CGateCount,
                )}
              />
              <KeyValue
                label="Executes Phase 8C again"
                value="No"
              />
              <KeyValue
                label="Rolls back Phase 8C again"
                value="No"
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue label="Sends WhatsApp" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Creates Shipment" value="No" />
              <KeyValue label="Captures payment" value="No" />
              <KeyValue label="Refunds payment" value="No" />
              <KeyValue label="Mutates Order" value="No" />
              <KeyValue label="Mutates Payment" value="No" />
              <KeyValue
                label="Mutates Customer/Lead"
                value="No"
              />
              <KeyValue
                label="Frontend can execute"
                value="No"
              />
              <KeyValue
                label="API can execute"
                value="No"
              />
            </div>
          )}
          {phase8dControlledMutationEvidenceLocks &&
            phase8dControlledMutationEvidenceLocks.items.length > 0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase8dControlledMutationEvidenceLocks.items.map(
                  (lock) => (
                    <div
                      key={lock.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6 py-1 border-b border-border last:border-0"
                      data-testid="phase8d-lock-row"
                    >
                      <span>
                        id=<strong>{lock.id}</strong>
                      </span>
                      <span>status={lock.status}</span>
                      <span>
                        8C={lock.sourcePhase8CGateId}
                      </span>
                      <span>
                        attempt={lock.sourcePhase8CAttemptId}
                      </span>
                      <span>
                        timeline=
                        {lock.oldOrderStatusSnapshot}
                        {" → "}
                        {lock.executedOrderStatusSnapshot}
                        {" → "}
                        {lock.finalOrderStatusSnapshot}
                      </span>
                      <span>
                        rollback=
                        {lock.rollbackCompletedSnapshot
                          ? "completed"
                          : "missing"}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {phase8dControlledMutationEvidenceLockReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  phase8dControlledMutationEvidenceLockReadiness
                    .nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase8d-cli-only-banner"
          >
            <strong>Lock-only · CLI-only Review.</strong> No "Lock
            Evidence" / "Reject Lock" / "Archive Lock" / "Re-execute
            Phase 8C" / "Re-rollback Phase 8C" / "Apply Mutation" /
            "Mark Paid" / "Send WhatsApp" / "Create Shipment" /
            "Capture" / "Refund" / "Notify Customer" / "Call
            Razorpay" / "Call Delhivery" / "Go Live" / "Edit .env"
            buttons exist on this page. Phase 8D approval is a
            status transition only — it does NOT execute Phase 8C
            again and does NOT authorise any provider call.
          </div>
        </section>
      )}

      {(phase8eRealCustomerPaymentOrderPilotReadiness ||
        phase8eRealCustomerPaymentOrderPilotGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase8e-real-customer-payment-order-pilot-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 8E Real Customer Payment → Order Pilot
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 8E — <strong>review / dry-run only</strong>{" "}
                against ONE explicit real customer{" "}
                <code>Order</code> + <code>Payment</code> candidate.
                Approval flips status to{" "}
                <code>
                  approved_for_future_phase8f_real_customer_controlled_mutation
                </code>{" "}
                — it does <strong>NOT</strong> execute mutation and
                does NOT authorise any provider call. Phase 8E
                NEVER mutates real <code>Order</code> /{" "}
                <code>Payment</code> / <code>Customer</code> /{" "}
                <code>Lead</code> / <code>Shipment</code> /{" "}
                <code>DiscountOfferLog</code> /{" "}
                <code>WhatsAppMessage</code> rows, NEVER calls
                Razorpay / Meta Cloud / Delhivery / Vapi, NEVER
                sends or queues WhatsApp, NEVER creates a{" "}
                <code>Shipment</code> / AWB / payment link, NEVER
                captures / refunds, NEVER sends a customer
                notification, NEVER edits any <code>.env*</code>{" "}
                file. Customer name + phone are masked
                (last-4 only); raw provider payload is never
                exposed. Phase 8C sandbox rows are explicitly
                rejected at candidate selection. Phase 8F (real
                customer controlled mutation) remains{" "}
                <strong>not approved</strong>.
              </p>
            </div>
            {phase8eRealCustomerPaymentOrderPilotReadiness && (
              <div data-testid="phase8e-status-badge">
                <StatusPill
                  tone={
                    phase8eRealCustomerPaymentOrderPilotReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase8eRealCustomerPaymentOrderPilotReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase8eRealCustomerPaymentOrderPilotReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={
                  phase8eRealCustomerPaymentOrderPilotReadiness.phase
                }
              />
              <KeyValue
                label="Status"
                value={
                  phase8eRealCustomerPaymentOrderPilotReadiness.status
                }
              />
              <KeyValue
                label="Phase 8E flag"
                value={
                  phase8eRealCustomerPaymentOrderPilotReadiness
                    .phase8EPaymentOrderPilotEnabled
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Eligible 8D locks"
                value={String(
                  phase8eRealCustomerPaymentOrderPilotReadiness
                    .eligiblePhase8DLockCount,
                )}
              />
              <KeyValue
                label="Real mutation allowed"
                value="No"
              />
              <KeyValue
                label="Real order mutation"
                value="No"
              />
              <KeyValue
                label="Real payment mutation"
                value="No"
              />
              <KeyValue label="WhatsApp allowed" value="No" />
              <KeyValue label="Courier allowed" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue
                label="Future Phase 8F required"
                value="Yes"
              />
              <KeyValue
                label="Phase 8F approved"
                value="No"
              />
              <KeyValue
                label="Real customer automation"
                value="Not approved"
              />
              <KeyValue label="Manual review" value="Yes" />
              <KeyValue
                label="Frontend can execute"
                value="No"
              />
              <KeyValue
                label="API can execute"
                value="No"
              />
            </div>
          )}
          {phase8eRealCustomerPaymentOrderPilotGates &&
            phase8eRealCustomerPaymentOrderPilotGates.items.length >
              0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase8eRealCustomerPaymentOrderPilotGates.items.map(
                  (gate) => (
                    <div
                      key={gate.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6 py-1 border-b border-border last:border-0"
                    >
                      <span>
                        id=<strong>{gate.id}</strong>
                      </span>
                      <span>status={gate.status}</span>
                      <span>
                        8D={gate.sourcePhase8DLockId}
                      </span>
                      <span>
                        8C={gate.sourcePhase8CGateId}
                      </span>
                      <span>
                        candidate=
                        {gate.candidateOrderIdSnapshot
                          ? `${gate.candidateOrderIdSnapshot.slice(0, 14)}…`
                          : "—"}
                      </span>
                      <span>
                        dryRun=
                        {gate.dryRunPassed ? "passed" : "pending"}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {phase8eRealCustomerCandidatePool && (
            <div
              className="border-t border-border px-6 py-4 text-xs"
              data-testid="phase8e-candidate-pool-subsection"
            >
              <div className="font-semibold text-foreground mb-2">
                Phase 8E-Hotfix-1 Candidate Pool (read-only;
                masked)
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <KeyValue
                  label="Total linked pairs"
                  value={String(
                    phase8eRealCustomerCandidatePool.totalLinkedPairs,
                  )}
                />
                <KeyValue
                  label="Strict Pending/Pending"
                  value={String(
                    phase8eRealCustomerCandidatePool.eligibleStrictPendingPendingCount,
                  )}
                />
                <KeyValue
                  label="Partial/Pending review-only"
                  value={String(
                    phase8eRealCustomerCandidatePool.eligiblePartialPendingReviewOnlyCount,
                  )}
                />
                <KeyValue
                  label="Recommended"
                  value={String(
                    phase8eRealCustomerCandidatePool
                      .recommendedCandidates.length,
                  )}
                />
              </div>
              {phase8eRealCustomerCandidatePool.warnings.length >
                0 && (
                <ul className="mt-3 space-y-1 text-xs text-amber-700 dark:text-amber-300">
                  {phase8eRealCustomerCandidatePool.warnings
                    .filter((w) => !w.startsWith("Phase 8E is"))
                    .map((w) => (
                      <li key={w}>⚠ {w}</li>
                    ))}
                </ul>
              )}
              {phase8eRealCustomerCandidatePool
                .recommendedCandidates.length > 0 && (
                <div className="mt-3">
                  <div className="text-foreground font-medium mb-1">
                    Top recommended candidate (masked):
                  </div>
                  {(() => {
                    const top: SaasPhase8ERealCustomerCandidatePoolRow =
                      phase8eRealCustomerCandidatePool
                        .recommendedCandidates[0];
                    return (
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        <KeyValue
                          label="orderId"
                          value={top.orderId || "—"}
                        />
                        <KeyValue
                          label="paymentId"
                          value={top.paymentId || "—"}
                        />
                        <KeyValue
                          label="orderPaymentStatus"
                          value={top.orderPaymentStatus || "—"}
                        />
                        <KeyValue
                          label="paymentStatus"
                          value={top.paymentStatus || "—"}
                        />
                        <KeyValue
                          label="stage"
                          value={top.stage || "—"}
                        />
                        <KeyValue
                          label="phoneLast4"
                          value={top.phoneLast4 || "—"}
                        />
                        <KeyValue
                          label="amount"
                          value={String(top.amount)}
                        />
                        <KeyValue
                          label="recommendation"
                          value={top.recommendation}
                        />
                      </div>
                    );
                  })()}
                </div>
              )}
              {Object.keys(
                phase8eRealCustomerCandidatePool
                  .blockedCountsByReason,
              ).length > 0 && (
                <div className="mt-3 text-muted-foreground">
                  <span className="font-medium">
                    Blocked counts by reason:
                  </span>
                  {Object.entries(
                    phase8eRealCustomerCandidatePool
                      .blockedCountsByReason,
                  ).map(([reason, count]) => (
                    <span key={reason} className="ml-2">
                      <code>{reason}</code>=
                      <strong>{count as number}</strong>
                    </span>
                  ))}
                </div>
              )}
              <div className="mt-3 text-muted-foreground">
                Pool <strong>nextAction:</strong>{" "}
                <code>
                  {phase8eRealCustomerCandidatePool.nextAction}
                </code>
              </div>
            </div>
          )}
          {phase8eRealCustomerPaymentOrderPilotReadiness?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  phase8eRealCustomerPaymentOrderPilotReadiness
                    .nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase8e-cli-only-banner"
          >
            <strong>Review-only · CLI-only Review.</strong> No
            "Approve Gate" / "Reject Gate" / "Archive Gate" /
            "Select Candidate" / "Execute Dry-Run" / "Apply
            Mutation" / "Mark Paid" / "Confirm Order" / "Send
            WhatsApp" / "Call Razorpay" / "Call Delhivery" /
            "Notify Customer" / "Refund" / "Capture" / "Go Live" /
            "Approve Phase 8F" / "Edit .env" buttons exist on this
            page. Phase 8E approval is a status transition only —
            it does NOT execute any mutation and does NOT
            authorise any provider call.
          </div>
        </section>
      )}

      {(phase8fRealCustomerControlledMutationReadiness ||
        phase8fRealCustomerControlledMutationGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="phase8f-real-customer-controlled-mutation-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Phase 8F Controlled Real Customer Payment → Order
                Mutation
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 8F is the{" "}
                <strong>CLI-only one-shot controlled mutation</strong>{" "}
                path for the ONE Phase 8E-approved real customer{" "}
                <code>Order</code> + <code>Payment</code> candidate.
                Execute requires three Phase 8F env flags ALL true, a
                structured 15-min Director sign-off UTC window, the
                kill switch enabled,{" "}
                <code>--confirm-one-shot-real-mutation</code>, non-empty{" "}
                <code>--operator-name</code>. Approval alone does{" "}
                <strong>NOT</strong> execute. Phase 8F NEVER calls
                Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends
                or queues WhatsApp, NEVER creates a{" "}
                <code>Shipment</code> / AWB / payment link, NEVER
                captures / refunds, NEVER sends a customer
                notification, NEVER mutates <code>Customer</code> /{" "}
                <code>Lead</code> / <code>Shipment</code> /{" "}
                <code>DiscountOfferLog</code> /{" "}
                <code>WhatsAppMessage</code> rows, NEVER mutates{" "}
                <code>Order.state</code>, NEVER edits any{" "}
                <code>.env*</code> file. The only mutation is writing{" "}
                <code>Order.payment_status</code> +{" "}
                <code>Payment.status</code> to <code>Paid</code> on
                the named target rows.
              </p>
            </div>
            {phase8fRealCustomerControlledMutationReadiness && (
              <div data-testid="phase8f-status-badge">
                <StatusPill
                  tone={
                    phase8fRealCustomerControlledMutationReadiness
                      .killSwitch.enabled
                      ? "success"
                      : "warning"
                  }
                >
                  {phase8fRealCustomerControlledMutationReadiness
                    .killSwitch.enabled
                    ? "Kill switch active"
                    : "Kill switch DISABLED"}
                </StatusPill>
              </div>
            )}
          </div>
          {phase8fRealCustomerControlledMutationReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={
                  phase8fRealCustomerControlledMutationReadiness.phase
                }
              />
              <KeyValue
                label="Status"
                value={
                  phase8fRealCustomerControlledMutationReadiness.status
                }
              />
              <KeyValue
                label="Phase 8F gate flag"
                value={
                  phase8fRealCustomerControlledMutationReadiness
                    .phase8FFlags
                    .PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED
                    ? "Enabled"
                    : "Disabled (safe)"
                }
              />
              <KeyValue
                label="Director approved flag"
                value={
                  phase8fRealCustomerControlledMutationReadiness
                    .phase8FFlags
                    .PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION
                    ? "True"
                    : "False (safe)"
                }
              />
              <KeyValue
                label="Allow real mutation flag"
                value={
                  phase8fRealCustomerControlledMutationReadiness
                    .phase8FFlags
                    .PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION
                    ? "True"
                    : "False (safe)"
                }
              />
              <KeyValue
                label="Eligible 8E gates"
                value={String(
                  phase8fRealCustomerControlledMutationReadiness
                    .eligiblePhase8EGateCount,
                )}
              />
              <KeyValue
                label="Real customer mutation"
                value="Allowed only via CLI execute"
              />
              <KeyValue label="Mutates Order.state" value="No" />
              <KeyValue label="WhatsApp allowed" value="No" />
              <KeyValue label="Courier allowed" value="No" />
              <KeyValue
                label="Customer notification"
                value="No"
              />
              <KeyValue label="Calls Razorpay" value="No" />
              <KeyValue label="Calls Meta Cloud" value="No" />
              <KeyValue label="Calls Delhivery" value="No" />
              <KeyValue label="Creates Shipment" value="No" />
              <KeyValue label="Creates AWB" value="No" />
              <KeyValue
                label="Frontend can execute"
                value="No"
              />
              <KeyValue
                label="API can execute"
                value="No"
              />
            </div>
          )}
          {phase8fRealCustomerControlledMutationGates &&
            phase8fRealCustomerControlledMutationGates.items.length >
              0 && (
              <div className="border-t border-border px-6 py-4 text-xs">
                {phase8fRealCustomerControlledMutationGates.items.map(
                  (gate) => (
                    <div
                      key={gate.id}
                      className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6 py-1 border-b border-border last:border-0"
                    >
                      <span>
                        id=<strong>{gate.id}</strong>
                      </span>
                      <span>status={gate.status}</span>
                      <span>
                        8E={gate.sourcePhase8EGateId}
                      </span>
                      <span>
                        order=
                        {gate.selectedOrderIdSnapshot || "—"}
                      </span>
                      <span>
                        payment=
                        {gate.selectedPaymentIdSnapshot || "—"}
                      </span>
                      <span>
                        {gate.selectedOrderPaymentStatusSnapshot ||
                          "—"}{" "}
                        →{" "}
                        {gate.proposedOrderPaymentStatusSnapshot ||
                          "—"}
                      </span>
                    </div>
                  ),
                )}
              </div>
            )}
          {phase8fRealCustomerControlledMutationReadiness
            ?.nextAction && (
            <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
              <strong>nextAction:</strong>{" "}
              <code>
                {
                  phase8fRealCustomerControlledMutationReadiness
                    .nextAction
                }
              </code>
            </div>
          )}
          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase8f-cli-only-banner"
          >
            <strong>
              CLI-only one-shot controlled mutation.
            </strong>{" "}
            No "Approve Gate" / "Reject Gate" / "Archive Gate" /
            "Execute" / "Apply Mutation" / "Mark Paid" / "Confirm
            Order" / "Send WhatsApp" / "Queue WhatsApp" / "Call
            Razorpay" / "Call Meta" / "Call Delhivery" / "Notify
            Customer" / "Refund" / "Capture" / "Create Shipment" /
            "Create AWB" / "Go Live" / "Edit .env" buttons exist on
            this page. Phase 8F execute is exclusively driven via
            the CLI command{" "}
            <code>
              execute_phase8f_real_customer_controlled_mutation
            </code>
            , which itself refuses unless three env flags are true,
            a structured 15-min Director UTC window is provided,
            and the kill switch is enabled.
          </div>
        </section>
      )}

      {(mcpReadiness || mcpSecurityPosture || mcpTools || mcpInvocations) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="mcp-gateway-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Network className="h-5 w-5 text-primary" />
                MCP Gateway Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6M-0 — read-only foundation for the future
                Claude / ChatGPT / Codex MCP connector. MCP defaults
                are <strong>disabled / read-only</strong>; no write
                tools, no provider tools, no public endpoint, no raw
                secrets, no full PII.
              </p>
            </div>
            {mcpReadiness && (
              <StatusPill
                tone={
                  mcpReadiness.safeToStartPhase6M ? "success" : "warning"
                }
              >
                {mcpReadiness.mcpEnabled
                  ? "MCP enabled"
                  : "MCP disabled (safe)"}
              </StatusPill>
            )}
          </div>
          {mcpReadiness && (
            <McpReadinessCard readiness={mcpReadiness} />
          )}
          {mcpSecurityPosture && (
            <McpSecurityPostureCard posture={mcpSecurityPosture} />
          )}
          {mcpTools && <McpToolsTable response={mcpTools} />}
          {mcpInvocations && (
            <McpInvocationsTable response={mcpInvocations} />
          )}
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Run Tool" / "Send" / "Execute"
            buttons exist on this page. Even the simulator runs only
            the registered read-only tools through the Phase 6M-0
            executor (no provider call, no business mutation).
          </div>
        </section>
      )}

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Panel title="Blockers & Warnings" icon={ShieldCheck}>
          <IssueList items={overview.blockers} empty="No blockers" />
          <IssueList items={overview.warnings} empty="No warnings" />
        </Panel>
        <Panel title="Audit Timeline" icon={CheckCircle2}>
          {overview.auditTimeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No SaaS admin audit events yet.
            </p>
          ) : (
            <div className="space-y-3">
              {overview.auditTimeline.map((event) => (
                <div
                  key={event.id}
                  className="rounded-md border border-border bg-muted/20 p-3"
                >
                  <div className="text-sm font-medium">{event.text}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {event.kind} - {new Date(event.createdAt).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </section>
    </>
  );
}

function Phase6OReviewRow({
  row,
  pending,
  onAction,
}: {
  row: SaasRazorpaySandboxStatusReviewDto;
  pending: boolean;
  onAction: (
    action: "approve" | "reject" | "archive",
    reason: string,
  ) => Promise<void>;
}) {
  const finalised =
    row.status === "approved_for_future_phase6p" ||
    row.status === "rejected" ||
    row.status === "archived" ||
    row.status === "blocked";
  return (
    <tr className="border-t border-border align-top">
      <td className="py-1 pr-3">{row.id}</td>
      <td className="py-1 pr-3 font-mono">{row.eventName}</td>
      <td className="py-1 pr-3 font-mono">{row.sourceEventId}</td>
      <td className="py-1 pr-3">{row.proposedPaymentStatus}</td>
      <td className="py-1 pr-3">{row.proposedOrderEffect}</td>
      <td className="py-1 pr-3">
        <StatusPill
          tone={
            row.status === "approved_for_future_phase6p"
              ? "success"
              : row.status === "rejected" || row.status === "blocked"
              ? "danger"
              : row.status === "archived"
              ? "neutral"
              : "info"
          }
        >
          {row.status}
        </StatusPill>
      </td>
      <td className="py-1 pr-3 text-emerald-600 font-medium">Disabled</td>
      <td className="py-1 pr-3">
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            disabled={pending || finalised}
            className="rounded border border-emerald-600/40 bg-emerald-600/5 px-2 py-0.5 text-[11px] font-medium disabled:opacity-50"
            onClick={() => onAction("approve", "")}
            data-testid={`phase6o-review-${row.id}-approve`}
          >
            Approve Review Only
          </button>
          <button
            type="button"
            disabled={pending || finalised}
            className="rounded border border-amber-600/40 bg-amber-600/5 px-2 py-0.5 text-[11px] font-medium disabled:opacity-50"
            onClick={() => onAction("reject", "")}
            data-testid={`phase6o-review-${row.id}-reject`}
          >
            Reject Review
          </button>
          <button
            type="button"
            disabled={pending || row.status === "archived"}
            className="rounded border border-border bg-muted/30 px-2 py-0.5 text-[11px] font-medium disabled:opacity-50"
            onClick={() => onAction("archive", "")}
            data-testid={`phase6o-review-${row.id}-archive`}
          >
            Archive Review
          </button>
        </div>
      </td>
    </tr>
  );
}


function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="surface-card p-4">
      <div className="flex items-center gap-2 text-xs uppercase text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="mt-2 truncate text-xl font-semibold">{value}</div>
      <div className="mt-1 text-sm text-muted-foreground">{detail}</div>
    </div>
  );
}

function Panel({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <div className="surface-card p-5">
      <h3 className="mb-4 flex items-center gap-2 font-display text-lg font-semibold">
        <Icon className="h-5 w-5 text-primary" />
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

function ContractList({
  title,
  data,
  testId,
}: {
  title: string;
  data: Record<string, unknown>;
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <h4 className="text-sm font-semibold mb-2">{title}</h4>
      <div className="rounded border border-border bg-muted/20 p-3 text-xs">
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="mb-2 last:mb-0">
            <div className="font-mono text-[11px] text-muted-foreground">
              {key}
            </div>
            <div className="mt-0.5 break-words">
              {Array.isArray(value)
                ? value.join(", ")
                : typeof value === "object" && value !== null
                  ? JSON.stringify(value)
                  : String(value)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <ul className="space-y-2 text-sm">
      {items.map((item) => (
        <li key={item} className="rounded-md border border-border p-2">
          {item}
        </li>
      ))}
    </ul>
  );
}

function LockRow({ label, safe }: { label: string; safe: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm">{label}</span>
      <StatusPill tone={safe ? "success" : "danger"}>
        {safe ? "Locked" : "Open"}
      </StatusPill>
    </div>
  );
}

function ProviderRow({ provider }: { provider: SaasProviderReadiness }) {
  return (
    <tr className="border-t border-border/60">
      <td className="px-6 py-3 font-medium">{provider.providerLabel}</td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(provider.status)}>
          {provider.status}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={provider.secretRefsPresent ? "success" : "warning"}>
          {provider.secretRefsPresent ? "Present" : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">{provider.validationStatus}</td>
      <td className="px-6 py-3">
        <StatusPill tone="neutral">Env/config</StatusPill>
      </td>
    </tr>
  );
}

function RuntimeOperationRow({
  decision,
}: {
  decision: SaasRuntimeDryRunOperationDecision;
}) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="runtime-operation-row"
    >
      <td className="px-6 py-3 font-mono text-xs">
        {decision.operationType}
      </td>
      <td className="py-3">{decision.providerLabel}</td>
      <td className="py-3">
        <StatusPill
          tone={
            decision.sideEffectRisk === "high"
              ? "warning"
              : decision.sideEffectRisk === "medium"
                ? "warning"
                : "neutral"
          }
        >
          {decision.sideEffectRisk}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={decision.providerSettingExists ? "success" : "warning"}
        >
          {decision.providerSettingExists ? "Configured" : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={decision.dryRun ? "success" : "danger"}>
          true
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone="neutral">false</StatusPill>
      </td>
      <td className="px-6 py-3 text-xs text-muted-foreground">
        {decision.nextAction}
      </td>
    </tr>
  );
}

function LiveGatePolicyRow({ policy }: { policy: SaasLiveGatePolicy }) {
  const decision = policy.currentGateDecision ?? "blocked_by_default";
  return (
    <tr className="border-t border-border/60" data-testid="live-gate-policy-row">
      <td className="px-6 py-3 font-mono text-xs">{policy.operationType}</td>
      <td className="py-3">{policy.providerType}</td>
      <td className="py-3">
        <StatusPill
          tone={
            policy.riskLevel === "critical" || policy.riskLevel === "high"
              ? "warning"
              : "neutral"
          }
        >
          {policy.riskLevel}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.approvalRequired ? "warning" : "neutral"}>
          {policy.approvalRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.caioReviewRequired ? "warning" : "neutral"}>
          {policy.caioReviewRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.consentRequired ? "warning" : "neutral"}>
          {policy.consentRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.claimVaultRequired ? "warning" : "neutral"}>
          {policy.claimVaultRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.webhookRequired ? "warning" : "neutral"}>
          {policy.webhookRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3 text-xs text-muted-foreground">{decision}</td>
      <td className="px-6 py-3">
        <StatusPill tone="neutral">
          {policy.liveAllowedNow ? "true" : "false"}
        </StatusPill>
      </td>
    </tr>
  );
}

function LiveGateSimulationRow({
  simulation,
}: {
  simulation: SaasRuntimeLiveGateSimulation;
}) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="live-gate-simulation-row"
    >
      <td className="px-6 py-3 font-mono text-xs">
        {simulation.operationType}
      </td>
      <td className="py-3">{simulation.providerType}</td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(simulation.status)}>
          {simulation.status}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(simulation.approvalStatus)}>
          {simulation.approvalStatus}
        </StatusPill>
      </td>
      <td className="py-3 text-xs text-muted-foreground">
        {simulation.gateDecision}
      </td>
      <td className="px-6 py-3">
        <StatusPill tone="success">
          {simulation.providerCallAttempted ? "attempted" : "not attempted"}
        </StatusPill>
      </td>
    </tr>
  );
}

function AiTaskRow({ task }: { task: SaasAiProviderRoutePreview }) {
  return (
    <tr className="border-t border-border/60" data-testid="ai-task-row">
      <td className="px-6 py-3 font-mono text-xs">{task.taskType}</td>
      <td className="py-3 text-xs">
        {task.primaryProvider} / {task.primaryModel}
      </td>
      <td className="py-3 text-xs">
        {task.fallbackProvider} / {task.fallbackModel}
      </td>
      <td className="py-3 text-xs">
        {task.maxTokens}{" "}
        <span className="text-muted-foreground">
          ({task.maxTokensFromEnv ? "env" : "default"})
        </span>
      </td>
      <td className="py-3">
        <StatusPill tone={task.safetyWrappersRequired ? "warning" : "neutral"}>
          {task.safetyWrappersRequired ? "Wrappers required" : "Internal only"}
        </StatusPill>
      </td>
      <td className="px-6 py-3 text-xs text-muted-foreground">
        {task.nextAction}
      </td>
    </tr>
  );
}

function RuntimeProviderRow({
  provider,
}: {
  provider: SaasRuntimeRoutingProviderPreview;
}) {
  const refsResolvable =
    provider.secretRefsPresent &&
    !provider.secretRefsResolvablePreview.anyMissingEnv;
  return (
    <tr className="border-t border-border/60" data-testid="runtime-provider-row">
      <td className="px-6 py-3 font-medium">{provider.providerLabel}</td>
      <td className="py-3">
        <StatusPill
          tone={provider.integrationSettingExists ? "success" : "warning"}
        >
          {provider.integrationSettingExists ? "Configured" : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(provider.settingStatus)}>
          {provider.settingStatus}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={provider.secretRefsPresent ? "success" : "warning"}>
          {provider.secretRefsPresent
            ? `${provider.expectedSecretRefKeys.length - provider.missingSecretRefs.length}/${provider.expectedSecretRefKeys.length} present`
            : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={refsResolvable ? "success" : "warning"}>
          {refsResolvable ? "Resolvable" : "Preview blocked"}
        </StatusPill>
      </td>
      <td className="px-6 py-3">
        <StatusPill tone="neutral">{provider.runtimeSource}</StatusPill>
      </td>
    </tr>
  );
}

function ProviderTestPlanInvariants({
  plan,
}: {
  plan: SaasProviderTestPlan | null;
}) {
  const rows: Array<{ label: string; value: boolean; safeWhenFalse?: boolean }> =
    plan
      ? [
          { label: "dryRun", value: plan.dryRun },
          {
            label: "providerCallAllowed",
            value: plan.providerCallAllowed,
            safeWhenFalse: true,
          },
          {
            label: "externalCallWillBeMade",
            value: plan.externalCallWillBeMade,
            safeWhenFalse: true,
          },
          {
            label: "externalCallWasMade",
            value: plan.externalCallWasMade,
            safeWhenFalse: true,
          },
          {
            label: "providerCallAttempted",
            value: plan.providerCallAttempted,
            safeWhenFalse: true,
          },
          { label: "realMoney", value: plan.realMoney, safeWhenFalse: true },
          {
            label: "realCustomerDataAllowed",
            value: plan.realCustomerDataAllowed,
            safeWhenFalse: true,
          },
        ]
      : [];
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Safety invariants
      </h4>
      {plan === null ? (
        <p className="text-xs text-muted-foreground">
          No plan prepared yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((row) => {
            const safe =
              row.safeWhenFalse === true ? row.value === false : row.value;
            return (
              <div
                key={row.label}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono text-muted-foreground">
                  {row.label}
                </span>
                <StatusPill tone={safe ? "success" : "danger"}>
                  {String(row.value)}
                </StatusPill>
              </div>
            );
          })}
          <div className="pt-1 text-[11px] text-muted-foreground">
            amount: {plan.amountPaise ?? "n/a"} paise · {plan.currency} ·
            payloadHash: {plan.payloadHash ? "present" : "missing"}
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderTestPlanEnvReadiness({
  plan,
}: {
  plan: SaasProviderTestPlan | null;
}) {
  const env = plan?.envReadiness;
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <KeyRound className="h-4 w-4 text-primary" />
        Razorpay env readiness
      </h4>
      {env === undefined ? (
        <p className="text-xs text-muted-foreground">
          No plan prepared yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          <EnvRow
            label="Razorpay key id"
            present={!!env.envPresence?.RAZORPAY_KEY_ID}
            blockingWhenMissing
          />
          <EnvRow
            label="Razorpay key secret"
            present={!!env.envPresence?.RAZORPAY_KEY_SECRET}
            blockingWhenMissing
          />
          <EnvRow
            label="Razorpay webhook secret"
            present={!!env.envPresence?.RAZORPAY_WEBHOOK_SECRET}
          />
          <div className="pt-1 text-[11px] text-muted-foreground">
            Masked refs only — raw values are never returned.
          </div>
        </div>
      )}
    </div>
  );
}

function EnvRow({
  label,
  present,
  blockingWhenMissing = false,
}: {
  label: string;
  present: boolean;
  blockingWhenMissing?: boolean;
}) {
  const tone: "success" | "warning" | "danger" = present
    ? "success"
    : blockingWhenMissing
      ? "danger"
      : "warning";
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="font-mono text-muted-foreground">{label}</span>
      <StatusPill tone={tone}>
        {present ? "present" : "missing"}
      </StatusPill>
    </div>
  );
}


function ProviderExecutionEnvCard({
  env,
}: {
  env: SaasProviderExecutionReadiness["envReadiness"];
}) {
  const keyTone: "success" | "warning" | "danger" = env.isLiveKey
    ? "danger"
    : env.isTestKey
      ? "success"
      : "warning";
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <KeyRound className="h-4 w-4 text-primary" />
        Razorpay execution-gate env
      </h4>
      <div className="space-y-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Phase 6K env flag
          </span>
          <StatusPill tone={env.envFlagEnabled ? "success" : "warning"}>
            {env.envFlagEnabled ? "enabled" : "disabled"}
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Razorpay key mode
          </span>
          <StatusPill tone={keyTone}>{env.razorpayKeyMode}</StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Key id (masked)
          </span>
          <span className="font-mono text-[11px]">
            {env.razorpayKeyIdMasked || "missing"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Key secret
          </span>
          <StatusPill
            tone={env.razorpayKeySecretPresent ? "success" : "danger"}
          >
            {env.razorpayKeySecretPresent ? "present" : "missing"}
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Webhook secret
          </span>
          <StatusPill
            tone={env.razorpayWebhookSecretPresent ? "success" : "warning"}
          >
            {env.razorpayWebhookSecretPresent ? "present" : "missing"}
          </StatusPill>
        </div>
      </div>
      <div className="pt-2 text-[11px] text-muted-foreground">
        Masked refs only. Raw secrets are never exposed.
      </div>
    </div>
  );
}

function ProviderExecutionInvariants({
  attempt,
}: {
  attempt: SaasProviderExecutionAttempt | null;
}) {
  const rows: Array<{ label: string; value: boolean; safeWhenFalse?: boolean }> =
    attempt
      ? [
          { label: "testMode", value: attempt.testMode },
          {
            label: "realMoney",
            value: attempt.realMoney,
            safeWhenFalse: true,
          },
          {
            label: "realCustomerDataAllowed",
            value: attempt.realCustomerDataAllowed,
            safeWhenFalse: true,
          },
          {
            label: "businessMutationWasMade",
            value: attempt.businessMutationWasMade,
            safeWhenFalse: true,
          },
          {
            label: "paymentLinkCreated",
            value: attempt.paymentLinkCreated,
            safeWhenFalse: true,
          },
          {
            label: "paymentCaptured",
            value: attempt.paymentCaptured,
            safeWhenFalse: true,
          },
          {
            label: "customerNotificationSent",
            value: attempt.customerNotificationSent,
            safeWhenFalse: true,
          },
        ]
      : [];
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Latest attempt safety invariants
      </h4>
      {attempt === null ? (
        <p className="text-xs text-muted-foreground">
          No execution attempt yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((row) => {
            const safe =
              row.safeWhenFalse === true ? row.value === false : row.value;
            return (
              <div
                key={row.label}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono text-muted-foreground">
                  {row.label}
                </span>
                <StatusPill tone={safe ? "success" : "danger"}>
                  {String(row.value)}
                </StatusPill>
              </div>
            );
          })}
          <div className="pt-1 text-[11px] text-muted-foreground">
            providerObjectId:{" "}
            <span className="font-mono">
              {attempt.providerObjectId || "n/a"}
            </span>{" "}
            · status: {attempt.providerStatus || attempt.status}
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderExecutionAttemptsTable({
  attempts,
}: {
  attempts: SaasProviderExecutionAttempt[];
}) {
  if (!attempts.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No execution attempts recorded yet.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[860px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Execution</th>
            <th className="py-3 text-left font-medium">Status</th>
            <th className="py-3 text-left font-medium">
              Provider obj id
            </th>
            <th className="py-3 text-left font-medium">Provider call</th>
            <th className="py-3 text-left font-medium">External call</th>
            <th className="py-3 text-left font-medium">Mutation</th>
            <th className="py-3 text-left font-medium">Payment captured</th>
            <th className="px-6 py-3 text-left font-medium">Notify sent</th>
          </tr>
        </thead>
        <tbody>
          {attempts.map((attempt) => (
            <tr
              key={attempt.executionId}
              className="border-t border-border/60"
              data-testid="provider-execution-attempt-row"
            >
              <td className="px-6 py-3 font-mono text-xs">
                {attempt.executionId}
              </td>
              <td className="py-3">
                <StatusPill tone={toneForStatus(attempt.status)}>
                  {attempt.status}
                </StatusPill>
              </td>
              <td className="py-3 text-xs font-mono">
                {attempt.providerObjectId || "—"}
              </td>
              <td className="py-3">
                <StatusPill
                  tone={
                    attempt.providerCallAttempted ? "warning" : "success"
                  }
                >
                  {String(attempt.providerCallAttempted)}
                </StatusPill>
              </td>
              <td className="py-3">
                <StatusPill
                  tone={
                    attempt.externalCallWasMade ? "warning" : "success"
                  }
                >
                  {String(attempt.externalCallWasMade)}
                </StatusPill>
              </td>
              <td className="py-3">
                <StatusPill
                  tone={
                    attempt.businessMutationWasMade ? "danger" : "success"
                  }
                >
                  {String(attempt.businessMutationWasMade)}
                </StatusPill>
              </td>
              <td className="py-3">
                <StatusPill
                  tone={attempt.paymentCaptured ? "danger" : "success"}
                >
                  {String(attempt.paymentCaptured)}
                </StatusPill>
              </td>
              <td className="px-6 py-3">
                <StatusPill
                  tone={
                    attempt.customerNotificationSent ? "danger" : "success"
                  }
                >
                  {String(attempt.customerNotificationSent)}
                </StatusPill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function RazorpayAuditReviewCard({
  review,
}: {
  review: SaasRazorpayAuditReview;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Phase 6K execution audit
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue label="Execution" value={review.executionId} />
        <KeyValue
          label="Provider order id"
          value={review.providerObjectId ?? "n/a"}
        />
        <KeyValue label="Status" value={review.status ?? "n/a"} />
        <KeyValue
          label="Rollback"
          value={review.rollbackStatus ?? "n/a"}
        />
      </div>
      {review.invariantResults && review.invariantResults.length > 0 && (
        <div className="mt-4 grid gap-1.5">
          {review.invariantResults.map((inv) => (
            <div
              key={inv.key}
              className="flex items-center justify-between text-xs"
              data-testid="razorpay-audit-invariant-row"
            >
              <span className="font-mono text-muted-foreground">
                {inv.key}
              </span>
              <StatusPill tone={inv.passed ? "success" : "danger"}>
                {String(inv.actual)}
              </StatusPill>
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 text-[11px] text-muted-foreground">
        Audit events: {review.auditEventCount ?? 0} ·
        rawSecretLeakDetected:{" "}
        <span className="font-mono">
          {String(Boolean(review.rawSecretLeakDetected))}
        </span>
      </div>
      {review.blockers && review.blockers.length > 0 && (
        <IssueList items={review.blockers} empty="No blockers" />
      )}
    </div>
  );
}

function RazorpayWebhookReadinessCard({
  readiness,
}: {
  readiness: SaasRazorpayWebhookReadiness;
}) {
  const keyTone: "success" | "warning" | "danger" = readiness.isLiveKey
    ? "danger"
    : readiness.isTestKey
      ? "success"
      : "warning";
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Webhook className="h-4 w-4 text-primary" />
        Webhook readiness
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue label="Key mode" value={readiness.razorpayKeyMode} />
        <KeyValue
          label="Key id (masked)"
          value={readiness.razorpayKeyIdMasked || "missing"}
        />
        <KeyValue
          label="Webhook secret"
          value={
            readiness.razorpayWebhookSecretPresent ? "present" : "missing"
          }
        />
        <KeyValue
          label="Latest succeeded"
          value={readiness.latestSucceededProviderObjectId ?? "n/a"}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <StatusPill tone={keyTone}>
          {readiness.isTestKey ? "test mode" : readiness.razorpayKeyMode}
        </StatusPill>
        <StatusPill
          tone={
            readiness.safeToPlanWebhookReadiness ? "success" : "warning"
          }
        >
          {readiness.safeToPlanWebhookReadiness
            ? "Safe to plan"
            : "Plan blocked"}
        </StatusPill>
        <span className="text-muted-foreground">
          Phase 6K succeeded:{" "}
          <span className="font-mono">
            {readiness.phase6KSucceededExecutionCount}
          </span>
        </span>
      </div>
      {readiness.blockers && readiness.blockers.length > 0 && (
        <IssueList items={readiness.blockers} empty="No blockers" />
      )}
    </div>
  );
}

function RazorpayWebhookPlanCard({
  plan,
}: {
  plan: SaasRazorpayWebhookPlan;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ClipboardList className="h-4 w-4 text-primary" />
        Webhook readiness plan ({plan.policyVersion})
      </h4>
      <div className="grid gap-3 sm:grid-cols-3">
        <KeyValue
          label="Endpoint"
          value={`${plan.endpointDesign.method} ${plan.endpointDesign.path}`}
        />
        <KeyValue
          label="Signature"
          value={`${plan.signatureVerificationDesign.algorithm} on ${plan.signatureVerificationDesign.header}`}
        />
        <KeyValue
          label="Replay window"
          value={`${plan.replayProtection.windowSeconds}s`}
        />
        <KeyValue
          label="Idempotency key"
          value={plan.idempotencyDesign.key}
        />
        <KeyValue
          label="Allowlist size"
          value={String(plan.eventAllowlist.length)}
        />
        <KeyValue
          label="Denylist size"
          value={String(plan.eventDenylist.length)}
        />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-1 font-semibold text-muted-foreground">
            Allowlist
          </div>
          <ul className="space-y-1 font-mono text-[11px]">
            {plan.eventAllowlist.map((event) => (
              <li
                key={event}
                data-testid="razorpay-webhook-allowlist-row"
              >
                {event}
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-1 font-semibold text-muted-foreground">
            Denylist
          </div>
          <ul className="space-y-1 font-mono text-[11px]">
            {plan.eventDenylist.map((event) => (
              <li
                key={event}
                data-testid="razorpay-webhook-denylist-row"
              >
                {event}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="mt-3 grid gap-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Phase 6L mutation policy
          </span>
          <StatusPill tone="success">
            no order/payment/shipment/notify mutations
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Phase 6L registers webhook
          </span>
          <StatusPill tone="success">
            {String(plan.endpointDesign.phase6LRegistration)}
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Sensitive payload keys scrubbed
          </span>
          <span className="font-mono text-[11px]">
            {plan.auditLoggingPlan.payloadHandling.sensitiveKeysToScrub.length}
          </span>
        </div>
      </div>
      <div className="mt-3 text-[11px] text-muted-foreground">
        Next action:{" "}
        <span className="font-medium">{plan.nextAction}</span> · Next
        phase: {plan.nextPhase}
      </div>
    </div>
  );
}


function McpReadinessCard({
  readiness,
}: {
  readiness: McpGatewayReadiness;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Bot className="h-4 w-4 text-primary" />
        MCP mode
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue label="MCP_ENABLED" value={String(readiness.mcpEnabled)} />
        <KeyValue label="Read-only mode" value={String(readiness.readOnlyMode)} />
        <KeyValue label="Write tools" value={String(readiness.writeToolsEnabled)} />
        <KeyValue
          label="Provider tools"
          value={String(readiness.providerToolsEnabled)}
        />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-4 text-xs">
        <KeyValue label="Tools" value={String(readiness.toolCount)} />
        <KeyValue label="Resources" value={String(readiness.resourceCount)} />
        <KeyValue label="Prompts" value={String(readiness.promptCount)} />
        <KeyValue
          label="Active clients"
          value={String(readiness.activeClientCount)}
        />
      </div>
      <div className="mt-3 text-[11px] text-muted-foreground">
        Next action:{" "}
        <span className="font-medium">{readiness.nextAction}</span>
      </div>
    </div>
  );
}

function McpSecurityPostureCard({
  posture,
}: {
  posture: McpSecurityPosture;
}) {
  const rows: Array<{ label: string; value: boolean; safeWhenFalse?: boolean }> = [
    { label: "authRequired", value: posture.authRequired },
    {
      label: "writeToolsEnabled",
      value: posture.writeToolsEnabled,
      safeWhenFalse: true,
    },
    {
      label: "providerToolsEnabled",
      value: posture.providerToolsEnabled,
      safeWhenFalse: true,
    },
    {
      label: "forbiddenToolsRegistered",
      value: posture.forbiddenToolsRegistered,
      safeWhenFalse: true,
    },
  ];
  const numericRows: Array<{ label: string; value: number }> = [
    { label: "rawSecretExposureCount", value: posture.rawSecretExposureCount },
    { label: "piiExposureCount", value: posture.piiExposureCount },
    {
      label: "providerCallAttemptedCount",
      value: posture.providerCallAttemptedCount,
    },
    {
      label: "businessMutationAttemptedCount",
      value: posture.businessMutationAttemptedCount,
    },
  ];
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Security posture
      </h4>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-muted/20 p-3">
          <div className="mb-1 text-xs font-semibold text-muted-foreground">
            Boolean invariants
          </div>
          <div className="space-y-1.5">
            {rows.map((row) => {
              const safe =
                row.safeWhenFalse === true ? row.value === false : row.value;
              return (
                <div
                  key={row.label}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="font-mono text-muted-foreground">
                    {row.label}
                  </span>
                  <StatusPill tone={safe ? "success" : "danger"}>
                    {String(row.value)}
                  </StatusPill>
                </div>
              );
            })}
          </div>
        </div>
        <div className="rounded-md border border-border bg-muted/20 p-3">
          <div className="mb-1 text-xs font-semibold text-muted-foreground">
            Counters (must stay 0)
          </div>
          <div className="space-y-1.5">
            {numericRows.map((row) => (
              <div
                key={row.label}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono text-muted-foreground">
                  {row.label}
                </span>
                <StatusPill tone={row.value === 0 ? "success" : "danger"}>
                  {row.value}
                </StatusPill>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function McpToolsTable({ response }: { response: McpToolsResponse }) {
  if (!response.tools.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No MCP tools registered. Run{" "}
        <code>manage.py ensure_mcp_defaults</code>.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[920px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Name</th>
            <th className="py-3 text-left font-medium">Category</th>
            <th className="py-3 text-left font-medium">Risk</th>
            <th className="py-3 text-left font-medium">Read-only</th>
            <th className="py-3 text-left font-medium">Provider call</th>
            <th className="py-3 text-left font-medium">Mutation</th>
            <th className="px-6 py-3 text-left font-medium">Scopes</th>
          </tr>
        </thead>
        <tbody>
          {response.tools.map((tool) => (
            <McpToolRow key={tool.name} tool={tool} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function McpToolRow({ tool }: { tool: McpToolDefinitionDto }) {
  const riskTone: "success" | "warning" | "danger" =
    tool.riskLevel === "low"
      ? "success"
      : tool.riskLevel === "critical" || tool.riskLevel === "high"
        ? "warning"
        : "neutral";
  return (
    <tr className="border-t border-border/60" data-testid="mcp-tool-row">
      <td className="px-6 py-3 font-mono text-xs">{tool.name}</td>
      <td className="py-3 text-xs">{tool.category}</td>
      <td className="py-3">
        <StatusPill tone={riskTone}>{tool.riskLevel}</StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={tool.readOnly ? "success" : "danger"}>
          {String(tool.readOnly)}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={tool.providerCallAllowed ? "danger" : "success"}
        >
          {String(tool.providerCallAllowed)}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={tool.businessMutationAllowed ? "danger" : "success"}
        >
          {String(tool.businessMutationAllowed)}
        </StatusPill>
      </td>
      <td className="px-6 py-3 text-[11px] font-mono text-muted-foreground">
        {tool.requiredScopes.join(", ")}
      </td>
    </tr>
  );
}

function McpInvocationsTable({
  response,
}: {
  response: McpInvocationsResponse;
}) {
  if (!response.invocations.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No MCP invocations recorded yet.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[860px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Invocation</th>
            <th className="py-3 text-left font-medium">Tool</th>
            <th className="py-3 text-left font-medium">Status</th>
            <th className="py-3 text-left font-medium">Provider call</th>
            <th className="py-3 text-left font-medium">Mutation</th>
            <th className="px-6 py-3 text-left font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {response.invocations.map((row) => (
            <McpInvocationRow key={row.invocationId} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function McpInvocationRow({ row }: { row: McpToolInvocationDto }) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="mcp-invocation-row"
    >
      <td className="px-6 py-3 font-mono text-xs">{row.invocationId}</td>
      <td className="py-3 text-xs">{row.toolName}</td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(row.status)}>{row.status}</StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={row.providerCallAttempted ? "danger" : "success"}>
          {String(row.providerCallAttempted)}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={row.businessMutationAttempted ? "danger" : "success"}
        >
          {String(row.businessMutationAttempted)}
        </StatusPill>
      </td>
      <td className="px-6 py-3 text-[11px] text-muted-foreground">
        {row.createdAt}
      </td>
    </tr>
  );
}


function RazorpayWebhookHandlerReadinessCard({
  readiness,
}: {
  readiness: SaasRazorpayWebhookHandlerReadiness;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Webhook className="h-4 w-4 text-primary" />
        Handler readiness
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue
          label="Test mode enabled"
          value={String(readiness.webhookTestModeEnabled)}
        />
        <KeyValue
          label="Webhook secret"
          value={
            readiness.webhookSecretPresent ? "present" : "missing"
          }
        />
        <KeyValue
          label="Replay window"
          value={`${readiness.replayWindowSeconds}s`}
        />
        <KeyValue
          label="Allowed events"
          value={String(readiness.allowedEvents.length)}
        />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-2 font-semibold text-muted-foreground">
            Safety invariants
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                businessMutationEnabled
              </span>
              <StatusPill
                tone={
                  readiness.businessMutationEnabled
                    ? "danger"
                    : "success"
                }
              >
                {String(readiness.businessMutationEnabled)}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                customerNotificationEnabled
              </span>
              <StatusPill
                tone={
                  readiness.customerNotificationEnabled
                    ? "danger"
                    : "success"
                }
              >
                {String(readiness.customerNotificationEnabled)}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                storeRawPayload
              </span>
              <StatusPill
                tone={readiness.storeRawPayload ? "warning" : "success"}
              >
                {String(readiness.storeRawPayload)}
              </StatusPill>
            </div>
          </div>
        </div>
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-2 font-semibold text-muted-foreground">
            Counters (must stay 0)
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                businessMutationCount
              </span>
              <StatusPill
                tone={
                  readiness.businessMutationCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.businessMutationCount}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                customerNotificationCount
              </span>
              <StatusPill
                tone={
                  readiness.customerNotificationCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.customerNotificationCount}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                rawSecretExposureCount
              </span>
              <StatusPill
                tone={
                  readiness.rawSecretExposureCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.rawSecretExposureCount}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                fullPiiExposureCount
              </span>
              <StatusPill
                tone={
                  readiness.fullPiiExposureCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.fullPiiExposureCount}
              </StatusPill>
            </div>
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-4 text-xs">
        <KeyValue label="Events seen" value={String(readiness.eventCount)} />
        <KeyValue
          label="Verified"
          value={String(readiness.verifiedEventCount)}
        />
        <KeyValue
          label="Duplicates"
          value={String(readiness.duplicateEventCount)}
        />
        <KeyValue
          label="Blocked / ignored"
          value={String(readiness.blockedEventCount)}
        />
      </div>
      {readiness.blockers.length > 0 && (
        <IssueList items={readiness.blockers} empty="No blockers" />
      )}
      <div className="mt-3 text-[11px] text-muted-foreground">
        Next action:{" "}
        <span className="font-medium">{readiness.nextAction}</span>
      </div>
    </div>
  );
}

function RazorpayWebhookEventsTable({
  response,
}: {
  response: SaasRazorpayWebhookEventsResponse;
}) {
  if (!response.events.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No Razorpay webhook events recorded yet. Send a synthetic
        event via{" "}
        <code>manage.py simulate_razorpay_webhook_event --event payment.captured</code>.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[920px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Event id</th>
            <th className="py-3 text-left font-medium">Event</th>
            <th className="py-3 text-left font-medium">Signature</th>
            <th className="py-3 text-left font-medium">Idempotency</th>
            <th className="py-3 text-left font-medium">Status</th>
            <th className="py-3 text-left font-medium">Order id</th>
            <th className="py-3 text-left font-medium">Payment id</th>
            <th className="py-3 text-left font-medium">Amount</th>
            <th className="px-6 py-3 text-left font-medium">Received</th>
          </tr>
        </thead>
        <tbody>
          {response.events.map((row) => (
            <RazorpayWebhookEventRow key={row.id} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RazorpayWebhookEventRow({
  row,
}: {
  row: SaasRazorpayWebhookEventDto;
}) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="razorpay-webhook-event-row"
    >
      <td className="px-6 py-3 font-mono text-xs">
        {row.sourceEventId || "—"}
      </td>
      <td className="py-3 text-xs">{row.eventName}</td>
      <td className="py-3">
        <StatusPill tone={row.signatureValid ? "success" : "danger"}>
          {row.signatureValid ? "valid" : "invalid"}
        </StatusPill>
      </td>
      <td className="py-3 text-xs">
        {row.idempotencyStatus} ({row.duplicateCount}x)
      </td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(row.processingStatus)}>
          {row.processingStatus}
        </StatusPill>
      </td>
      <td className="py-3 text-[11px] font-mono">
        {row.providerOrderId || "—"}
      </td>
      <td className="py-3 text-[11px] font-mono">
        {row.providerPaymentId || "—"}
      </td>
      <td className="py-3 text-xs">
        {row.amountPaise === null
          ? "—"
          : `${row.amountPaise} ${row.currency || ""}`}
      </td>
      <td className="px-6 py-3 text-[11px] text-muted-foreground">
        {row.receivedAt}
      </td>
    </tr>
  );
}
