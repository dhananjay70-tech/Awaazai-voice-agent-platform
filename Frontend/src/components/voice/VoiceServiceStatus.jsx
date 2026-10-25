import { describeVoiceStatus } from './voiceStatus.js'

export default function VoiceServiceStatus({ resource }) {
  const info = describeVoiceStatus(resource)
  return (
    <span className={`badge ${info.tone}`} role="status">
      <span className="dot" aria-hidden="true" />
      {info.text}
    </span>
  )
}
