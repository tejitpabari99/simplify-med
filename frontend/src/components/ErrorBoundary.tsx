import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  // Label shown above the error text — customize per boundary instance
  // (e.g. "Something went wrong" at the app root vs a more specific message
  // wrapping just the care plan body).
  title?: string;
  // Called after the boundary clears its own error state, so a caller can
  // also reset whatever application state led here (e.g. HomePage's
  // appState machine). Optional: a boundary with no owning app state (the
  // App-root instance) can omit this and rely on the boundary resetting
  // itself plus a fresh mount of its children.
  onReset?: () => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

// React has no hook equivalent for catching render/lifecycle errors in
// children — this must be a class component. With no error boundary
// anywhere in the app, ANY uncaught exception during render (a malformed
// payload, a third-party component throwing, a resolution bug) unmounts the
// entire React tree and leaves a genuinely blank page, because there is
// nothing render()'d at all — not even sibling components like <Footer/>.
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Best-effort console diagnostics; no analytics dependency here since a
    // rendering crash is exactly the kind of moment other subsystems (GA,
    // Firestore listeners, etc.) may also be in a bad state.
    console.error('ErrorBoundary caught an error:', error, info.componentStack);
  }

  handleRestart = (): void => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error) {
      return (
        <div className="glass-card">
          <p className="section-title">{this.props.title ?? 'Something went wrong'}</p>
          <p className="error-box">
            An unexpected error occurred while showing this page. Nothing you entered was saved.
          </p>
          {error.message && (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', wordBreak: 'break-word' }}>
              {error.message}
            </p>
          )}
          <button className="cta-btn" onClick={this.handleRestart}>Start over</button>
        </div>
      );
    }
    return this.props.children;
  }
}
