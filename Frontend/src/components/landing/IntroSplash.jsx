import { useEffect, useRef, useState } from 'react'

/**
 * Full-screen intro video shown when the site is first opened in a tab. The page underneath is already rendered; when the
 * clip ends (or the visitor presses Skip) the overlay fades away. It is skipped for reduced motion, when the video
 * cannot play, and on later visits within the same tab session.
 */
const INTRO_VIDEO = '/videos/intro.mp4' // first 10 s of video/12779446_3840_2160_24fps.mp4, 720p
const SEEN_KEY = 'awaazai-intro-seen'

function shouldPlay() {
  if (import.meta.env.MODE === 'test') return false
  try {
    if (window.sessionStorage.getItem(SEEN_KEY)) return false
  } catch {
    // storage blocked: just play it
  }
  return !(typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches)
}

export default function IntroSplash() {
  const [phase, setPhase] = useState(() => (shouldPlay() ? 'playing' : 'done')) // playing | leaving | done
  const skipRef = useRef(null)

  const finish = () => {
    try {
      window.sessionStorage.setItem(SEEN_KEY, '1')
    } catch {
      // ignore
    }
    setPhase((current) => (current === 'playing' ? 'leaving' : current))
  }

  useEffect(() => {
    if (phase === 'done') return undefined
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    skipRef.current?.focus()
    return () => {
      document.body.style.overflow = previous
    }
  }, [phase])

  useEffect(() => {
    if (phase !== 'leaving') return undefined
    const timer = window.setTimeout(() => setPhase('done'), 700)
    return () => window.clearTimeout(timer)
  }, [phase])

  useEffect(() => {
    if (phase !== 'playing') return undefined
    const onKey = (event) => event.key === 'Escape' && finish()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase])

  if (phase === 'done') return null

  return (
    <div className={`intro${phase === 'leaving' ? ' is-leaving' : ''}`} role="dialog" aria-modal="true" aria-label="AwaazAI intro">
      <video
        className="intro-video"
        autoPlay
        muted
        playsInline
        preload="auto"
        src={INTRO_VIDEO}
        aria-hidden="true"
        onEnded={finish}
        onError={finish}
      />
      <div className="intro-shade" aria-hidden="true" />
      <p className="intro-brand" aria-hidden="true">
        Awaaz<span>AI</span>
      </p>
      <button ref={skipRef} type="button" className="intro-skip" onClick={finish}>
        Skip intro
      </button>
    </div>
  )
}
