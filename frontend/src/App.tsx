import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppLayout } from "@/components/layout/AppLayout";
import Index from "./pages/Index";
import NotFound from "./pages/NotFound";
import LeadsPage from "./pages/Leads";
import CustomersPage from "./pages/Customers";
import CallingPage from "./pages/Calling";
import OrdersPage from "./pages/Orders";
import ConfirmationPage from "./pages/Confirmation";
import PaymentsPage from "./pages/Payments";
import DeliveryPage from "./pages/Delivery";
import RtoPage from "./pages/Rto";
import AgentsPage from "./pages/Agents";
import CeoAiPage from "./pages/CeoAi";
import CaioPage from "./pages/Caio";
import RewardsPage from "./pages/Rewards";
import LearningPage from "./pages/Learning";
import ClaimsPage from "./pages/Claims";
import AnalyticsPage from "./pages/Analytics";
import SchedulerPage from "./pages/Scheduler";
import GovernancePage from "./pages/Governance";
import SettingsPage from "./pages/Settings";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Index />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/customers" element={<CustomersPage />} />
            <Route path="/calling" element={<CallingPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/confirmation" element={<ConfirmationPage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/delivery" element={<DeliveryPage />} />
            <Route path="/rto" element={<RtoPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/ceo-ai" element={<CeoAiPage />} />
            <Route path="/caio" element={<CaioPage />} />
            <Route path="/rewards" element={<RewardsPage />} />
            <Route path="/learning" element={<LearningPage />} />
            <Route path="/claims" element={<ClaimsPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/ai-scheduler" element={<SchedulerPage />} />
            <Route path="/ai-governance" element={<GovernancePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
