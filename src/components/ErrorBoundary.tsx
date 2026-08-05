import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
  /** Shown in the heading, so the message names what failed. */
  label?: string;
}

interface State {
  error: Error | null;
  info: ErrorInfo | null;
}

/**
 * Catches a render error and shows it, rather than unmounting the app.
 *
 * Without this, any exception during render leaves an empty document body with
 * the reason visible only in the browser console. That is the same failure the
 * scan engine is built to avoid: a blank page and a clean estate look identical
 * from the outside, and neither of them is a report.
 *
 * Deliberately shows the message and stack in the page. This runs in front of
 * governance data, for an operator who has a terminal open — sparing them the
 * detail only means they have to go and find it.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info });
    console.error("Render error:", error, info.componentStack);
  }

  private reset = () => this.setState({ error: null, info: null });

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        role="alert"
        className="m-6 overflow-hidden rounded-lg border border-danger/40 bg-danger-subtle"
      >
        <div className="flex items-start gap-3 px-5 py-4">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-danger">
              {this.props.label ?? "Something failed to render"}
            </h2>
            <p className="mt-1 font-mono text-xs break-words text-danger/90">
              {error.message || String(error)}
            </p>
          </div>
          <button
            type="button"
            onClick={this.reset}
            className="flex shrink-0 items-center gap-1.5 rounded-md border border-danger/40 px-2.5 py-1.5 text-xs text-danger hover:bg-danger/10"
          >
            <RotateCcw className="size-3.5" aria-hidden />
            Retry
          </button>
        </div>

        {info?.componentStack && (
          <details className="border-t border-danger/20 px-5 py-3">
            <summary className="cursor-pointer text-xs text-danger/80">
              Component stack
            </summary>
            <pre className="mt-2 max-h-64 overflow-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-danger/70">
              {info.componentStack.trim()}
            </pre>
          </details>
        )}
      </div>
    );
  }
}
