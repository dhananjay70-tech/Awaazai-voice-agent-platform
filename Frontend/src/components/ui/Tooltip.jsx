import { useId } from 'react'

/**
 * Text bubble for a control whose label is not visible (an icon button, a collapsed sidebar item). It shows on hover
 * and keyboard focus and is linked with aria-describedby; it never holds anything interactive. Pass `disabled` to
 * render the children alone.
 */
export default function Tooltip({ text, children, side = 'right', disabled = false }) {
  const id = useId()
  if (disabled) return children
  return (
    <span className={`tooltip-host tooltip-${side}`}>
      <span aria-describedby={id} className="tooltip-anchor">
        {children}
      </span>
      <span role="tooltip" id={id} className="tooltip">
        {text}
      </span>
    </span>
  )
}
