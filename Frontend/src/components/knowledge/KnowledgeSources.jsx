import { FileText, Globe, Library } from 'lucide-react'
import { ComingSoonButton, ComingSoonNotice } from '../ui/ComingSoon.jsx'
import { EmptyState } from '../ui/States.jsx'

/**
 * Source overview for knowledge. No ingestion API exists, so this shows the structure a real implementation will fill
 * (source types, status, agent association) and nothing that pretends to have been uploaded or indexed.
 */
export default function KnowledgeSources({ agentName }) {
  return (
    <div className="page-stack">
      <ComingSoonNotice title="Knowledge ingestion is not connected yet">
        There is no service for uploading, indexing or searching documents in this version, so nothing can be added{agentName ? ` to “${agentName}”` : ''} and no sources are attached.
      </ComingSoonNotice>

      <div className="source-grid">
        <section className="card source-card" aria-labelledby="src-docs">
          <span className="state-icon">
            <FileText size={22} aria-hidden="true" />
          </span>
          <h3 id="src-docs">Documents</h3>
          <p>PDFs, text files and spreadsheets such as FAQs, policies and price lists.</p>
          <ComingSoonButton icon={FileText}>Upload documents</ComingSoonButton>
        </section>
        <section className="card source-card" aria-labelledby="src-web">
          <span className="state-icon">
            <Globe size={22} aria-hidden="true" />
          </span>
          <h3 id="src-web">Websites</h3>
          <p>Pages from your site, crawled and kept up to date.</p>
          <ComingSoonButton icon={Globe}>Add website</ComingSoonButton>
        </section>
      </div>

      <section className="card page-stack" aria-labelledby="src-list" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="src-list">
          Sources{agentName ? ` for ${agentName}` : ''}
        </h3>
        <EmptyState icon={Library} title="No knowledge sources">
          When ingestion is available, each source will show here with its status (queued, processing, ready or failed).
        </EmptyState>
      </section>
    </div>
  )
}
