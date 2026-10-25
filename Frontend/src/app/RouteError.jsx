import { TriangleAlert } from 'lucide-react'
import Button from '../components/ui/Button.jsx'
import { EmptyState } from '../components/ui/States.jsx'

/** Last-resort screen if rendering a route throws: the page is never left blank. */
export default function RouteError() {
  return (
    <main className="auth-page">
      <EmptyState
        icon={TriangleAlert}
        title="Something went wrong"
        actions={
          <Button variant="primary" onClick={() => window.location.assign('/')}>
            Back to the home page
          </Button>
        }
      >
        An unexpected error stopped this page from loading.
      </EmptyState>
    </main>
  )
}
