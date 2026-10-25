import { Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth.js'
import Button from '../ui/Button.jsx'
import Logo from '../ui/Logo.jsx'

// Every target is a section on the landing page; nothing links to a page that does not exist.
const NAV_LINKS = [
  { href: '/#product', label: 'Product' },
  { href: '/#solutions', label: 'Solutions' },
  { href: '/#developers', label: 'Developers' },
  { href: '/#pricing', label: 'Pricing' },
  { href: '/#how-it-works', label: 'Resources' },
]

/** Scroll to the #section in the URL after navigation (the router does not do this by itself). */
function useScrollToHash() {
  const { hash, pathname } = useLocation()
  useEffect(() => {
    if (!hash) {
      window.scrollTo({ top: 0 })
      return
    }
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash, pathname])
}

function PublicNav() {
  const { isAuthenticated } = useAuth()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  const close = () => setOpen(false)

  return (
    <header className="site-header">
      <div className="container site-header-inner">
        <Logo />
        <nav className={`site-nav${open ? ' is-open' : ''}`} id="site-nav" aria-label="Primary">
          <ul>
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <Link to={link.href} onClick={close}>
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
          <div className="site-nav-actions">
            {isAuthenticated ? (
              <Button to="/dashboard" variant="primary" onClick={close}>
                Open dashboard
              </Button>
            ) : (
              <>
                <Button to="/login" variant="ghost" onClick={close}>
                  Sign in
                </Button>
                <Button to="/register" variant="primary" onClick={close}>
                  Get Started
                </Button>
              </>
            )}
          </div>
        </nav>
        <button
          type="button"
          className="icon-btn nav-toggle"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="site-nav"
          aria-label={open ? 'Close menu' : 'Open menu'}
        >
          {open ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
        </button>
      </div>
    </header>
  )
}

function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div className="footer-brand">
          <Logo />
          <p>Design, configure, test and manage AI voice agents.</p>
        </div>
        <nav aria-label="Product">
          <h2>Product</h2>
          <ul>
            <li><Link to="/#product">Features</Link></li>
            <li><Link to="/#solutions">Use cases</Link></li>
            <li><Link to="/#how-it-works">How it works</Link></li>
            <li><Link to="/voice-test">Voice demo</Link></li>
          </ul>
        </nav>
        <nav aria-label="Developers">
          <h2>Developers</h2>
          <ul>
            <li><Link to="/#developers">API overview</Link></li>
            <li><Link to="/#pricing">Pricing</Link></li>
          </ul>
        </nav>
        <nav aria-label="Account">
          <h2>Account</h2>
          <ul>
            <li><Link to="/login">Sign in</Link></li>
            <li><Link to="/register">Create account</Link></li>
          </ul>
        </nav>
      </div>
      <div className="container footer-bottom">
        <span>© {new Date().getFullYear()} AwaazAI</span>
        <span>Early development: some capabilities shown on this site are planned, and are labelled as such.</span>
      </div>
    </footer>
  )
}

export default function PublicLayout() {
  useScrollToHash()
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <PublicNav />
      <main id="main-content">
        <Outlet />
      </main>
      <SiteFooter />
    </>
  )
}
