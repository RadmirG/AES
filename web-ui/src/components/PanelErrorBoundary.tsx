import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; name: string; resetKeys: readonly unknown[] };

export class PanelErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`AES ${this.props.name} rendering failed`, error, info.componentStack);
  }

  componentDidUpdate(previous: Props) {
    if (this.state.failed && (previous.resetKeys.length !== this.props.resetKeys.length ||
      this.props.resetKeys.some((key, index) => !Object.is(key, previous.resetKeys[index])))) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return <section className="card panelRecovery" role="alert">
        <h3>{this.props.name} could not be displayed</h3>
        <p>Your chats and stored results have not been deleted. You can continue using the other panel or select another conversation.</p>
        <button type="button" onClick={() => this.setState({ failed: false })}>Retry this view</button>
      </section>;
    }
    return this.props.children;
  }
}
