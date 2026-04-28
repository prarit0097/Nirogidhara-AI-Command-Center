import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  WhatsAppProviderStatus,
  WhatsAppTemplate,
} from "@/types/domain";
import { MessageSquare, RefreshCw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

export default function WhatsAppTemplatesPage() {
  const [providerStatus, setProviderStatus] = useState<
    WhatsAppProviderStatus | null
  >(null);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    void Promise.all([
      api.getWhatsAppProviderStatus(),
      api.listWhatsAppTemplates(),
    ]).then(([status, rows]) => {
      setProviderStatus(status);
      setTemplates(rows);
    });
  }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const result = await api.syncWhatsAppTemplates({});
      toast.success(
        `Synced ${result.totalProcessed} templates · created=${result.createdCount} updated=${result.updatedCount}`,
      );
      const fresh = await api.listWhatsAppTemplates();
      setTemplates(fresh);
    } catch (error) {
      toast.error(
        `Sync failed: ${(error as Error).message ?? "unknown error"}`,
      );
    } finally {
      setSyncing(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="WhatsApp"
        title="Templates"
        description="Meta-approved templates mirrored from WABA. Phase 5A is read-only — admins refresh via Sync."
      />

      <div className="surface-card p-5 mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <MessageSquare className="h-5 w-5 text-primary" />
          <div>
            <div className="font-medium">Provider</div>
            <div className="text-xs text-muted-foreground">
              {providerStatus
                ? `${providerStatus.provider} · ${providerStatus.healthy ? "healthy" : "unhealthy"}`
                : "Loading provider status…"}
            </div>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleSync}
          disabled={syncing}
          className="gap-2"
        >
          <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
          Sync from Meta
        </Button>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" /> Approved templates
          </h3>
          <StatusPill tone="info">{templates.length}</StatusPill>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[680px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Name</th>
                <th className="text-left font-medium py-3">Language</th>
                <th className="text-left font-medium py-3">Category</th>
                <th className="text-left font-medium py-3">Status</th>
                <th className="text-left font-medium py-3">Action key</th>
                <th className="text-left font-medium px-6 py-3">Claim Vault</th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr
                  key={t.id}
                  className={`border-t border-border/60 hover:bg-muted/20 ${
                    !t.isActive || t.status !== "APPROVED"
                      ? "opacity-60"
                      : ""
                  }`}
                >
                  <td className="px-6 py-3 font-medium">{t.name}</td>
                  <td className="py-3">{t.language}</td>
                  <td className="py-3">
                    <StatusPill
                      tone={t.category === "MARKETING" ? "warning" : "info"}
                    >
                      {t.category}
                    </StatusPill>
                  </td>
                  <td className="py-3">
                    <StatusPill
                      tone={
                        t.status === "APPROVED"
                          ? "success"
                          : t.status === "REJECTED"
                            ? "danger"
                            : "neutral"
                      }
                    >
                      {t.status}
                    </StatusPill>
                  </td>
                  <td className="py-3 text-xs text-muted-foreground">
                    {t.actionKey || "—"}
                  </td>
                  <td className="px-6 py-3">
                    {t.claimVaultRequired ? (
                      <StatusPill tone="warning">required</StatusPill>
                    ) : (
                      <StatusPill tone="neutral">—</StatusPill>
                    )}
                  </td>
                </tr>
              ))}
              {templates.length === 0 && (
                <tr>
                  <td
                    className="px-6 py-6 text-center text-muted-foreground"
                    colSpan={6}
                  >
                    No templates synced yet. Click <strong>Sync from Meta</strong>{" "}
                    to seed defaults.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
