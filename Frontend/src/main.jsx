import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { router } from './app/router.jsx'
import AuthProvider from './auth/AuthProvider.jsx'
import ToastProvider from './components/ui/Toasts.jsx'
import './styles/tokens.css'
import './styles/base.css'
import './styles/ui.css'
import './styles/app.css'
import './styles/landing.css'
import './styles/studio.css'
import './styles/sidebar.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </AuthProvider>
  </StrictMode>,
)
