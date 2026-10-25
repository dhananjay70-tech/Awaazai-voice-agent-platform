import { BarChart3 } from 'lucide-react'
import { useState } from 'react'
import Field from '../components/ui/Field.jsx'
import { ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState } from '../components/ui/States.jsx'

const RANGES = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]
const METRICS = ['Conversations', 'Minutes of speech', 'Average response time', 'Completed conversations']

export default function AnalyticsPage() {
  const [range, setRange] = useState('30')
  const rangeLabel = RANGES.find((item) => item.value === range).label.toLowerCase()

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Analytics</h2>
          <p>See how your agents are used once conversations are recorded.</p>
        </div>
        <Field as="select" label="Date range" value={range} onChange={(event) => setRange(event.target.value)}>
          {RANGES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </Field>
      </div>

      <ComingSoonNotice title="Analytics are not available yet">
        The backend does not record conversations or usage, and there is no analytics endpoint, so there are no numbers to show. We don’t display placeholder statistics.
      </ComingSoonNotice>

      <div className="stat-grid">
        {METRICS.map((label) => (
          <div className="card stat" key={label}>
            <span className="stat-label">{label}</span>
            <span className="stat-value" aria-label="No data">
              -
            </span>
            <span className="stat-note">No data source yet</span>
          </div>
        ))}
      </div>

      <EmptyState icon={BarChart3} title={`No data for the ${rangeLabel}`}>
        Charts for conversation volume and usage will appear here once conversation events and analytics endpoints are implemented.
      </EmptyState>
    </div>
  )
}
