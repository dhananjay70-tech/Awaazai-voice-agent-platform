import { Component } from 'react'
import Button from './Button.jsx'
import { EmptyState } from './States.jsx'
import { TriangleAlert } from 'lucide-react'

/** Keeps one broken screen from blanking the whole app. */
export default class ErrorBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    console.error('Unhandled UI error:', error.message)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <EmptyState
        icon={TriangleAlert}
        title="This page hit an unexpected error"
        actions={<Button variant="primary" onClick={() => window.location.reload()}>Reload the page</Button>}
      >
        Your work on other pages is not affected. Reloading signs you out because the session is kept in memory only.
      </EmptyState>
    )
  }
}
