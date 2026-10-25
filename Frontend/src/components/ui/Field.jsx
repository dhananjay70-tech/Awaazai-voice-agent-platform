import { Eye, EyeOff } from 'lucide-react'
import { useId, useState } from 'react'

/**
 * Labelled form control. `as` is 'input' | 'textarea' | 'select'. The label, hint and error are wired to the control
 * with htmlFor / aria-describedby / aria-invalid so screen readers announce them.
 */
export default function Field({ label, hint, error, as = 'input', children, className = '', ...controlProps }) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  const Control = as
  const controlClass = as === 'textarea' ? 'textarea' : as === 'select' ? 'select' : 'input'
  return (
    <div className={`field ${className}`}>
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <Control id={id} className={controlClass} aria-invalid={error ? 'true' : undefined} aria-describedby={describedBy} {...controlProps}>
        {children}
      </Control>
      {hint && (
        <p className="field-hint" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export function PasswordField({ label, hint, error, ...inputProps }) {
  const id = useId()
  const [visible, setVisible] = useState(false)
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <div className="input-wrap">
        <input
          id={id}
          className="input"
          type={visible ? 'text' : 'password'}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={describedBy}
          {...inputProps}
        />
        <button
          type="button"
          className="input-action"
          onClick={() => setVisible((value) => !value)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          aria-pressed={visible}
        >
          {visible ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
        </button>
      </div>
      {hint && (
        <p className="field-hint" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export function Switch({ label, checked, onChange, disabled }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" checked={checked} onChange={(event) => onChange(event.target.checked)} disabled={disabled} />
      <span className="switch-track" aria-hidden="true" />
      <span>{label}</span>
    </label>
  )
}
