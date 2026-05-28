import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, isApiError } from "@/services/api";
import type {
  ImportedDataset,
  ImportedDatasetDetail,
  ImportsOverview,
} from "@/types/domain";
import { Database, ShieldCheck, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const CSV_PLACEHOLDER = `name,phone,disease,city,state,notes
Ramesh,+91XXXXXXXXXX,Joint pain,Mumbai,Maharashtra,old customer`;

export default function DataImports() {
  const [overview, setOverview] = useState<ImportsOverview | null>(null);
  const [datasets, setDatasets] = useState<ImportedDataset[]>([]);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState("");
  const [problemCategory, setProblemCategory] = useState("");
  const [sourceLabel, setSourceLabel] = useState("Uploaded Data");
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [lastResult, setLastResult] = useState<ImportedDatasetDetail | null>(null);
  const [creatingFor, setCreatingFor] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getImportsOverview().then(setOverview).catch(() => setOverview(null)),
      api
        .getImportDatasets()
        .then((r) => setDatasets(r.items))
        .catch(() => setDatasets([])),
    ]).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleFile = async (file: File | null) => {
    if (!file) {
      setFileName("");
      return;
    }
    setFileName(file.name);
    setCsv(await file.text());
    if (!name.trim()) setName(file.name.replace(/\.csv$/i, ""));
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (uploading) return;
    if (!name.trim()) {
      toast.error("Give the dataset a name first.");
      return;
    }
    if (!csv.trim()) {
      toast.error("Paste CSV content or choose a .csv file first.");
      return;
    }
    setUploading(true);
    setLastResult(null);
    try {
      const result = await api.uploadImportDataset({
        name: name.trim(),
        csv: csv.trim(),
        sourceLabel: sourceLabel.trim(),
        problemCategory: problemCategory.trim(),
        originalFilename: fileName,
      });
      setLastResult(result);
      toast.success(
        `Dataset uploaded — ${result.validRows} valid, ${result.duplicateRows} duplicates, ${result.invalidRows} invalid.`,
      );
      setName("");
      setCsv("");
      setFileName("");
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Upload failed (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Upload failed. Please retry.");
      }
    } finally {
      setUploading(false);
    }
  };

  const handleCreateCampaign = async (dataset: ImportedDataset) => {
    if (dataset.validRows <= 0) {
      toast.error("No valid rows to build a campaign from.");
      return;
    }
    setCreatingFor(dataset.id);
    try {
      const campaign = await api.createImportCampaign(dataset.id, {
        name: `${dataset.name} campaign`,
        problemCategory: dataset.problemCategory,
      });
      toast.success(`Campaign "${campaign.name}" created with ${campaign.totalContacts} contacts.`);
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Could not create campaign (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Could not create campaign. Please retry.");
      }
    } finally {
      setCreatingFor(null);
    }
  };

  return (
    <div data-testid="data-imports-page">
      <PageHeader
        eyebrow="Operations"
        title="Data Imports"
        description="Upload existing offline / old customer data (CSV), validate + deduplicate it, and build a manual calling campaign from the valid rows."
      />

      <div
        data-testid="data-imports-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Internal workflow only — no WhatsApp / payment / courier / Vapi /
          AI-provider action is triggered. Uploading parses + validates rows;
          no customer is contacted.
        </span>
      </div>

      {/* KPI cards */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <Kpi label="Datasets" value={overview.datasetCount} />
          <Kpi label="Valid contacts" value={overview.validContacts} tone="success" />
          <Kpi label="Duplicates" value={overview.duplicateCount} tone="warning" />
          <Kpi label="Invalid" value={overview.invalidCount} tone="danger" />
          <Kpi label="Active campaigns" value={overview.activeCampaigns} />
          <Kpi label="Pending calls" value={overview.pendingCalls} />
          <Kpi label="Interested rate" value={`${overview.interestedRate}%`} tone="success" />
          <Kpi label="Orders created" value={overview.orderCreatedCount} tone="success" />
        </div>
      )}

      {/* Upload card */}
      <form
        onSubmit={handleUpload}
        className="surface-elevated p-6 mb-6 space-y-4"
        data-testid="data-imports-upload-form"
      >
        <h2 className="font-display text-lg font-semibold flex items-center gap-2">
          <Upload className="h-5 w-5 text-accent" /> Upload customer data (CSV)
        </h2>
        <div className="grid sm:grid-cols-3 gap-3">
          <div>
            <Label htmlFor="ds-name">Dataset name</Label>
            <Input
              id="ds-name"
              data-testid="data-imports-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={uploading}
              placeholder="e.g. Joint pain 2024"
            />
          </div>
          <div>
            <Label htmlFor="ds-category">Problem / disease</Label>
            <Input
              id="ds-category"
              value={problemCategory}
              onChange={(e) => setProblemCategory(e.target.value)}
              disabled={uploading}
              placeholder="e.g. Joint pain"
            />
          </div>
          <div>
            <Label htmlFor="ds-source">Source label</Label>
            <Input
              id="ds-source"
              value={sourceLabel}
              onChange={(e) => setSourceLabel(e.target.value)}
              disabled={uploading}
              placeholder="Uploaded Data"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="ds-file">Upload .csv (optional)</Label>
          <Input
            id="ds-file"
            type="file"
            accept=".csv,text/csv"
            disabled={uploading}
            data-testid="data-imports-file"
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          />
          {fileName && (
            <div className="text-[11px] text-muted-foreground mt-1">{fileName}</div>
          )}
        </div>
        <div>
          <Label htmlFor="ds-csv">CSV content</Label>
          <Textarea
            id="ds-csv"
            data-testid="data-imports-csv"
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
            disabled={uploading}
            rows={6}
            placeholder={CSV_PLACEHOLDER}
            className="font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground mt-1">
            Accepted columns (auto-detected): name, phone/mobile, problem/disease,
            city, state, notes, product/medicine, source, old status, last order date.
            Phone is required; duplicates (in-file or vs existing CRM) are flagged, not created.
          </p>
        </div>
        <Button type="submit" disabled={uploading} data-testid="data-imports-upload-submit">
          {uploading ? "Uploading…" : "Upload + validate"}
        </Button>

        {lastResult && (
          <div
            className="rounded-lg border border-border p-3 text-sm space-y-2"
            data-testid="data-imports-result"
          >
            <div className="flex flex-wrap gap-4">
              <SummaryStat label="Total" value={lastResult.totalRows} />
              <SummaryStat label="Valid" value={lastResult.validRows} tone="success" />
              <SummaryStat label="Duplicates" value={lastResult.duplicateRows} tone="warning" />
              <SummaryStat label="Invalid" value={lastResult.invalidRows} tone="danger" />
            </div>
            {lastResult.problemBreakdown.length > 0 && (
              <div className="text-[12px] text-muted-foreground">
                Problem-wise:{" "}
                {lastResult.problemBreakdown
                  .map((p) => `${p.problemCategory} (${p.count})`)
                  .join(", ")}
              </div>
            )}
            {lastResult.errorSamples.length > 0 && (
              <div className="rounded-lg bg-muted/50 p-2.5 text-xs max-h-40 overflow-auto">
                <div className="font-medium mb-1">Rejected row samples (phones masked):</div>
                <ul className="space-y-1">
                  {lastResult.errorSamples.map((s, idx) => (
                    <li key={`${s.rowNumber}-${idx}`}>
                      <span className="font-mono mr-2">row {s.rowNumber}</span>
                      {s.reason}
                      <span className="ml-1 text-muted-foreground">(****{s.phoneLast4})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </form>

      {/* Datasets list */}
      <div className="surface-elevated p-6">
        <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
          <Database className="h-5 w-5 text-accent" /> Uploaded datasets ({datasets.length})
        </h2>
        {loading ? (
          <p className="text-muted-foreground text-[14px]">Loading…</p>
        ) : datasets.length === 0 ? (
          <p data-testid="data-imports-empty" className="text-muted-foreground text-[14px]">
            No datasets uploaded yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid="data-imports-table" className="w-full text-[13.5px] border-collapse">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="py-2 pr-3">S.N.</th>
                  <th className="py-2 pr-3">Name</th>
                  <th className="py-2 pr-3">Problem</th>
                  <th className="py-2 pr-3">Total</th>
                  <th className="py-2 pr-3">Valid</th>
                  <th className="py-2 pr-3">Dup</th>
                  <th className="py-2 pr-3">Invalid</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((d, idx) => (
                  <tr key={d.id} className="border-b border-border/60 last:border-0">
                    <td className="py-2 pr-3 text-muted-foreground">{idx + 1}</td>
                    <td className="py-2 pr-3 font-medium">{d.name}</td>
                    <td className="py-2 pr-3">{d.problemCategory || "—"}</td>
                    <td className="py-2 pr-3 tabular-nums">{d.totalRows}</td>
                    <td className="py-2 pr-3 tabular-nums text-success">{d.validRows}</td>
                    <td className="py-2 pr-3 tabular-nums text-warning">{d.duplicateRows}</td>
                    <td className="py-2 pr-3 tabular-nums text-destructive">{d.invalidRows}</td>
                    <td className="py-2 pr-3 capitalize">{d.status}</td>
                    <td className="py-2 pr-3">
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`data-imports-create-campaign-${d.id}`}
                        disabled={creatingFor === d.id || d.validRows <= 0}
                        onClick={() => handleCreateCampaign(d)}
                      >
                        {creatingFor === d.id ? "Creating…" : "Create campaign"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "danger"
          ? "text-destructive"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${toneClass}`}>{value}</div>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "danger"
          ? "text-destructive"
          : "text-foreground";
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${toneClass}`}>{value}</div>
    </div>
  );
}
