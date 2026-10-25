import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RedirectIfAuthenticated, RequireAuth } from '../auth/RouteGuards.jsx'
import AppShell from '../components/layout/AppShell.jsx'
import PublicLayout from '../components/layout/PublicLayout.jsx'
import AgentStudio from '../pages/agent/AgentStudio.jsx'
import AgentsPage from '../pages/AgentsPage.jsx'
import AgentTalkPage from '../pages/AgentTalkPage.jsx'
import AnalyticsPage from '../pages/AnalyticsPage.jsx'
import ConversationsPage from '../pages/ConversationsPage.jsx'
import DashboardPage from '../pages/DashboardPage.jsx'
import DeploymentPage from '../pages/DeploymentPage.jsx'
import HelpPage from '../pages/HelpPage.jsx'
import IntegrationsPage from '../pages/IntegrationsPage.jsx'
import KnowledgePage from '../pages/KnowledgePage.jsx'
import LandingPage from '../pages/LandingPage.jsx'
import LoginPage from '../pages/LoginPage.jsx'
import NewAgentPage from '../pages/NewAgentPage.jsx'
import NotFoundPage from '../pages/NotFoundPage.jsx'
import PhoneNumbersPage from '../pages/PhoneNumbersPage.jsx'
import PlaygroundPage from '../pages/PlaygroundPage.jsx'
import RegisterPage from '../pages/RegisterPage.jsx'
import { AccountPage, PreferencesPage, ProfilePage, SecurityPage, SettingsLayout } from '../pages/SettingsPage.jsx'
import TestsPage from '../pages/TestsPage.jsx'
import ToolsPage from '../pages/ToolsPage.jsx'
import UsersPage from '../pages/UsersPage.jsx'
import VoicesPage from '../pages/VoicesPage.jsx'
import VoiceTestPage from '../pages/VoiceTestPage.jsx'
import WorkflowsPage from '../pages/WorkflowsPage.jsx'
import RouteError from './RouteError.jsx'
import StudioTabRedirect from './StudioTabRedirect.jsx'

// `handle.showCreate` adds the "Create agent" shortcut to the app header; `handle.wide` lets the page use the full
// width (the studio). Page titles and breadcrumbs come from the URL (see components/layout/navigation.js).
export const routes = [
  {
    errorElement: <RouteError />,
    children: [
      {
        element: <PublicLayout />,
        children: [{ path: '/', element: <LandingPage /> }],
      },
      {
        element: <RedirectIfAuthenticated />,
        children: [
          { path: '/login', element: <LoginPage /> },
          { path: '/register', element: <RegisterPage /> },
        ],
      },
      // The original standalone voice test page: local development only, it refuses non-loopback voice URLs.
      { path: '/voice-test', element: <VoiceTestPage /> },
      {
        element: <RequireAuth />,
        children: [
          {
            element: <AppShell />,
            children: [
              { path: '/dashboard', element: <DashboardPage />, handle: { showCreate: true } },
              { path: '/agents', element: <AgentsPage /> },
              { path: '/agents/new', element: <NewAgentPage /> },
              { path: '/agents/:id', element: <AgentStudio />, handle: { wide: true, hideTitle: true } },
              { path: '/agents/:id/configure', element: <StudioTabRedirect tab="agent" /> },
              { path: '/agents/:id/knowledge', element: <StudioTabRedirect tab="knowledge" /> },
              { path: '/agents/:id/talk', element: <AgentTalkPage /> },
              { path: '/playground', element: <PlaygroundPage /> },
              { path: '/knowledge', element: <KnowledgePage /> },
              { path: '/tools', element: <ToolsPage /> },
              { path: '/workflows', element: <WorkflowsPage /> },
              { path: '/integrations', element: <IntegrationsPage /> },
              { path: '/voices', element: <VoicesPage /> },
              { path: '/conversations', element: <ConversationsPage /> },
              { path: '/users', element: <UsersPage /> },
              { path: '/tests', element: <TestsPage /> },
              { path: '/analytics', element: <AnalyticsPage /> },
              { path: '/phone-numbers', element: <PhoneNumbersPage /> },
              { path: '/deployment', element: <DeploymentPage /> },
              { path: '/help', element: <HelpPage /> },
              {
                path: '/settings',
                element: <SettingsLayout />,
                children: [
                  { index: true, element: <Navigate to="/settings/profile" replace /> },
                  { path: 'profile', element: <ProfilePage /> },
                  { path: 'account', element: <AccountPage /> },
                  { path: 'preferences', element: <PreferencesPage /> },
                  { path: 'security', element: <SecurityPage /> },
                ],
              },
            ],
          },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
