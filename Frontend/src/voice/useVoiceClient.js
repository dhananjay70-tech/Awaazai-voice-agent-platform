import { useCallback, useEffect, useRef, useState } from 'react'
import { createBrowserPlayerFactory } from './playbackQueue.js'
import { VoiceClient } from './voiceClient.js'
import { initialState } from './voiceState.js'

export const BUSY_PHASES = ['requesting-mic', 'connecting', 'listening', 'processing']

/**
 * React glue only: all behaviour lives in VoiceClient. The client is created per URL and always disposed on unmount.
 * `onTurnComplete(state)` (optional) is called once each time a turn reaches `done`, so a screen can keep a transcript.
 */
export function useVoiceClient(url, { onTurnComplete } = {}) {
  const [state, setState] = useState(initialState)
  const clientRef = useRef(null)
  const completeRef = useRef(onTurnComplete)
  useEffect(() => {
    completeRef.current = onTurnComplete // always the latest callback, without recreating the client
  })

  useEffect(() => {
    let lastPhase = initialState.phase
    const client = new VoiceClient({
      url,
      onChange: (next) => {
        setState(next)
        if (next.phase === 'done' && lastPhase !== 'done') completeRef.current?.(next)
        lastPhase = next.phase
      },
      deps: { createPlayer: createBrowserPlayerFactory(new Audio()) },
    })
    clientRef.current = client
    return () => {
      client.dispose() // closes the socket, releases the microphone, stops any sound
      clientRef.current = null
    }
  }, [url])

  const start = useCallback((language) => clientRef.current?.start({ language }), [])
  const stop = useCallback(() => clientRef.current?.stop(), [])
  const cancel = useCallback(() => clientRef.current?.cancel(), [])
  const sendText = useCallback((text, language) => clientRef.current?.sendText(text, { language }), [])
  const newConversation = useCallback(() => clientRef.current?.newConversation(), [])

  const speaking = Object.values(state.segments).some((status) => status === 'playing' || status === 'ready')
  return { state, busy: BUSY_PHASES.includes(state.phase), speaking, start, stop, cancel, sendText, newConversation }
}
