import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { api, isApiError } from "@/services/api";
import type { CreateLeadPayload, Lead } from "@/types/domain";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

interface NewLeadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (lead: Lead) => void;
}

interface LeadFormState {
  name: string;
  phone: string;
  email: string;
  source: string;
  diseaseCategory: string;
  state: string;
  city: string;
  notes: string;
  consentCall: boolean;
  consentWhatsapp: boolean;
  consentMarketing: boolean;
}

const EMPTY_FORM: LeadFormState = {
  name: "",
  phone: "",
  email: "",
  source: "Manual",
  diseaseCategory: "",
  state: "",
  city: "",
  notes: "",
  consentCall: false,
  consentWhatsapp: false,
  consentMarketing: false,
};

// Phase 16B — New Lead modal. Replaces the prior toast-only button on the
// Leads page with a real form that POSTs /api/leads/. Captures the new
// lead-level consent triplet + intake notes + disease category. On 409
// duplicate (backend ``LeadDuplicateError``) it surfaces the existing Lead
// id so the operator can navigate to the duplicate.
export function NewLeadModal({ open, onOpenChange, onCreated }: NewLeadModalProps) {
  const [form, setForm] = useState<LeadFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [duplicate, setDuplicate] = useState<{
    field: string;
    existingLeadId: string;
  } | null>(null);

  const update = <K extends keyof LeadFormState>(key: K, value: LeadFormState[K]) => {
    setForm((s) => ({ ...s, [key]: value }));
    if (duplicate) setDuplicate(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    if (!form.name.trim() || !form.phone.trim()) {
      toast.error("Name and phone are required.");
      return;
    }
    setSubmitting(true);
    setDuplicate(null);
    const payload: CreateLeadPayload = {
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      state: form.state.trim(),
      city: form.city.trim(),
      source: form.source.trim() || "Manual",
      diseaseCategory: form.diseaseCategory.trim(),
      notes: form.notes.trim(),
      consentCall: form.consentCall,
      consentWhatsapp: form.consentWhatsapp,
      consentMarketing: form.consentMarketing,
    };
    try {
      const lead = await api.createLead(payload);
      toast.success(`Lead ${lead.id} created`);
      onCreated(lead);
      setForm(EMPTY_FORM);
      onOpenChange(false);
    } catch (err) {
      // Phase 16B-Hotfix-1: the backend returns a typed 409 for a
      // duplicate phone/email. `safeMutate` now surfaces that as a
      // typed `ApiError` (status 409 + parsed body) instead of
      // masking it with an optimistic mock. We parse the structured
      // body — `{duplicate, field, existingLeadId}` — and show a
      // clear "duplicate blocked" message. The modal STAYS OPEN and
      // NO created-success toast fires.
      if (isApiError(err) && err.httpStatus === 409) {
        const body = (err.body ?? {}) as {
          field?: string;
          existingLeadId?: string;
        };
        const field = body.field === "email" ? "email" : "phone";
        setDuplicate({
          field,
          existingLeadId: body.existingLeadId ?? "",
        });
        toast.error("Duplicate lead blocked — existing lead found.");
        return; // modal stays open; do NOT close, do NOT show created toast
      }
      // Any other failure (network/offline, validation, 5xx) — show a
      // safe error toast; do not fake success.
      const message = err instanceof Error ? err.message : "Could not create lead";
      toast.error(message.slice(0, 200));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => {
      if (!submitting) {
        onOpenChange(o);
        if (!o) {
          setForm(EMPTY_FORM);
          setDuplicate(null);
        }
      }
    }}>
      <DialogContent className="sm:max-w-lg" data-testid="new-lead-modal">
        <DialogHeader>
          <DialogTitle>New Lead</DialogTitle>
          <DialogDescription>
            Capture a new lead manually. Consent fields default to{" "}
            <strong>off</strong>; downstream WhatsApp / calling paths gate on
            these flags.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4" data-testid="new-lead-form">
          {duplicate && (
            <div
              className="rounded-lg bg-warning/10 border border-warning/30 text-warning p-3 text-xs"
              data-testid="new-lead-duplicate"
            >
              <strong>Duplicate {duplicate.field}</strong>
              {duplicate.existingLeadId
                ? ` — existing lead ${duplicate.existingLeadId}.`
                : "."}{" "}
              Update the existing lead instead of creating a new one.
            </div>
          )}

          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label htmlFor="lead-name">Name *</Label>
              <Input
                id="lead-name"
                value={form.name}
                onChange={(e) => update("name", e.target.value)}
                disabled={submitting}
                required
              />
            </div>
            <div>
              <Label htmlFor="lead-phone">Phone *</Label>
              <Input
                id="lead-phone"
                value={form.phone}
                onChange={(e) => update("phone", e.target.value)}
                disabled={submitting}
                required
                placeholder="+91…"
              />
            </div>
            <div>
              <Label htmlFor="lead-email">Email</Label>
              <Input
                id="lead-email"
                type="email"
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                disabled={submitting}
              />
            </div>
            <div>
              <Label htmlFor="lead-source">Source</Label>
              <Input
                id="lead-source"
                value={form.source}
                onChange={(e) => update("source", e.target.value)}
                disabled={submitting}
                placeholder="Manual"
              />
            </div>
            <div>
              <Label htmlFor="lead-disease">Disease / problem</Label>
              <Input
                id="lead-disease"
                value={form.diseaseCategory}
                onChange={(e) => update("diseaseCategory", e.target.value)}
                disabled={submitting}
              />
            </div>
            <div>
              <Label htmlFor="lead-state">State</Label>
              <Input
                id="lead-state"
                value={form.state}
                onChange={(e) => update("state", e.target.value)}
                disabled={submitting}
              />
            </div>
            <div>
              <Label htmlFor="lead-city">City</Label>
              <Input
                id="lead-city"
                value={form.city}
                onChange={(e) => update("city", e.target.value)}
                disabled={submitting}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="lead-notes">Notes</Label>
            <Textarea
              id="lead-notes"
              value={form.notes}
              onChange={(e) => update("notes", e.target.value)}
              disabled={submitting}
              rows={3}
            />
          </div>

          <div className="rounded-lg bg-muted/40 p-3 space-y-2">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Consent (defaults to off — explicit opt-in required for outbound)
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Checkbox
                checked={form.consentCall}
                onCheckedChange={(v) => update("consentCall", v === true)}
                disabled={submitting}
                data-testid="lead-consent-call"
              />
              <span>Call consent</span>
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Checkbox
                checked={form.consentWhatsapp}
                onCheckedChange={(v) => update("consentWhatsapp", v === true)}
                disabled={submitting}
                data-testid="lead-consent-whatsapp"
              />
              <span>WhatsApp consent</span>
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Checkbox
                checked={form.consentMarketing}
                onCheckedChange={(v) => update("consentMarketing", v === true)}
                disabled={submitting}
                data-testid="lead-consent-marketing"
              />
              <span>Marketing consent</span>
            </label>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              data-testid="new-lead-submit"
            >
              {submitting ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              {submitting ? "Saving…" : "Create lead"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
