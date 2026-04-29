import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/services/api";
import { connectAuditEvents } from "@/services/realtime";
import type {
  ActivityEvent,
  WhatsAppConversation,
  WhatsAppInboxCounts,
  WhatsAppInboxSummary,
  WhatsAppInternalNote,
  WhatsAppMessage,
  WhatsAppTemplate,
} from "@/types/domain";
import {
  CheckCheck,
  Clock,
  Eye,
  MessageCircle,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  StickyNote,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

type FilterKey = "all" | "unread" | "open" | "pending" | "resolved";

const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "open", label: "Open" },
  { key: "pending", label: "Pending" },
  { key: "resolved", label: "Resolved" },
];

const STATUS_TONES: Record<
  WhatsAppMessage["status"],
  "success" | "info" | "warning" | "danger" | "neutral"
> = {
  queued: "info",
  sent: "info",
  delivered: "success",
  read: "success",
  failed: "danger",
};

export default function WhatsAppInboxPage() {
  const [inbox, setInbox] = useState<WhatsAppInboxSummary | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<WhatsAppMessage[]>([]);
  const [notes, setNotes] = useState<WhatsAppInternalNote[]>([]);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [noteDraft, setNoteDraft] = useState("");
  const [showSendModal, setShowSendModal] = useState(false);

  const refreshInbox = useCallback(async () => {
    const data = await api.getWhatsAppInbox();
    setInbox(data);
    if (!activeId && data.conversations.length > 0) {
      setActiveId(data.conversations[0].id);
    }
  }, [activeId]);

  const refreshThread = useCallback(async (id: string) => {
    const [m, n] = await Promise.all([
      api.getWhatsAppConversationMessages(id),
      api.getWhatsAppConversationNotes(id),
    ]);
    setMessages(m);
    setNotes(n);
  }, []);

  useEffect(() => {
    void refreshInbox();
    void api.listWhatsAppTemplates({ status: "APPROVED" }).then((rows) => {
      setTemplates(rows.filter((t) => t.isActive));
    });
  }, [refreshInbox]);

  useEffect(() => {
    if (!activeId) return;
    void refreshThread(activeId);
  }, [activeId, refreshThread]);

  // Realtime — refresh on whatsapp.* AuditEvents.
  useEffect(() => {
    const controller = connectAuditEvents({
      onEvent: (event: ActivityEvent) => {
        if (typeof event.kind !== "string") return;
        if (!event.kind.startsWith("whatsapp.")) return;
        void refreshInbox();
        if (activeId) {
          void refreshThread(activeId);
        }
      },
    });
    return () => controller.close();
  }, [activeId, refreshInbox, refreshThread]);

  const filteredConversations = useMemo(() => {
    if (!inbox) return [];
    let list = [...inbox.conversations];
    if (filter === "unread") list = list.filter((c) => c.unreadCount > 0);
    else if (filter !== "all")
      list = list.filter((c) => c.status === filter);
    const needle = search.trim().toLowerCase();
    if (needle) {
      list = list.filter(
        (c) =>
          c.customerName.toLowerCase().includes(needle) ||
          c.customerPhone.toLowerCase().includes(needle) ||
          c.lastMessageText.toLowerCase().includes(needle) ||
          c.subject.toLowerCase().includes(needle),
      );
    }
    return list;
  }, [inbox, filter, search]);

  const activeConversation =
    inbox?.conversations.find((c) => c.id === activeId) ?? null;

  const counts: WhatsAppInboxCounts =
    inbox?.counts ?? {
      all: 0,
      unread: 0,
      open: 0,
      pending: 0,
      resolved: 0,
      escalatedToHuman: 0,
    };

  const handleMarkRead = async () => {
    if (!activeId) return;
    await api.markWhatsAppConversationRead(activeId);
    await refreshInbox();
    toast.success("Marked as read");
  };

  const handleAddNote = async () => {
    if (!activeId || !noteDraft.trim()) return;
    try {
      const note = await api.createWhatsAppConversationNote(activeId, {
        body: noteDraft.trim(),
      });
      setNotes((prev) => [note, ...prev]);
      setNoteDraft("");
      toast.success("Internal note saved");
    } catch (error) {
      toast.error(`Could not save note: ${(error as Error).message}`);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="WhatsApp · Phase 5B"
        title="Inbox"
        description="Inbound conversations, internal notes and manual approved-template sends. Backend gates remain final — consent + Claim Vault + approval matrix + CAIO refusal still enforce on every send."
      />

      <div className="grid grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)_360px] gap-4 min-h-[640px]">
        {/* Left pane — filters + search */}
        <div className="surface-card p-4 space-y-4">
          <div className="space-y-1.5">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`w-full flex items-center justify-between rounded-lg px-3 py-2 text-sm transition ${
                  filter === f.key
                    ? "bg-gradient-emerald-soft border border-primary/20 text-foreground"
                    : "hover:bg-muted/60 text-muted-foreground"
                }`}
              >
                <span>{f.label}</span>
                <StatusPill tone={filter === f.key ? "success" : "neutral"}>
                  {countFor(f.key, counts)}
                </StatusPill>
              </button>
            ))}
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1.5">
              Search
            </div>
            <div className="relative">
              <Search className="h-4 w-4 absolute left-2 top-2.5 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="name, phone, text"
                className="pl-8"
              />
            </div>
          </div>
          <div className="rounded-xl bg-muted/40 p-3 text-xs text-muted-foreground">
            <div className="flex items-center gap-2 mb-1">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
              <span className="font-medium text-foreground">AI suggestions</span>
            </div>
            <StatusPill tone="neutral">
              {inbox?.aiSuggestions.status ?? "disabled"}
            </StatusPill>
            <p className="mt-2 leading-relaxed">
              {inbox?.aiSuggestions.message ??
                "AI WhatsApp suggestions are planned for Phase 5C. Phase 5B is manual-only."}
            </p>
          </div>
        </div>

        {/* Middle pane — conversation list */}
        <div className="surface-card p-3 space-y-1.5 max-h-[720px] overflow-auto scrollbar-thin">
          {filteredConversations.length === 0 && (
            <div className="text-sm text-muted-foreground p-6 text-center">
              No conversations match this filter yet.
            </div>
          )}
          {filteredConversations.map((c) => (
            <ConversationCard
              key={c.id}
              conversation={c}
              active={c.id === activeId}
              onClick={() => setActiveId(c.id)}
            />
          ))}
        </div>

        {/* Right pane — thread + notes + send */}
        <div className="surface-card flex flex-col max-h-[720px]">
          {!activeConversation ? (
            <div className="flex-1 grid place-items-center text-sm text-muted-foreground">
              Select a conversation
            </div>
          ) : (
            <ThreadPane
              conversation={activeConversation}
              messages={messages}
              notes={notes}
              templates={templates}
              noteDraft={noteDraft}
              onNoteDraftChange={setNoteDraft}
              onAddNote={handleAddNote}
              onMarkRead={handleMarkRead}
              onSendClick={() => setShowSendModal(true)}
              aiMessage={
                inbox?.aiSuggestions.message ??
                "AI WhatsApp suggestions are planned for Phase 5C."
              }
            />
          )}
        </div>
      </div>

      {showSendModal && activeConversation && (
        <TemplateSendModal
          conversation={activeConversation}
          templates={templates}
          onClose={() => setShowSendModal(false)}
          onSent={async () => {
            setShowSendModal(false);
            if (activeId) await refreshThread(activeId);
            await refreshInbox();
          }}
        />
      )}
    </>
  );
}

function countFor(key: FilterKey, counts: WhatsAppInboxCounts): number {
  if (key === "all") return counts.all;
  if (key === "unread") return counts.unread;
  if (key === "open") return counts.open;
  if (key === "pending") return counts.pending;
  if (key === "resolved") return counts.resolved;
  return 0;
}

interface ConversationCardProps {
  conversation: WhatsAppConversation;
  active: boolean;
  onClick: () => void;
}

function ConversationCard({
  conversation,
  active,
  onClick,
}: ConversationCardProps) {
  const initials =
    (conversation.customerName || "?")
      .split(" ")
      .map((n) => n[0] ?? "")
      .slice(0, 2)
      .join("") || "?";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left rounded-xl px-3 py-2.5 transition ${
        active
          ? "bg-gradient-emerald-soft border border-primary/20"
          : "hover:bg-muted/60"
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div className="h-9 w-9 rounded-full bg-gradient-hero text-primary-foreground grid place-items-center text-xs font-semibold shrink-0">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium truncate flex-1">
              {conversation.customerName || conversation.customerPhone || "Unknown"}
            </div>
            {conversation.unreadCount > 0 && (
              <span className="inline-flex items-center justify-center text-[10px] font-semibold rounded-full bg-primary text-primary-foreground h-5 min-w-[1.25rem] px-1">
                {conversation.unreadCount}
              </span>
            )}
          </div>
          <div className="text-[11px] text-muted-foreground truncate">
            {conversation.lastMessageText || conversation.customerPhone}
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <StatusPill
              tone={
                conversation.status === "resolved"
                  ? "success"
                  : conversation.status === "escalated_to_human"
                    ? "danger"
                    : conversation.status === "pending"
                      ? "warning"
                      : "info"
              }
            >
              {conversation.status}
            </StatusPill>
            {conversation.lastMessageAt && (
              <span className="text-[10px] text-muted-foreground inline-flex items-center gap-0.5">
                <Clock className="h-3 w-3" />
                {formatRelative(conversation.lastMessageAt)}
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

interface ThreadPaneProps {
  conversation: WhatsAppConversation;
  messages: WhatsAppMessage[];
  notes: WhatsAppInternalNote[];
  templates: WhatsAppTemplate[];
  noteDraft: string;
  onNoteDraftChange: (value: string) => void;
  onAddNote: () => void;
  onMarkRead: () => void;
  onSendClick: () => void;
  aiMessage: string;
}

function ThreadPane({
  conversation,
  messages,
  notes,
  templates,
  noteDraft,
  onNoteDraftChange,
  onAddNote,
  onMarkRead,
  onSendClick,
  aiMessage,
}: ThreadPaneProps) {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-5 py-4 border-b border-border flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-display text-base font-semibold truncate">
            {conversation.customerName || "Unknown customer"}
          </div>
          <div className="text-xs text-muted-foreground truncate">
            {conversation.customerPhone}
            {conversation.assignedToUsername
              ? ` · assigned to ${conversation.assignedToUsername}`
              : ""}
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={onMarkRead}
            disabled={conversation.unreadCount === 0}
          >
            <Eye className="h-3.5 w-3.5" /> Mark read
          </Button>
          <Button
            size="sm"
            className="gap-1.5 bg-gradient-hero text-primary-foreground"
            onClick={onSendClick}
            disabled={templates.length === 0}
          >
            <Send className="h-3.5 w-3.5" /> Send template
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin px-5 py-4 space-y-2.5 bg-muted/20">
        {messages.length === 0 && (
          <div className="text-sm text-muted-foreground text-center py-8">
            No messages yet.
          </div>
        )}
        {[...messages].reverse().map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>

      <div className="border-t border-border bg-background">
        <div className="px-5 py-3 space-y-2">
          <div className="rounded-lg bg-muted/40 p-2.5 text-xs flex items-start gap-2">
            <Sparkles className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-medium text-foreground">
                AI suggestions
              </span>{" "}
              <StatusPill tone="neutral">disabled</StatusPill>
              <span className="block text-muted-foreground mt-0.5">
                {aiMessage}
              </span>
            </div>
          </div>
          <div className="rounded-lg border border-border p-2.5">
            <div className="flex items-center gap-1.5 mb-1.5 text-xs font-medium text-muted-foreground">
              <StickyNote className="h-3.5 w-3.5" /> Internal note
              <span className="text-[10px] text-muted-foreground/80">
                (never sent to customer)
              </span>
            </div>
            <Textarea
              value={noteDraft}
              onChange={(e) => onNoteDraftChange(e.target.value)}
              placeholder="Add context for the next operator…"
              className="min-h-[60px] text-sm"
            />
            <div className="flex items-center justify-between mt-2">
              <span className="text-[11px] text-muted-foreground">
                {notes.length} note{notes.length === 1 ? "" : "s"}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={onAddNote}
                disabled={!noteDraft.trim()}
              >
                Save note
              </Button>
            </div>
          </div>
          {notes.length > 0 && (
            <div className="space-y-1.5 max-h-[140px] overflow-auto scrollbar-thin">
              {notes.map((n) => (
                <div
                  key={n.id}
                  className="rounded-lg bg-muted/30 px-2.5 py-1.5 text-xs"
                >
                  <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
                    <span>{n.authorName || "operator"}</span>
                    <span>{formatRelative(n.createdAt)}</span>
                  </div>
                  <div className="text-foreground/90 mt-0.5">{n.body}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface MessageBubbleProps {
  message: WhatsAppMessage;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const outbound = message.direction === "outbound";
  const tone = STATUS_TONES[message.status];
  return (
    <div
      className={`flex ${outbound ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[78%] rounded-2xl px-3.5 py-2 text-sm shadow-sm ${
          outbound
            ? "bg-gradient-hero text-primary-foreground"
            : "bg-background border border-border"
        }`}
      >
        {message.templateName && (
          <div
            className={`text-[10px] uppercase tracking-wider mb-0.5 ${
              outbound ? "text-primary-foreground/80" : "text-muted-foreground"
            }`}
          >
            template · {message.templateName}
          </div>
        )}
        <div className="whitespace-pre-wrap break-words">{message.body}</div>
        <div
          className={`flex items-center gap-1.5 mt-1 text-[10px] ${
            outbound ? "text-primary-foreground/80" : "text-muted-foreground"
          }`}
        >
          <span>{formatRelative(message.createdAt)}</span>
          <StatusPill tone={tone}>
            {message.status === "delivered" && (
              <CheckCheck className="h-3 w-3 mr-0.5" />
            )}
            {message.status}
          </StatusPill>
        </div>
      </div>
    </div>
  );
}

interface TemplateSendModalProps {
  conversation: WhatsAppConversation;
  templates: WhatsAppTemplate[];
  onClose: () => void;
  onSent: () => void | Promise<void>;
}

function TemplateSendModal({
  conversation,
  templates,
  onClose,
  onSent,
}: TemplateSendModalProps) {
  const firstTemplate = templates[0];
  const [templateId, setTemplateId] = useState<string>(firstTemplate?.id ?? "");
  const [variablesJson, setVariablesJson] = useState<string>(
    JSON.stringify({ customer_name: conversation.customerName, context: "" }, null, 2),
  );
  const [submitting, setSubmitting] = useState(false);

  const selected = templates.find((t) => t.id === templateId) ?? firstTemplate;

  const handleSubmit = async () => {
    if (!selected) {
      toast.error("No approved template available.");
      return;
    }
    let variables: Record<string, string | number> = {};
    try {
      variables = JSON.parse(variablesJson) as Record<string, string | number>;
    } catch {
      toast.error("Variables must be valid JSON.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.sendWhatsAppConversationTemplate(conversation.id, {
        actionKey: selected.actionKey || "whatsapp.payment_reminder",
        templateId: selected.id,
        variables,
        triggeredBy: "manual_inbox_modal",
      });
      toast.success(
        res.autoApproved ? "Template queued and sent" : "Template queued",
      );
      await onSent();
    } catch (error) {
      toast.error(`Send failed: ${(error as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-foreground/30 backdrop-blur-sm p-4">
      <div className="surface-card w-full max-w-lg p-6 space-y-4">
        <div>
          <h3 className="font-display text-lg font-semibold flex items-center gap-2">
            <Zap className="h-4 w-4 text-accent" /> Send approved template
          </h3>
          <p className="text-xs text-muted-foreground">
            Backend gates remain final: consent + Claim Vault + approval matrix
            still apply.
          </p>
        </div>
        <div className="rounded-lg bg-muted/40 p-3 text-sm">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
            <ShieldCheck className="h-3.5 w-3.5" />
            Customer
          </div>
          <div className="font-medium">
            {conversation.customerName || "Unknown"}
          </div>
          <div className="text-xs text-muted-foreground">
            {conversation.customerPhone}
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs uppercase tracking-wider text-muted-foreground">
            Template
          </label>
          <select
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            {templates.length === 0 && (
              <option value="">No approved templates</option>
            )}
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}/{t.language} · {t.category}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs uppercase tracking-wider text-muted-foreground">
            Variables (JSON)
          </label>
          <Textarea
            value={variablesJson}
            onChange={(e) => setVariablesJson(e.target.value)}
            className="min-h-[120px] font-mono text-xs"
          />
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !selected}
            className="gap-1.5 bg-gradient-hero text-primary-foreground"
          >
            {submitting && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
            <MessageCircle className="h-3.5 w-3.5" />
            Queue send
          </Button>
        </div>
      </div>
    </div>
  );
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
