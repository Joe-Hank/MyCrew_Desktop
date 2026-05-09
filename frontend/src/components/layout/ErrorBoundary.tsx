import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-8">
          <span className="text-4xl">⚠️</span>
          <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            页面出现错误
          </h2>
          <p className="max-w-sm text-center text-xs text-zinc-500">
            {this.state.error?.message ?? "未知错误"}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="rounded bg-blue-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600"
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
