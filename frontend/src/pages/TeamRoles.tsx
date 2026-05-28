import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { api, isApiError } from "@/services/api";
import type { TeamRoleMember, TeamRolesResponse } from "@/types/domain";
import { ShieldCheck, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

export default function TeamRoles() {
  const [data, setData] = useState<TeamRolesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  // Per-user draft operational role (keyed by userId) + in-flight save flag.
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    api
      .getTeamRoles()
      .then((res) => {
        setData(res);
        const initial: Record<number, string> = {};
        for (const m of res.members) {
          initial[m.userId] = m.operationalRole || "read_only_viewer";
        }
        setDrafts(initial);
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleSave = async (member: TeamRoleMember) => {
    const operationalRole = drafts[member.userId];
    if (!operationalRole) return;
    setSavingId(member.userId);
    try {
      await api.assignTeamRole({
        userId: member.userId,
        operationalRole,
      });
      toast.success(`Role saved for ${member.displayName} (internal label).`);
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Could not save role (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Could not save role. Please retry.");
      }
    } finally {
      setSavingId(null);
    }
  };

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading team roles...
      </div>
    );
  }

  const members = data?.members ?? [];
  const options = data?.operationalRoleOptions ?? [];

  return (
    <div data-testid="team-roles-page">
      <PageHeader
        eyebrow="Governance"
        title="Team Roles"
        description="Assign internal operational-team labels for Nirogidhara operations. Labels are for coordination only — they grant no provider access and activate no automation."
      />

      <div className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground">
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Internal coordination only: assigning a role does not enable WhatsApp,
          payment, courier, calling, or any provider workflow.
        </span>
      </div>

      <div className="surface-elevated p-6">
        <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
          <Users className="h-5 w-5 text-accent" /> Members ({members.length})
        </h2>

        {members.length === 0 ? (
          <p
            data-testid="team-roles-empty"
            className="text-muted-foreground text-[14px]"
          >
            No team members found yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table
              data-testid="team-roles-table"
              className="w-full text-[13.5px] border-collapse"
            >
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="py-2 pr-3">S.N.</th>
                  <th className="py-2 pr-3">User</th>
                  <th className="py-2 pr-3">Account role</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Operational role</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {members.map((m, idx) => (
                  <tr
                    key={m.userId}
                    className="border-b border-border/60 last:border-0"
                  >
                    <td className="py-2 pr-3 text-muted-foreground">{idx + 1}</td>
                    <td className="py-2 pr-3">
                      <div className="font-medium">{m.displayName}</div>
                      <div className="text-[12px] text-muted-foreground">
                        {m.emailMasked || m.username}
                      </div>
                    </td>
                    <td className="py-2 pr-3 capitalize">{m.accountRole || "—"}</td>
                    <td className="py-2 pr-3">
                      <span
                        className={
                          m.isActive
                            ? "text-success"
                            : "text-muted-foreground"
                        }
                      >
                        {m.isActive ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <select
                        data-testid={`team-role-select-${m.userId}`}
                        aria-label={`Operational role for ${m.displayName}`}
                        value={drafts[m.userId] ?? "read_only_viewer"}
                        onChange={(e) =>
                          setDrafts((d) => ({
                            ...d,
                            [m.userId]: e.target.value,
                          }))
                        }
                        className="h-9 rounded-md border border-input bg-background px-2 text-[13px]"
                      >
                        {options.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2 pr-3">
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`team-role-save-${m.userId}`}
                        disabled={
                          savingId === m.userId ||
                          drafts[m.userId] === m.operationalRole
                        }
                        onClick={() => handleSave(m)}
                      >
                        {savingId === m.userId ? "Saving..." : "Save"}
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
