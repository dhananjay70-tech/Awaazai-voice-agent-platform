// Agent languages are stored as language tags (Backend pattern ^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$).
// The VoiceAgent service speaks three modes (see voice/voiceProtocol.js LANGUAGES): hinglish, hindi, english.
// Only tags with a verified voice mode are offered for new agents.

export const AGENT_LANGUAGES = [
  { value: 'en', label: 'English', voiceLanguage: 'english' },
  { value: 'hi', label: 'Hindi', voiceLanguage: 'hindi' },
  { value: 'hi-Latn', label: 'Hinglish (Hindi in Latin script)', voiceLanguage: 'hinglish' },
]

export const DEFAULT_AGENT_LANGUAGE = 'en'

export function languageLabel(value) {
  return AGENT_LANGUAGES.find((item) => item.value === value)?.label ?? value
}

/** The VoiceAgent mode for an agent language tag, or null when the voice service has no matching mode. */
export function voiceLanguageFor(value) {
  return AGENT_LANGUAGES.find((item) => item.value === value)?.voiceLanguage ?? null
}

/** Options for a language <select>; an existing value that is not in the list is kept so editing never rewrites it. */
export function languageOptions(current) {
  if (current && !AGENT_LANGUAGES.some((item) => item.value === current)) {
    return [...AGENT_LANGUAGES, { value: current, label: `${current} (no voice support)`, voiceLanguage: null }]
  }
  return AGENT_LANGUAGES
}
