import { Navigate, useParams } from 'react-router-dom'

/** /agents/:id/configure and /agents/:id/knowledge are views of the studio, not separate editors. */
export default function StudioTabRedirect({ tab }) {
  const { id } = useParams()
  return <Navigate to={tab === 'agent' ? `/agents/${id}` : `/agents/${id}?tab=${tab}`} replace />
}
