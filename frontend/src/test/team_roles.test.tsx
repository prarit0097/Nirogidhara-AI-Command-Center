import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getTeamRoles: vi.fn(),
      assignTeamRole: vi.fn(),
      // Representative provider/business method — must never fire here.
      createDirectorBriefingReview: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import TeamRoles from "@/pages/TeamRoles";
import { api } from "@/services/api";

const ROLE_OPTIONS = [
  { value: "director_admin", label: "Director / Admin" },
  { value: "calling_agent", label: "Calling Agent" },
  { value: "confirmation_team", label: "Confirmation Team" },
  { value: "read_only_viewer", label: "Read-only Viewer" },
];

const ROLES_RESPONSE = {
  members: [
    {
      userId: 7,
      username: "ops",
      displayName: "Ops User",
      emailMasked: "o***@nirogidhara.test",
      accountRole: "operations",
      operationalRole: "read_only_viewer",
      operationalRoleLabel: "Read-only Viewer",
      isActive: true,
      notes: "",
      assignedAt: null,
    },
  ],
  total: 1,
  operationalRoleOptions: ROLE_OPTIONS,
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <TeamRoles />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getTeamRoles as any).mockResolvedValue(ROLES_RESPONSE);
  (api.assignTeamRole as any).mockResolvedValue({
    ...ROLES_RESPONSE.members[0],
    operationalRole: "calling_agent",
    operationalRoleLabel: "Calling Agent",
  });
});

describe("Phase 16C — Team Roles page", () => {
  it("renders members + the operational-role table", async () => {
    renderPage();
    expect(await screen.findByTestId("team-roles-page")).toBeInTheDocument();
    expect(screen.getByTestId("team-roles-table")).toBeInTheDocument();
    expect(screen.getByText("Ops User")).toBeInTheDocument();
    expect(screen.getByText("o***@nirogidhara.test")).toBeInTheDocument();
  });

  it("renders a clean empty state when there are no members", async () => {
    (api.getTeamRoles as any).mockResolvedValue({
      members: [],
      total: 0,
      operationalRoleOptions: ROLE_OPTIONS,
    });
    renderPage();
    expect(await screen.findByTestId("team-roles-empty")).toBeInTheDocument();
  });

  it("assigns a new operational role via the internal API only", async () => {
    renderPage();
    await screen.findByTestId("team-roles-table");

    fireEvent.change(screen.getByTestId("team-role-select-7"), {
      target: { value: "calling_agent" },
    });
    fireEvent.click(screen.getByTestId("team-role-save-7"));

    await waitFor(() =>
      expect(api.assignTeamRole).toHaveBeenCalledTimes(1),
    );
    expect(api.assignTeamRole).toHaveBeenCalledWith({
      userId: 7,
      operationalRole: "calling_agent",
    });
    // No briefing/provider path fired from the team-roles page.
    expect(api.createDirectorBriefingReview).not.toHaveBeenCalled();
  });

  it("disables Save until the role is changed", async () => {
    renderPage();
    await screen.findByTestId("team-roles-table");
    // Initial draft equals current operationalRole → Save disabled.
    expect(screen.getByTestId("team-role-save-7")).toBeDisabled();
  });
});
