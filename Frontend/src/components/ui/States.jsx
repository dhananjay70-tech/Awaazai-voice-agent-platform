import { AlertCircle, RotateCw } from 'lucide-react'
import { ApiError } from '../../api/client.js'
import Button from './Button.jsx'

export function EmptyState({ icon: Icon, title, children, actions }) {
  return (
    <div className="state-panel">
      {Icon && (
        <span className="state-icon">
          <Icon size={24} aria-hidden="true" />
        </span>
      )}
      <h2 className="state-title">{title}</h2>
      {children && <p className="state-text">{children}</p>}
      {actions && <div className="state-actions">{actions}</div>}
    </div>
  )
}

/** A failed request with a way out: never leave the page blank. */
export function ErrorState({ error, title = 'Something went wrong', onRetry, actions }) {
  const message = error instanceof ApiError ? error.message : 'Please try again.'
  return (
    <div className="state-panel is-error" role="alert">
      <span className="state-icon">
        <AlertCircle size={24} aria-hidden="true" />
      </span>
      <h2 className="state-title">{title}</h2>
      <p className="state-text">{message}</p>
      {error instanceof ApiError && error.diagnostic && <p className="field-hint">{error.diagnostic}</p>}
      <div className="state-actions">
        {onRetry && (
          <Button icon={RotateCw} onClick={onRetry}>
            Try again
          </Button>
        )}
        {actions}
      </div>
    </div>
  )
}

export function Skeleton({ width = '100%', height = 16, style }) {
  return <div className="skeleton" style={{ width, height, ...style }} aria-hidden="true" />
}
