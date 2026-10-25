import { useEffect, useRef } from 'react'
import { SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN, widthFromDrag, widthFromKey } from '../../utils/sidebarWidth.js'

/**
 * The draggable divider on the sidebar's right edge. Mouse, touch and pen use pointer events with pointer capture, so
 * the element itself receives every move until release and no listener has to be added to (or removed from) the
 * document. Keyboard: Left/Right resize (Shift = larger steps), Home/End jump to the limits, Enter or a double click
 * restores the default width.
 *
 * onChange(width)   every intermediate width (the layout follows immediately)
 * onCommit(width)   the final width, once the drag or key press is done (the caller stores it)
 * onDragging(bool)  true while a drag is in progress (the caller disables transitions and text selection)
 */
export default function SidebarResizer({ width, onChange, onCommit, onDragging }) {
  const drag = useRef(null) // { pointerId, startX, startWidth, latest } while dragging
  const draggingRef = useRef(onDragging)
  useEffect(() => {
    draggingRef.current = onDragging
  })
  useEffect(
    () => () => {
      if (drag.current) draggingRef.current?.(false) // unmounted mid-drag: never leave the layout stuck in "resizing"
    },
    [],
  )

  function begin(event) {
    if (event.button !== undefined && event.button !== 0) return
    event.preventDefault()
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: width, latest: width }
    event.currentTarget.setPointerCapture?.(event.pointerId)
    onDragging(true)
  }

  function move(event) {
    const current = drag.current
    if (!current || event.pointerId !== current.pointerId) return
    current.latest = widthFromDrag(current.startWidth, current.startX, event.clientX)
    onChange(current.latest)
  }

  function end(event) {
    const current = drag.current
    if (!current || event.pointerId !== current.pointerId) return
    drag.current = null
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    onDragging(false)
    onCommit(current.latest)
  }

  function onKeyDown(event) {
    const next = widthFromKey(width, event.key, { shift: event.shiftKey })
    if (next === null) return
    event.preventDefault()
    onChange(next)
    onCommit(next)
  }

  function reset() {
    onChange(SIDEBAR_DEFAULT)
    onCommit(SIDEBAR_DEFAULT)
  }

  return (
    // A focusable separator is the ARIA pattern for a resizable split: it announces its value and limits.
    <div
      className="sidebar-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={width}
      aria-valuemin={SIDEBAR_MIN}
      aria-valuemax={SIDEBAR_MAX}
      tabIndex={0}
      onPointerDown={begin}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onKeyDown={onKeyDown}
      onDoubleClick={reset}
    >
      <span className="sidebar-grip" aria-hidden="true" />
    </div>
  )
}
