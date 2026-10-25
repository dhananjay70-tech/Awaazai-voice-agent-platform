import { Check, Copy, EllipsisVertical, Mic, PanelRightClose, PanelRightOpen, Save, Trash2 } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../api/index.js'
import { ApiError, fieldErrorsFrom } from '../../api/client.js'
import AgentLoader from '../../components/agents/AgentLoader.jsx'
import { AgentStatusBadge } from '../../components/agents/AgentCard.jsx'
import AgentTab from '../../components/studio/AgentTab.jsx'
import { AdvancedTab, AnalysisTab, KnowledgeTab, SecurityTab, TestsTab, ToolsTab, WidgetTab, WorkflowTab } from '../../components/studio/StudioTabs.jsx'
import Alert, { ErrorAlert } from '../../components/ui/Alert.jsx'
import Button from '../../components/ui/Button.jsx'
import ConfirmDialog from '../../components/ui/ConfirmDialog.jsx'
import DropdownMenu from '../../components/ui/DropdownMenu.jsx'
import { useToast } from '../../components/ui/ToastContext.js'
import VoiceTestPanel from '../../components/voice/VoiceTestPanel.jsx'
import { useAgentFormState } from '../../hooks/useAgentForm.js'
import { useUnsavedChangesGuard } from '../../hooks/useUnsavedChangesGuard.jsx'
import { agentToForm, backendFieldsToForm, changedFields, FIELD_TAB, fieldLabels, formToPatch, isDirty, unsavedKeys, validateAgentForm } from '../../utils/agentForm.js'
import { languageLabel, voiceLanguageFor } from '../../utils/languages.js'
import { clearStudioDraft, loadStudioDraft, saveStudioDraft } from '../../utils/studioDraft.js'

const STUDIO_TABS = [
  { id: 'agent', label: 'Agent' },
  { id: 'workflow', label: 'Workflow' },
  { id: 'knowledge', label: 'Knowledge Base' },
  { id: 'analysis', label: 'Analysis' },
  { id: 'tools', label: 'Tools' },
  { id: 'tests', label: 'Tests' },
  { id: 'widget', label: 'Widget' },
  { id: 'security', label: 'Security' },
  { id: 'advanced', label: 'Advanced' },
]

function wideScreen() {
  return typeof window.matchMedia === 'function' ? window.matchMedia('(min-width: 1100px)').matches : true
}

function Studio({ agent, setAgent }) {
  const navigate = useNavigate()
  const toast = useToast()
  const tabsId = useId()
  const panelRef = useRef(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get('tab')
  const tab = STUDIO_TABS.some((item) => item.id === requested) ? requested : 'agent'

  const [baseline, setBaseline] = useState(() => agentToForm(agent))
  const { form, setForm, errors, setErrors, set, setField } = useAgentFormState(baseline)
  const [phase, setPhase] = useState('idle') // idle | saving | verifying
  const [confirmed, setConfirmed] = useState(false) // true only once the server has stored what we sent AND returned it on a fresh read
  const [conflict, setConflict] = useState(null) // { latest, fields }: the agent was changed on the server after we loaded it
  const [notStored, setNotStored] = useState(null) // fields the server answered OK for but did not actually keep
  const [draft, setDraft] = useState(() => {
    // Edits kept from a session that expired mid-save: offered back, but only if they still differ from the agent.
    const kept = loadStudioDraft(agent.id)
    const base = agentToForm(agent)
    return kept && isDirty({ ...base, ...kept.form }, base) ? kept : null
  })
  const [saveError, setSaveError] = useState(null)
  const [panelOpen, setPanelOpen] = useState(wideScreen)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)
  const inFlight = useRef(false)

  const dirty = isDirty(form, baseline)
  const { dialog, allowLeave } = useUnsavedChangesGuard(dirty)

  function openTab(id) {
    const next = new URLSearchParams(searchParams)
    if (id === 'agent') next.delete('tab')
    else next.set('tab', id)
    setSearchParams(next, { replace: true })
  }

  function showErrors(found) {
    setErrors(found)
    const first = Object.keys(found).find((field) => found[field])
    if (first) openTab(FIELD_TAB[first] ?? 'agent')
  }

  /** Make a server copy the page's truth: displayed agent, saved baseline and (unless keepEdits) the form. */
  function adopt(serverAgent, { keepEdits = false } = {}) {
    const next = agentToForm(serverAgent)
    setAgent(serverAgent)
    setBaseline(next)
    if (!keepEdits) {
      setForm(next)
      setErrors({})
    }
  }

  async function handleSave({ overwrite = false } = {}) {
    if (inFlight.current) return // ignore a second submit while the first is still running
    const found = validateAgentForm(form)
    if (Object.keys(found).length > 0) {
      showErrors(found)
      return
    }
    const patch = formToPatch(form, agent)
    if (Object.keys(patch).length === 0) {
      toast.info('There are no changes to save.')
      return
    }
    inFlight.current = true
    setPhase('saving')
    setSaveError(null)
    setConflict(null)
    setNotStored(null)
    setConfirmed(false)
    try {
      if (!overwrite) {
        // Stale-state guard: if the agent changed on the server since we loaded it (another tab or device), do not
        // silently write over it. Only a real difference in a saved field counts as a conflict.
        const latest = await api.agents.get(agent.id)
        const fields = changedFields(agent, latest)
        if (fields.length > 0) {
          setConflict({ latest, fields })
          return
        }
      }
      await api.agents.update(agent.id, patch)
      setPhase('verifying')
      // Reload the agent and compare, so "saved" means "the database now holds this", not "the request returned".
      const stored = await api.agents.get(agent.id)
      const missing = unsavedKeys(patch, stored)
      if (missing.length === 0) {
        adopt(stored)
        clearStudioDraft(agent.id)
        setDraft(null)
        setConfirmed(true)
        toast.success('Changes saved.')
      } else {
        adopt(stored, { keepEdits: true }) // show what the server really has, keep the user's edits in the form
        setNotStored(fieldLabels(missing))
      }
    } catch (error) {
      setSaveError(error)
      if (error instanceof ApiError) {
        // An expired sign-in sends the user to the login page: keep their edits for this tab so they are not lost.
        if (error.isUnauthorized || error.isNetworkError) saveStudioDraft(agent.id, form)
        const mapped = backendFieldsToForm(fieldErrorsFrom(error))
        if (error.code === 'agent_name_conflict') mapped.name = error.message
        if (Object.keys(mapped).length > 0) showErrors(mapped)
      }
    } finally {
      inFlight.current = false
      setPhase('idle')
    }
  }

  function loadLatest() {
    adopt(conflict.latest)
    setConflict(null)
    toast.info('Loaded the latest version. Your unsaved edits were discarded.')
  }

  function restoreDraft() {
    setForm({ ...baseline, ...draft.form })
    clearStudioDraft(agent.id)
    setDraft(null)
  }

  function discardDraft() {
    clearStudioDraft(agent.id)
    setDraft(null)
  }

  async function deleteAgent() {
    setDeleting(true)
    setDeleteError(null)
    try {
      await api.agents.remove(agent.id)
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        setDeleteError(error instanceof ApiError ? error.message : 'Could not delete the agent.')
        setDeleting(false)
        return
      }
    }
    allowLeave()
    toast.success(`Deleted “${agent.name}”.`)
    navigate('/agents', { replace: true })
  }

  async function copyId() {
    try {
      await navigator.clipboard.writeText(agent.id)
      toast.success('Agent ID copied.')
    } catch {
      toast.error('Could not copy. Select the ID on the Agent tab instead.')
    }
  }

  function openTest() {
    setPanelOpen(true)
    requestAnimationFrame(() => panelRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }))
  }

  function onTabKeyDown(event) {
    const index = STUDIO_TABS.findIndex((item) => item.id === tab)
    const move = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: STUDIO_TABS.length - 1 }[event.key]
    if (move === undefined) return
    event.preventDefault()
    const next = STUDIO_TABS[(move + STUDIO_TABS.length) % STUDIO_TABS.length]
    openTab(next.id)
    document.getElementById(`${tabsId}-tab-${next.id}`)?.focus()
  }

  const voiceLanguage = voiceLanguageFor(agent.language)
  const tabHasError = (id) => Object.keys(errors).some((field) => errors[field] && FIELD_TAB[field] === id)

  return (
    <div className="studio">
      <div className="studio-bar">
        <div className="studio-identity">
          <h2 title={agent.name}>{agent.name}</h2>
          <AgentStatusBadge active={agent.is_active} />
          <span className={`badge ${dirty ? 'badge-warning' : ''}`} title="Publishing is not available: changes apply as soon as they are saved.">
            {dirty ? 'Unsaved changes' : 'Saved'}
          </span>
        </div>
        <div className="studio-actions">
          <span className={`save-status${dirty ? ' is-dirty' : ''}`} role="status" aria-live="polite">
            {phase === 'saving' ? (
              'Saving…'
            ) : phase === 'verifying' ? (
              'Verifying…'
            ) : dirty || !confirmed ? (
              ''
            ) : (
              <>
                <Check size={14} aria-hidden="true" style={{ verticalAlign: '-2px' }} /> All changes saved
              </>
            )}
          </span>
          <Button icon={Mic} onClick={openTest}>
            Test agent
          </Button>
          <Button variant="primary" icon={Save} loading={phase !== 'idle'} disabled={!dirty} onClick={() => handleSave()}>
            Save changes
          </Button>
          <DropdownMenu
            label="More actions"
            trigger={<EllipsisVertical size={18} aria-hidden="true" />}
            items={[
              { label: 'Open full-screen test', icon: Mic, to: `/agents/${agent.id}/talk` },
              { label: 'Copy agent ID', icon: Copy, onSelect: copyId },
              { label: 'Delete agent', icon: Trash2, danger: true, onSelect: () => setConfirmDelete(true) },
            ]}
          />
        </div>
      </div>

      <ErrorAlert error={saveError} title="Could not save your changes" />

      {notStored && (
        <Alert tone="error" title="The server did not store everything you changed">
          It answered, but a fresh read still shows the old value for: {notStored.join(', ')}. Your edits are still in the form. Try saving again, or reload the page to see what is stored.
        </Alert>
      )}

      {conflict && (
        <Alert tone="warning" title="This agent was changed since you opened it">
          It was updated elsewhere ({fieldLabels(conflict.fields).join(', ')}). Nothing was saved. You can load the newer version (your unsaved edits are discarded), or save your edits over it: only the fields you changed are
          sent.
          <span className="alert-actions">
            <Button size="sm" onClick={loadLatest}>
              Load latest version
            </Button>
            <Button size="sm" variant="primary" onClick={() => handleSave({ overwrite: true })}>
              Save my changes anyway
            </Button>
          </span>
        </Alert>
      )}

      {draft && (
        <Alert tone="info" title="You have unsaved edits from before your session ended">
          They were kept in this tab only. Restore them into the form, or discard them.
          <span className="alert-actions">
            <Button size="sm" variant="primary" onClick={restoreDraft}>
              Restore my edits
            </Button>
            <Button size="sm" onClick={discardDraft}>
              Discard
            </Button>
          </span>
        </Alert>
      )}

      <div className="tabs studio-tabs" role="tablist" aria-label="Agent studio" onKeyDown={onTabKeyDown}>
        {STUDIO_TABS.map((item) => (
          <button
            key={item.id}
            id={`${tabsId}-tab-${item.id}`}
            type="button"
            role="tab"
            className="tab"
            aria-selected={tab === item.id}
            aria-controls={`${tabsId}-panel`}
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => openTab(item.id)}
          >
            {item.label}
            {tabHasError(item.id) && (
              <span className="badge badge-error" role="img" aria-label="has errors">
                !
              </span>
            )}
          </button>
        ))}
      </div>

      <div className={`studio-body${panelOpen ? ' has-panel' : ''}`}>
        <div className="studio-main" role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-tab-${tab}`}>
          {tab === 'agent' && <AgentTab agent={agent} form={form} errors={errors} set={set} setField={setField} />}
          {tab === 'workflow' && <WorkflowTab />}
          {tab === 'knowledge' && <KnowledgeTab agent={agent} />}
          {tab === 'analysis' && <AnalysisTab />}
          {tab === 'tools' && <ToolsTab />}
          {tab === 'tests' && <TestsTab />}
          {tab === 'widget' && <WidgetTab agent={agent} />}
          {tab === 'security' && <SecurityTab />}
          {tab === 'advanced' && <AdvancedTab onOpenAgentTab={() => openTab('agent')} />}
        </div>

        <aside className="studio-panel" ref={panelRef} aria-label="Test agent">
          <div className="studio-panel-head">
            <h3>Test agent</h3>
            <button type="button" className="icon-btn" onClick={() => setPanelOpen((open) => !open)} aria-expanded={panelOpen} aria-label={panelOpen ? 'Collapse test panel' : 'Expand test panel'}>
              {panelOpen ? <PanelRightClose size={18} aria-hidden="true" /> : <PanelRightOpen size={18} aria-hidden="true" />}
            </button>
          </div>
          {panelOpen && (
            <>
              {dirty && <p className="field-hint">The test uses the saved agent, not your unsaved edits.</p>}
              <VoiceTestPanel
                compact
                agentName={agent.name}
                languageText={languageLabel(agent.language)}
                voiceLanguage={voiceLanguage}
                unsupportedMessage={`The agent’s language “${agent.language}” has no matching voice mode. Choose English, Hindi or Hinglish and save.`}
              />
            </>
          )}
        </aside>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={`Delete “${agent.name}”?`}
        confirmLabel="Delete agent"
        busy={deleting}
        error={deleteError}
        onConfirm={deleteAgent}
        onCancel={() => setConfirmDelete(false)}
      >
        This permanently removes the agent and its settings. This can’t be undone.
      </ConfirmDialog>
      {dialog}
    </div>
  )
}

/** Route element for /agents/:id: loads the agent, then renders the studio. */
export default function AgentStudio() {
  return <AgentLoader>{(agent, setAgent) => <Studio agent={agent} setAgent={setAgent} />}</AgentLoader>
}
