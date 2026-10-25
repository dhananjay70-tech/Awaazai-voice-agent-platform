import { MessagesSquare } from 'lucide-react'
import Button from '../components/ui/Button.jsx'
import { ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState } from '../components/ui/States.jsx'

export default function ConversationsPage() {
  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Conversations</h2>
          <p>Past conversations with your agents: transcripts, duration and outcome.</p>
        </div>
      </div>

      <ComingSoonNotice title="Conversation history is not recorded yet">
        Nothing stores a conversation after it ends: the backend has no conversation tables or endpoints, and the voice service keeps a session only in memory while it is open. No conversation, transcript, duration
        or recording is shown here because none exists.
      </ComingSoonNotice>

      <EmptyState
        icon={MessagesSquare}
        title="No conversations"
        actions={
          <Button to="/playground" variant="primary">
            Try the playground
          </Button>
        }
      >
        Conversations you hold in the playground appear on screen while the session is open, but they are not saved. Saving them needs a conversation-history service.
      </EmptyState>

      <section className="card" aria-labelledby="conv-needs">
        <h3 className="section-title" id="conv-needs" style={{ marginBottom: 'var(--space-4)' }}>
          What this page needs
        </h3>
        <ol className="steps">
          <li>Backend tables and endpoints for conversations and their messages, owned by the signed-in user.</li>
          <li>The voice service reporting each finished turn to the backend.</li>
          <li>Audio recording storage, only if recordings are wanted (playback needs a real audio URL).</li>
        </ol>
      </section>
    </div>
  )
}
