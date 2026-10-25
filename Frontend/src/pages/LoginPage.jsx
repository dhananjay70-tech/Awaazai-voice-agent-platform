import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, fieldErrorsFrom } from '../api/client.js'
import { useAuth } from '../auth/useAuth.js'
import AuthLayout from '../components/layout/AuthLayout.jsx'
import Alert, { ErrorAlert } from '../components/ui/Alert.jsx'
import Button from '../components/ui/Button.jsx'
import Field, { PasswordField } from '../components/ui/Field.jsx'
import { hasErrors, validateLogin } from '../utils/validation.js'

export default function LoginPage() {
  const { login, notice, clearNotice } = useAuth()
  const [values, setValues] = useState({ email: '', password: '' })
  const [errors, setErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const inFlight = useRef(false)

  const update = (name) => (event) => {
    setValues((current) => ({ ...current, [name]: event.target.value }))
    setErrors((current) => ({ ...current, [name]: undefined }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (inFlight.current) return // a double click or Enter-then-click must not send two requests
    const found = validateLogin(values)
    setErrors(found)
    if (hasErrors(found)) return
    inFlight.current = true
    setSubmitting(true)
    setServerError(null)
    clearNotice()
    try {
      await login({ email: values.email.trim(), password: values.password })
      // The route guard now sees an authenticated session and moves on; nothing else to do here.
    } catch (error) {
      setServerError(error)
      if (error instanceof ApiError && error.status === 422) setErrors(fieldErrorsFrom(error))
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      documentTitle="Sign in"
      lede="Sign in to manage your voice agents."
      footer={
        <>
          New to AwaazAI? <Link to="/register">Create an account</Link>
        </>
      }
    >
      {notice && <Alert tone="warning">{notice}</Alert>}
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <ErrorAlert error={serverError} />
        <Field
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          inputMode="email"
          value={values.email}
          onChange={update('email')}
          error={errors.email}
          disabled={submitting}
          autoFocus
        />
        <PasswordField
          label="Password"
          name="password"
          autoComplete="current-password"
          value={values.password}
          onChange={update('password')}
          error={errors.password}
          disabled={submitting}
        />
        <Button type="submit" variant="primary" size="lg" block loading={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      <p className="auth-note">For your security the session is kept in memory only, so reloading the page signs you out.</p>
    </AuthLayout>
  )
}
