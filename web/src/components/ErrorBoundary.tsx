import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{ padding: "2rem", textAlign: "center" }}>
          <h2>页面出现错误</h2>
          <p style={{ color: "#888", margin: "1rem 0" }}>
            {this.state.error?.message || "未知错误"}
          </p>
          <button onClick={this.handleReset} style={{ padding: "0.5rem 1.5rem" }}>
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
