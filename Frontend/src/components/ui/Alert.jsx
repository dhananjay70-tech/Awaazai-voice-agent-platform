import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import { ApiError } from '../../api/client.js'

const ICONS = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle }

export default function Alert({ tone = 'info', title, children, meta, ...rest }) {
  const Icon = ICONS[tone]
  return (
    <div className={`alert alert-${tone}`} role={tone === 'error' ? 'alert' : 'status'} {...rest}>
      <Icon size={18} aria-hidden="true" />
      <div className="alert-body">
        {title && <strong>{title}</strong>}
        {children && <span>{children}</span>}
        {meta && <span className="alert-meta">{meta}</span>}
      </div>
    </div>
  )
}

/** An Alert for any thrown error: shows the friendly message and the request id when the server sent one. */
export function ErrorAlert({ error, title }) {
  if (!error) return null
  const message = error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
  return (
    <Alert tone="error" title={title} meta={error instanceof ApiError ? error.diagnostic : null}>
      {message}
    </Alert>
  )
}
