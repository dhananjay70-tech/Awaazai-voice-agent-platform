import { AudioLines } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function Logo({ to = '/', compact = false }) {
  return (
    <Link to={to} className="logo" aria-label="AwaazAI home">
      <span className="logo-mark" aria-hidden="true">
        <AudioLines size={18} strokeWidth={2.5} />
      </span>
      {!compact && (
        <span>
          Awaaz<span className="logo-ai">AI</span>
        </span>
      )}
    </Link>
  )
}
