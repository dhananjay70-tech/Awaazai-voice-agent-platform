import {
  BarChart3,
  BookOpen,
  Bot,
  CircleHelp,
  FlaskConical,
  LayoutDashboard,
  MessagesSquare,
  Mic,
  Phone,
  Plug,
  Rocket,
  Settings,
  Users,
  Volume2,
  Wrench,
  Workflow,
} from 'lucide-react'

// `soon` marks sections whose backend does not exist yet; they open an honest "not available" page, never a fake one.
export const NAV_GROUPS = [
  {
    id: 'main',
    label: null,
    items: [
      { to: '/dashboard', label: 'Home', icon: LayoutDashboard },
      { to: '/agents', label: 'Agents', icon: Bot },
      { to: '/playground', label: 'Playground', icon: Mic },
    ],
  },
  {
    id: 'configure',
    label: 'Configure',
    items: [
      { to: '/knowledge', label: 'Knowledge Base', icon: BookOpen, soon: true },
      { to: '/tools', label: 'Tools', icon: Wrench, soon: true },
      { to: '/workflows', label: 'Workflows', icon: Workflow, soon: true },
      { to: '/integrations', label: 'Integrations', icon: Plug, soon: true },
      { to: '/voices', label: 'Voices', icon: Volume2 },
    ],
  },
  {
    id: 'monitor',
    label: 'Monitor',
    items: [
      { to: '/conversations', label: 'Conversations', icon: MessagesSquare, soon: true },
      { to: '/users', label: 'Users', icon: Users, soon: true },
      { to: '/tests', label: 'Tests', icon: FlaskConical, soon: true },
      { to: '/analytics', label: 'Analytics', icon: BarChart3, soon: true },
    ],
  },
  {
    id: 'deploy',
    label: 'Deploy',
    items: [
      { to: '/phone-numbers', label: 'Phone Numbers', icon: Phone, soon: true },
      { to: '/deployment', label: 'Deployment', icon: Rocket, soon: true },
    ],
  },
]

export const BOTTOM_NAV = [
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/help', label: 'Help', icon: CircleHelp },
]

export const APP_NAV = [...NAV_GROUPS.flatMap((group) => group.items), ...BOTTOM_NAV]

const SECTION_LABELS = {
  dashboard: 'Home',
  agents: 'Agents',
  playground: 'Playground',
  knowledge: 'Knowledge Base',
  tools: 'Tools',
  workflows: 'Workflows',
  integrations: 'Integrations',
  voices: 'Voices',
  conversations: 'Conversations',
  users: 'Users',
  tests: 'Tests',
  analytics: 'Analytics',
  'phone-numbers': 'Phone Numbers',
  deployment: 'Deployment',
  settings: 'Settings',
  help: 'Help',
}

const AGENT_PAGE_LABELS = { talk: 'Voice test' }
const SETTINGS_PAGE_LABELS = { profile: 'Profile', account: 'Account', preferences: 'Preferences', security: 'Security' }

/**
 * Breadcrumb trail for an app path: [{ label, to }]. The last item has no `to` (it is the current page).
 * `agentLabel` is the loaded agent's name, shown in place of its id.
 */
export function buildCrumbs(pathname, agentLabel) {
  const parts = pathname.split('/').filter(Boolean)
  const [section, second, third] = parts
  if (!section || !SECTION_LABELS[section]) return [{ label: 'AwaazAI' }]
  const crumbs = [{ label: SECTION_LABELS[section], to: `/${section}` }]

  if (section === 'agents' && second) {
    if (second === 'new') {
      crumbs.push({ label: 'New agent' })
    } else {
      crumbs.push({ label: agentLabel || 'Agent', to: `/agents/${second}` })
      if (third) crumbs.push({ label: AGENT_PAGE_LABELS[third] ?? third })
    }
  } else if (section === 'settings' && SETTINGS_PAGE_LABELS[second]) {
    crumbs.push({ label: SETTINGS_PAGE_LABELS[second] })
  }

  const last = crumbs.length - 1
  return crumbs.map((crumb, index) => (index === last ? { label: crumb.label } : crumb))
}
