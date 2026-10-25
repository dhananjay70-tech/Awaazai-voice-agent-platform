import { Link } from 'react-router-dom'

/**
 * One button for every action. Pass `to` for internal navigation (renders a link), `loading` to show a spinner and
 * block clicks while a request is in progress.
 */
export default function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  block = false,
  icon: Icon,
  to,
  className = '',
  children,
  disabled,
  type = 'button',
  ...rest
}) {
  const classes = [
    'btn',
    variant === 'primary' && 'btn-primary',
    variant === 'ghost' && 'btn-ghost',
    variant === 'outline' && 'btn-outline',
    variant === 'danger' && 'btn-danger',
    size === 'sm' && 'btn-sm',
    size === 'lg' && 'btn-lg',
    block && 'btn-block',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  const content = (
    <>
      {loading ? <span className="spinner" aria-hidden="true" /> : Icon ? <Icon size={size === 'sm' ? 15 : 17} aria-hidden="true" /> : null}
      {children}
    </>
  )
  if (to) {
    return (
      <Link to={to} className={classes} {...rest}>
        {content}
      </Link>
    )
  }
  return (
    <button type={type} className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {content}
    </button>
  )
}
