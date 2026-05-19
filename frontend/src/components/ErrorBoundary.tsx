import React, { type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional friendly section name shown in the fallback UI. */
  sectionName?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error(
      `[ErrorBoundary] ${this.props.sectionName ?? "section"} crashed:`,
      error,
      errorInfo,
    );
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="m-4 rounded-lg border border-destructive/30 bg-destructive/5 p-6">
          <h2 className="text-base font-semibold text-destructive">
            {this.props.sectionName ?? "Section"} failed to render
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            This section hit a runtime error. Other parts of the page should
            still work.
          </p>
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              Show error details
            </summary>
            <pre className="mt-2 max-h-64 overflow-auto rounded bg-background p-3 text-xs whitespace-pre-wrap">
              {this.state.error?.toString()}
              {"\n\n"}
              {this.state.error?.stack}
            </pre>
          </details>
          <button
            type="button"
            onClick={this.handleReset}
            className="mt-3 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
