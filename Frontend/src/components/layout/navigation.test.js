import assert from 'node:assert/strict'
import { test } from 'node:test'
import { APP_NAV, buildCrumbs, NAV_GROUPS } from './navigation.js'

const labels = (crumbs) => crumbs.map((crumb) => crumb.label)

test('top-level sections have a single, current-page crumb', () => {
  assert.deepEqual(buildCrumbs('/dashboard'), [{ label: 'Home' }])
  assert.deepEqual(buildCrumbs('/phone-numbers'), [{ label: 'Phone Numbers' }])
  assert.deepEqual(buildCrumbs('/voices'), [{ label: 'Voices' }])
})

test('agent pages link back to their parents and use the agent name instead of the id', () => {
  assert.deepEqual(buildCrumbs('/agents/abc', 'Reception'), [{ label: 'Agents', to: '/agents' }, { label: 'Reception' }])
  assert.deepEqual(buildCrumbs('/agents/abc/talk', 'Reception'), [
    { label: 'Agents', to: '/agents' },
    { label: 'Reception', to: '/agents/abc' },
    { label: 'Voice test' },
  ])
  assert.deepEqual(labels(buildCrumbs('/agents/abc')), ['Agents', 'Agent'])
  assert.deepEqual(labels(buildCrumbs('/agents/new')), ['Agents', 'New agent'])
})

test('settings pages are nested under settings', () => {
  assert.deepEqual(buildCrumbs('/settings/profile'), [{ label: 'Settings', to: '/settings' }, { label: 'Profile' }])
  assert.deepEqual(labels(buildCrumbs('/settings/security')), ['Settings', 'Security'])
})

test('the sidebar has the Main, Configure, Monitor and Deploy groups with every requested item', () => {
  assert.deepEqual(NAV_GROUPS.map((group) => group.label), [null, 'Configure', 'Monitor', 'Deploy'])
  const labelsOf = (id) => NAV_GROUPS.find((group) => group.id === id).items.map((item) => item.label)
  assert.deepEqual(labelsOf('main'), ['Home', 'Agents', 'Playground'])
  assert.deepEqual(labelsOf('configure'), ['Knowledge Base', 'Tools', 'Workflows', 'Integrations', 'Voices'])
  assert.deepEqual(labelsOf('monitor'), ['Conversations', 'Users', 'Tests', 'Analytics'])
  assert.deepEqual(labelsOf('deploy'), ['Phone Numbers', 'Deployment'])
  assert.deepEqual(APP_NAV.slice(-2).map((item) => item.label), ['Settings', 'Help'])
})

test('every navigation target has a breadcrumb label (so no page shows a generic title)', () => {
  for (const item of APP_NAV) assert.equal(buildCrumbs(item.to).at(-1).label, item.label, item.to)
})

test('every navigation path is unique', () => {
  assert.equal(new Set(APP_NAV.map((item) => item.to)).size, APP_NAV.length)
})
