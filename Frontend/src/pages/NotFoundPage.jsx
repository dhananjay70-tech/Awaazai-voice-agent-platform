import { Compass } from 'lucide-react'
import { useEffect } from 'react'
import Button from '../components/ui/Button.jsx'
import Logo from '../components/ui/Logo.jsx'
import { EmptyState } from '../components/ui/States.jsx'

export default function NotFoundPage() {
  useEffect(() => {
    document.title = 'Page not found · AwaazAI'
  }, [])
  return (
    <main className="auth-page">
      <div style={{ display: 'grid', gap: 'var(--space-5)', justifyItems: 'center', width: '100%', maxWidth: 560 }}>
        <Logo />
        <EmptyState
          icon={Compass}
          title="Page not found"
          actions={
            <>
              <Button to="/" variant="primary">
                Go to the home page
              </Button>
              <Button to="/dashboard" variant="outline">
                Open dashboard
              </Button>
            </>
          }
        >
          The page you’re looking for doesn’t exist or has moved.
        </EmptyState>
      </div>
    </main>
  )
}
