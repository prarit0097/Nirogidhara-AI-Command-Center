import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Login from "@/pages/Login";

vi.mock("@/services/api", () => ({
  api: {
    login: vi.fn(),
  },
}));

import { api } from "@/services/api";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe("Phase 13A — Director Login page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders email and password inputs and a sign-in button", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign in/i }),
    ).toBeInTheDocument();
  });

  it("on successful login, saves the JWT and navigates", async () => {
    (api.login as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      access: "fake-jwt-token-xyz",
    });
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "pwd123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(window.localStorage.getItem("nirogidhara.jwt")).toBe(
        "fake-jwt-token-xyz",
      );
    });
    expect(mockNavigate).toHaveBeenCalledWith("/saas-admin", {
      replace: true,
    });
  });

  it("on failed login, shows an error and does not navigate", async () => {
    (api.login as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Invalid credentials"),
    );
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /invalid credentials/i,
      );
    });
    expect(window.localStorage.getItem("nirogidhara.jwt")).toBeNull();
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
