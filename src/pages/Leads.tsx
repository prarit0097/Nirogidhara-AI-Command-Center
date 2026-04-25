import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/services/api";
import { Filter, Phone, Plus, Search, Upload, Flame, Snowflake, Sun, Copy } from "lucide-react";
import { toast } from "sonner";

const QUALITY_ICON: Record<string, any> = { Hot: Flame, Warm: Sun, Cold: Snowflake };
const QUALITY_TONE: Record<string, "danger" | "warning" | "info"> = { Hot: "danger", Warm: "warning", Cold: "info" };

export default function Leads() {
  const [leads, setLeads] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("All");

  useEffect(() => { api.getLeads().then(setLeads); }, []);

  const filtered = useMemo(() => leads.filter((l) => {
    if (status !== "All" && l.status !== status) return false;
    if (search && !`${l.name} ${l.phone}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [leads, search, status]);

  const STATUSES = ["All", "New", "AI Calling Started", "Interested", "Callback Required", "Payment Link Sent", "Order Punched", "Not Interested", "Invalid"];

  return (
    <>
      <PageHeader
        eyebrow="Sales"
        title="Leads CRM"
        description="Every lead from Meta, Google, influencer & inbound calls — auto-scored, deduplicated and routed to AI or human callers."
        actions={
          <>
            <Button variant="outline" onClick={() => toast.info("Upload panel — connect Django /api/leads/import")}><Upload className="h-4 w-4 mr-1.5" />Import</Button>
            <Button className="bg-gradient-hero text-primary-foreground"><Plus className="h-4 w-4 mr-1.5" />New Lead</Button>
          </>
        }
      />

      <div className="surface-card p-4 mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name or phone…" className="pl-9 bg-muted/50 border-transparent" />
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <Filter className="h-4 w-4 text-muted-foreground" />
          {STATUSES.map((s) => (
            <button key={s} onClick={() => setStatus(s)}
              className={`text-xs px-2.5 py-1 rounded-full border transition ${status === s ? "bg-foreground text-background border-foreground" : "bg-background border-border hover:bg-muted"}`}>
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[1000px]">
            <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-4 py-3">Lead</th>
                <th className="text-left font-medium py-3">Source / Campaign</th>
                <th className="text-left font-medium py-3">Interest</th>
                <th className="text-left font-medium py-3">Quality</th>
                <th className="text-left font-medium py-3">Status</th>
                <th className="text-left font-medium py-3">Assignee</th>
                <th className="text-right font-medium px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((l) => {
                const QI = QUALITY_ICON[l.quality];
                return (
                  <tr key={l.id} className="border-t border-border/60 hover:bg-muted/30 transition">
                    <td className="px-4 py-3">
                      <div className="font-medium flex items-center gap-2">
                        {l.name}
                        {l.duplicate && <span title="Possible duplicate"><Copy className="h-3.5 w-3.5 text-warning" /></span>}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">{l.phone}</div>
                      <div className="text-[11px] text-muted-foreground">{l.city}, {l.state} · {l.language}</div>
                    </td>
                    <td className="py-3">
                      <div className="text-sm">{l.source}</div>
                      <div className="text-[11px] text-muted-foreground">{l.campaign}</div>
                    </td>
                    <td className="py-3 text-sm">{l.productInterest}</td>
                    <td className="py-3"><StatusPill tone={QUALITY_TONE[l.quality]} icon={QI && <QI className="h-3 w-3" />}>{l.quality} · {l.qualityScore}</StatusPill></td>
                    <td className="py-3"><StatusPill tone={toneForStatus(l.status)}>{l.status}</StatusPill></td>
                    <td className="py-3 text-sm">{l.assignee}</td>
                    <td className="px-4 py-3 text-right">
                      <Button size="sm" variant="ghost" className="h-8" onClick={() => toast.success(`Calling ${l.name}…`)}>
                        <Phone className="h-3.5 w-3.5 mr-1" />Call
                      </Button>
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr><td colSpan={7} className="text-center py-12 text-muted-foreground text-sm">No leads match your filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}