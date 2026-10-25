import { useCallback, useEffect, useState } from 'react'
import { isAbortError } from '../api/client.js'

/**
 * Load data when a component mounts. `fetcher(signal)` must be stable (wrap it in useCallback); to load something
 * else, remount the component with a different `key`. The request is cancelled on unmount.
 * Returns { data, error, loading, reload, setData }.
 */
export function useResource(fetcher) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetcher(controller.signal).then(
      (data) => setState({ data, error: null, loading: false }),
      (error) => {
        if (isAbortError(error)) return
        setState({ data: null, error, loading: false })
      },
    )
    return () => controller.abort()
  }, [fetcher, attempt])

  const reload = useCallback(() => {
    setState((current) => ({ ...current, error: null, loading: true }))
    setAttempt((value) => value + 1)
  }, [])

  const setData = useCallback((updater) => {
    setState((current) => ({ ...current, data: typeof updater === 'function' ? updater(current.data) : updater }))
  }, [])

  return { ...state, reload, setData }
}
