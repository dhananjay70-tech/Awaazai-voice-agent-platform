import { useEffect, useState } from 'react'

/**
 * The browser's microphone permission: 'granted' | 'denied' | 'prompt' | 'unknown'.
 * 'unknown' means the Permissions API cannot tell (some browsers); the real answer comes when recording starts.
 */
export function useMicrophonePermission() {
  const [permission, setPermission] = useState('unknown')

  useEffect(() => {
    let status = null
    let cancelled = false
    const onChange = () => status && setPermission(status.state)
    navigator.permissions
      ?.query({ name: 'microphone' })
      .then((result) => {
        if (cancelled) return
        status = result
        setPermission(result.state)
        result.addEventListener('change', onChange)
      })
      .catch(() => {}) // unsupported name: stay 'unknown'
    return () => {
      cancelled = true
      status?.removeEventListener('change', onChange)
    }
  }, [])

  return permission
}
