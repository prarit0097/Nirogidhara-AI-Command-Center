import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function BoomChild(): never {
  throw new Error("boom");
}

describe("Phase 13C — ErrorBoundary", () => {
  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary sectionName="Test">
        <div>OK</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("catches a thrown error and shows fallback UI with section name", () => {
    const originalError = console.error;
    console.error = () => {};
    try {
      render(
        <ErrorBoundary sectionName="Test Section">
          <BoomChild />
        </ErrorBoundary>,
      );
      expect(
        screen.getByText(/Test Section failed to render/i),
      ).toBeInTheDocument();
      expect(screen.getByText(/Try again/i)).toBeInTheDocument();
    } finally {
      console.error = originalError;
    }
  });

  it("resets to children on Try again click after error is removed", () => {
    const originalError = console.error;
    console.error = () => {};
    try {
      const { rerender } = render(
        <ErrorBoundary sectionName="Test">
          <BoomChild />
        </ErrorBoundary>,
      );
      expect(screen.getByText(/failed to render/i)).toBeInTheDocument();
      rerender(
        <ErrorBoundary sectionName="Test">
          <div>fresh content</div>
        </ErrorBoundary>,
      );
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
      expect(screen.getByText("fresh content")).toBeInTheDocument();
    } finally {
      console.error = originalError;
    }
  });
});
