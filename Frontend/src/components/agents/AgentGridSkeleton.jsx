import { Skeleton } from '../ui/States.jsx'

export default function AgentGridSkeleton({ count = 3 }) {
  return (
    <div className="agent-grid" aria-busy="true" aria-label="Loading agents">
      {Array.from({ length: count }, (_, index) => (
        <div className="card agent-card" key={index}>
          <Skeleton width="55%" height={20} />
          <Skeleton height={14} />
          <Skeleton width="70%" height={14} />
          <Skeleton width="40%" height={32} style={{ marginTop: 8 }} />
        </div>
      ))}
    </div>
  )
}
