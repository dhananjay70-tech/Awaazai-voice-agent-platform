import { FlaskConical, Plus } from 'lucide-react'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState } from '../components/ui/States.jsx'

const TEST_PARTS = [
  ['Scenario', 'A short conversation to start, such as a caller asking to move an appointment.'],
  ['Expected behaviour', 'What a good answer must contain or avoid.'],
  ['Agent configuration', 'Which version of the agent’s prompt and settings to run it against.'],
  ['Result', 'Pass or fail, with the reasons, once a run has actually happened.'],
]

export default function TestsPage() {
  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Tests</h2>
          <p>Check that an agent behaves as expected after you change its prompt.</p>
        </div>
        <ComingSoonButton icon={Plus}>Create test</ComingSoonButton>
      </div>

      <ComingSoonNotice title="Automated tests are not available yet">
        There is no evaluation service, so tests cannot be created or run, and no pass or fail result is shown. For now, try an agent by hand in the playground.
      </ComingSoonNotice>

      <section className="card page-stack" aria-labelledby="test-list" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="test-list">
          Test cases
        </h3>
        <EmptyState icon={FlaskConical} title="No tests">
          Test cases and their latest results will be listed here.
        </EmptyState>
      </section>

      <section className="card" aria-labelledby="test-parts">
        <h3 className="section-title" id="test-parts" style={{ marginBottom: 'var(--space-4)' }}>
          What a test will contain
        </h3>
        <dl className="meta-list">
          {TEST_PARTS.map(([term, text]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  )
}
