import { Link } from 'react-router-dom'
import Alert from '../components/ui/Alert.jsx'

export default function HelpPage() {
  return (
    <div className="page-stack" style={{ maxWidth: 'var(--width-narrow)' }}>
      <div className="page-intro">
        <div>
          <h2>Help</h2>
          <p>How AwaazAI fits together and what works today.</p>
        </div>
      </div>

      <section className="card page-stack" aria-labelledby="help-start" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="help-start">
          Getting started
        </h3>
        <ol className="steps">
          <li>
            <strong>
              <Link to="/agents/new">Create an agent</Link>
            </strong>
            Pick a template or start blank, and give it a name, language and instructions.
          </li>
          <li>
            <strong>Shape it in the studio</strong>
            Edit the system prompt, the voice settings and the language, then save.
          </li>
          <li>
            <strong>
              <Link to="/playground">Test it</Link>
            </strong>
            Start a session, press Talk (or type) and listen to the reply.
          </li>
        </ol>
      </section>

      <section className="card page-stack" aria-labelledby="help-run" style={{ gap: 'var(--space-3)' }}>
        <h3 className="section-title" id="help-run">
          Running it locally
        </h3>
        <p className="muted">Three services work together. Start each in its own terminal:</p>
        <ul className="feature-list">
          <li>
            <span>
              <strong>Backend</strong> (accounts and agents) on port 8000
            </span>
          </li>
          <li>
            <span>
              <strong>VoiceAgent</strong> (speech and replies) on port 8001
            </span>
          </li>
          <li>
            <span>
              <strong>Frontend</strong> (this app) on port 5173
            </span>
          </li>
        </ul>
        <p className="field-hint">The Backend must have its VoiceAgent address configured for the Home page to show the voice service as reachable.</p>
      </section>

      <Alert tone="info" title="What is not available yet">
        Saved conversations, knowledge sources, tools, workflows, phone numbers, analytics and team management have no backend yet. Their pages say so, and nothing on them is simulated.
      </Alert>

      <Alert tone="warning" title="About voice tests">
        The voice service does not apply an agent’s saved prompt or voice settings yet, and it has no authentication, so tests only work against a service on your own machine. Your sign-in lasts 30 minutes and is lost when you reload the page.
      </Alert>
    </div>
  )
}
