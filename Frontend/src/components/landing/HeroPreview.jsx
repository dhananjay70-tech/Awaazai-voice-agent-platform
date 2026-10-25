import { useEffect, useRef, useState } from 'react'

/**
 * Hero visual: the provided video, large, inside a dark framed stage. The CSS-drawn rings and sound wave are only a
 * fallback, shown instead of the video when the visitor prefers reduced motion or the video fails to load.
 */
const HERO_VIDEO = '/videos/hero-ai.mp4' // copy of video/15432956_1080_1920_30fps.mp4
const BARS = Array.from({ length: 41 }, (_, index) => {
  const centre = 1 - Math.abs(index - 20) / 20
  return { peak: 0.2 + 0.8 * centre * (0.65 + 0.35 * Math.abs(Math.sin(index * 1.7))), delay: -((index * 137) % 1800) }
})

function prefersReducedMotion() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export default function HeroPreview() {
  const videoRef = useRef(null)
  const [reduced, setReduced] = useState(prefersReducedMotion)
  const [videoState, setVideoState] = useState('loading') // loading | ready | failed

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReduced(query.matches)
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  const showVideo = !reduced && videoState !== 'failed'

  return (
    <div
      className="voice-stage"
      role="img"
      aria-label="Abstract animated light trails representing real-time AI voice conversation."
    >
      {!showVideo && (
        <>
          <div className="voice-glow" aria-hidden="true" />
          <div className="voice-rings" aria-hidden="true">
            <i /> <i /> <i />
          </div>
          <div className="voice-wave" aria-hidden="true">
            {BARS.map((bar, index) => (
              <i key={index} style={{ '--peak': bar.peak, animationDelay: `${bar.delay}ms` }} />
            ))}
          </div>
        </>
      )}

      {showVideo && (
        <video
          ref={videoRef}
          className={`voice-video${videoState === 'ready' ? ' is-ready' : ''}`}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          src={HERO_VIDEO}
          aria-hidden="true"
          tabIndex={-1}
          onLoadedData={() => setVideoState('ready')}
          onError={() => setVideoState('failed')}
        />
      )}
      <div className="voice-vignette" aria-hidden="true" />
    </div>
  )
}
