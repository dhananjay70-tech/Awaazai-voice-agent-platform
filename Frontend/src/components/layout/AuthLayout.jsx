import { useEffect } from 'react'
import Logo from '../ui/Logo.jsx'

export default function AuthLayout({ title, lede, children, footer, documentTitle }) {
  useEffect(() => {
    document.title = `${documentTitle ?? title} · AwaazAI`
  }, [documentTitle, title])

  return (
    <div className="auth-page">
      <div className="grid-texture" aria-hidden="true" />
      <main className="auth-card">
        <Logo />
        <div>
          <h1>{title}</h1>
          {lede && <p className="lede">{lede}</p>}
        </div>
        {children}
        {footer && <p className="auth-foot">{footer}</p>}
      </main>
    </div>
  )
}
