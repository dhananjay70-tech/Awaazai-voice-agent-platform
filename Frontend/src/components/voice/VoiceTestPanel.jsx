import { useVoiceServiceStatus, describeVoiceStatus } from './voiceStatus.js'
import { DEFAULT_VOICE_URL, validateVoiceUrl } from '../../voice/voiceProtocol.js'
import Alert from '../ui/Alert.jsx'
import LivePlayground from './LivePlayground.jsx'

const VOICE_URL = import.meta.env.VITE_VOICE_AGENT_WS_URL || DEFAULT_VOICE_URL

/**
 * Everything around a voice test: the local-only warnings, the backend's view of the voice service, and the live
 * playground. `voiceLanguage` is a VoiceAgent mode ('english' | 'hindi' | 'hinglish') or null when none applies.
 * `compact` is the narrow right-hand studio panel: same facts, shorter wording.
 */
export default function VoiceTestPanel({ agentName, languageText, voiceLanguage, unsupportedMessage, agentNote, compact = false }) {
  const serviceStatus = useVoiceServiceStatus()
  const urlCheck = validateVoiceUrl(VOICE_URL)
  const status = describeVoiceStatus(serviceStatus)
  const canTest = urlCheck.ok && Boolean(voiceLanguage)

  return (
    <div className="page-stack" style={compact ? { gap: 'var(--space-3)' } : undefined}>
      {compact ? (
        <Alert tone="warning" title="Local test: saved settings not applied">
          The voice service ignores this agent’s saved prompt and voice settings, and only runs on your own machine.
        </Alert>
      ) : (
        <Alert tone="warning" title="Local development test: saved agent settings are not applied">
          This page talks directly to the voice service on your own machine, which has no authentication and is not allowed outside localhost. It does not use an agent’s saved instructions or voice settings yet,
          so replies show how voice conversations work, not how a specific agent would answer.
        </Alert>
      )}
      {agentNote}
      {!urlCheck.ok && (
        <Alert tone="error" title="Voice connection disabled">
          {urlCheck.reason}
        </Alert>
      )}
      {urlCheck.ok && !voiceLanguage && (
        <Alert tone="error" title="This language isn’t supported by the voice service">
          {unsupportedMessage}
        </Alert>
      )}
      {canTest && !status.ok && !serviceStatus.loading && (
        <Alert tone="warning" title="The backend can’t reach the voice service" meta={compact ? undefined : 'You can still try: connecting reports a clear error if it isn’t running.'}>
          {status.detail ?? 'Start the VoiceAgent service on port 8001.'}
        </Alert>
      )}
      {canTest && (
        <LivePlayground key={voiceLanguage} url={urlCheck.url} voiceLanguage={voiceLanguage} agentName={agentName} languageText={languageText} compact={compact} />
      )}
    </div>
  )
}
