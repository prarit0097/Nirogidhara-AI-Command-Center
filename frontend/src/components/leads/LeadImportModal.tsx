import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/services/api";
import type { LeadImportResult } from "@/types/domain";
import { Loader2, Upload } from "lucide-react";
import { toast } from "sonner";

interface LeadImportModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (result: LeadImportResult) => void;
}

const CSV_PLACEHOLDER = `name,phone,email,source,disease,city,state,notes,consent_call,consent_whatsapp,consent_marketing
Test Lead,+91XXXXXXXXXX,,Manual,Joint pain,Mumbai,Maharashtra,Demo row,false,false,false`;

// Phase 16B — Lead CSV import modal. Accepts a CSV blob (either pasted or
// uploaded via <input type=file>) and POSTs to /api/leads/import-csv/.
// Backend response is the safe summary (createdCount / duplicateCount /
// errorCount + sanitised rowErrors with phones masked to last-4). NEVER
// triggers WhatsApp / call / payment after import.
export function LeadImportModal({ open, onOpenChange, onImported }: LeadImportModalProps) {
  const [csv, setCsv] = useState("");
  const [source, setSource] = useState("CSV Import");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<LeadImportResult | null>(null);
  const [fileName, setFileName] = useState<string>("");

  const reset = () => {
    setCsv("");
    setSource("CSV Import");
    setResult(null);
    setFileName("");
  };

  const handleFile = async (file: File | null) => {
    if (!file) {
      setFileName("");
      return;
    }
    setFileName(file.name);
    const text = await file.text();
    setCsv(text);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const trimmed = csv.trim();
    if (!trimmed) {
      toast.error("Paste CSV content or upload a CSV file first.");
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      const summary = await api.importLeadsCsv({ csv: trimmed, source: source.trim() || "CSV Import" });
      setResult(summary);
      if (summary.createdCount > 0) {
        toast.success(
          `${summary.createdCount} lead${summary.createdCount === 1 ? "" : "s"} imported (` +
          `${summary.duplicateCount} duplicate${summary.duplicateCount === 1 ? "" : "s"}, ` +
          `${summary.errorCount} error${summary.errorCount === 1 ? "" : "s"})`,
        );
        onImported(summary);
      } else if (summary.errorCount > 0 || summary.duplicateCount > 0) {
        toast.warning(
          `Imported 0 leads — ${summary.duplicateCount} duplicates, ${summary.errorCount} errors`,
        );
      } else {
        toast.info("CSV processed — no rows created or rejected.");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "CSV import failed";
      toast.error(message.slice(0, 200));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!submitting) {
          onOpenChange(o);
          if (!o) reset();
        }
      }}
    >
      <DialogContent className="sm:max-w-2xl" data-testid="lead-import-modal">
        <DialogHeader>
          <DialogTitle>Import leads from CSV</DialogTitle>
          <DialogDescription>
            Header row required. Minimum columns: <code>name</code> + <code>phone</code>.
            Optional: <code>email</code>, <code>source</code>, <code>disease</code>,
            <code>state</code>, <code>city</code>, <code>notes</code>,{" "}
            <code>consent_call</code>, <code>consent_whatsapp</code>,{" "}
            <code>consent_marketing</code>. Duplicate phones / emails (within the
            CSV or against existing Leads) are <strong>skipped</strong>, never
            overwritten. No WhatsApp / call / payment side-effects fire from import.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4" data-testid="lead-import-form">
          <div className="grid sm:grid-cols-[1fr_220px] gap-3 items-end">
            <div>
              <Label htmlFor="lead-import-source">Source label</Label>
              <Input
                id="lead-import-source"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                disabled={submitting}
                placeholder="CSV Import"
              />
            </div>
            <div>
              <Label htmlFor="lead-import-file">Upload .csv (optional)</Label>
              <Input
                id="lead-import-file"
                type="file"
                accept=".csv,text/csv"
                disabled={submitting}
                onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                data-testid="lead-import-file"
              />
              {fileName && (
                <div className="text-[11px] text-muted-foreground mt-1">{fileName}</div>
              )}
            </div>
          </div>

          <div>
            <Label htmlFor="lead-import-csv">CSV content</Label>
            <Textarea
              id="lead-import-csv"
              value={csv}
              onChange={(e) => setCsv(e.target.value)}
              disabled={submitting}
              rows={8}
              placeholder={CSV_PLACEHOLDER}
              className="font-mono text-xs"
              data-testid="lead-import-csv"
            />
          </div>

          {result && (
            <div
              className="rounded-lg border border-border p-3 space-y-2 text-sm"
              data-testid="lead-import-result"
            >
              <div className="flex flex-wrap gap-4">
                <SummaryStat label="Total rows" value={result.totalRows} />
                <SummaryStat label="Created" value={result.createdCount} tone="success" />
                <SummaryStat label="Duplicates" value={result.duplicateCount} tone="warning" />
                <SummaryStat label="Errors" value={result.errorCount} tone="danger" />
              </div>
              {result.rowErrors.length > 0 && (
                <div className="rounded-lg bg-muted/50 p-2.5 text-xs max-h-48 overflow-auto">
                  <div className="font-medium mb-1">Row issues (sanitised — phones masked to last-4):</div>
                  <ul className="space-y-1">
                    {result.rowErrors.map((re, idx) => (
                      <li key={`${re.rowNumber}-${idx}`}>
                        <span className="font-mono text-[11px] mr-2">row {re.rowNumber}</span>
                        {re.reason}
                        {re.phoneLast4 ? <span className="ml-1 text-muted-foreground">(****{re.phoneLast4})</span> : null}
                      </li>
                    ))}
                  </ul>
                  {result.truncatedErrorList && (
                    <div className="text-[11px] text-muted-foreground mt-1">
                      Error list truncated for safety. Inspect the CSV to fix the rest.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => onOpenChange(false)}
            >
              {result ? "Close" : "Cancel"}
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              data-testid="lead-import-submit"
            >
              {submitting ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Upload className="h-4 w-4 mr-1" />}
              {submitting ? "Importing…" : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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
