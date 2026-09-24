import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** Shown above the message; defaults to a generic page-level title. */
  title?: string;
  /** Reset the boundary when this changes (e.g. the route path). */
  resetKey?: string;
};

type State = { error: Error | null };

/**
 * A lazily loaded page whose code is gone: the app was upgraded while this tab
 * (or installed app) stayed open, and the old build's chunks no longer exist.
 * Chrome, Safari and Firefox word it differently.
 */
export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
    message,
  );
}

/**
 * Catches render errors of one route (or the whole app) so a broken page shows
 * a message and a "try again" button instead of a blank screen. Phase 4.6.
 */
export default class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The console is the only sink we have in the browser; server-side error
    // reporting is a Phase 4.7 item.
    console.error("Route render failed", error, info.componentStack);
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    if (isChunkLoadError(this.state.error)) {
      // Trying again would fetch the same missing file; only a reload helps.
      return (
        <div className="route-error card" role="alert">
          <h2>Alpharouter was updated</h2>
          <p className="muted">Reload to continue.</p>
          <div className="route-error__actions">
            <button type="button" className="btn" onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
        </div>
      );
    }
    return (
      <div className="route-error card" role="alert">
        <h2>{this.props.title ?? "This page could not be displayed"}</h2>
        <p className="muted">{this.state.error.message || String(this.state.error)}</p>
        <div className="route-error__actions">
          <button type="button" className="btn" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    );
  }
}
