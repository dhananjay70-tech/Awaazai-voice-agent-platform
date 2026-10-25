import { useCallback, useState } from 'react'
import { clampSidebarWidth, readStoredWidth, storeWidth } from '../utils/sidebarWidth.js'

/** The sidebar's width: live while dragging, remembered in this browser once a resize is finished. */
export function useSidebarWidth() {
  const [width, setWidth] = useState(readStoredWidth)
  const [resizing, setResizing] = useState(false)

  const change = useCallback((next) => setWidth(clampSidebarWidth(next)), [])
  const commit = useCallback((next) => storeWidth(next), [])

  return { width, resizing, change, commit, setResizing }
}
