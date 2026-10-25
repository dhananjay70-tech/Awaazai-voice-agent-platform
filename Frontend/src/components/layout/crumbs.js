import { useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'

/** A page that knows a better name for itself than its URL (an agent's name) reports it to the header breadcrumbs. */
export function useCrumbLabel(label) {
  const context = useOutletContext()
  const setCrumbLabel = context?.setCrumbLabel
  useEffect(() => {
    setCrumbLabel?.(label ?? null)
    return () => setCrumbLabel?.(null)
  }, [label, setCrumbLabel])
}
