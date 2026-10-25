import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, fieldErrorsFrom } from '../api/client.js'
import { useAuth } from '../auth/useAuth.js'
import AuthLayout from '../components/layout/AuthLayout.jsx'
import { ErrorAlert } from '../components/ui/Alert.jsx'
import Button from '../components/ui/Button.jsx'
import Field, { PasswordField } from '../components/ui/Field.jsx'
import { hasErrors, MIN_PASSWORD_LENGTH, validateRegistration } from '../utils/validation.js'

export default function RegisterPage() {
  const { register } = useAuth()
  const [values, setValues] = useState({ fullName: '', email: '', password: '', confirmPassword: '' })
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
    if (inFlight.current) return
    const found = validateRegistration(values)
    setErrors(found)
    if (hasErrors(found)) return
    inFlight.current = true
    setSubmitting(true)
    setServerError(null)
    try {
      await register({ fullName: values.fullName.trim(), email: values.email.trim(), password: values.password })
    } catch (error) {
      setServerError(error)
      if (error instanceof ApiError) {
        if (error.status === 422) {
          const fields = fieldErrorsFrom(error)
          setErrors({ email: fields.email, password: fields.password, fullName: fields.full_name })
        } else if (error.code === 'email_already_registered') {
          setErrors({ email: 'An account with this email already exists.' })
        }
      }
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      documentTitle="Create account"
      lede="Start building AI voice agents in minutes."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <ErrorAlert error={serverError} />
        <Field
          label="Full name (optional)"
          name="fullName"
          autoComplete="name"
          value={values.fullName}
          onChange={update('fullName')}
          error={errors.fullName}
          disabled={submitting}
          autoFocus
        />
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
        />
        <PasswordField
          label="Password"
          name="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          value={values.password}
          onChange={update('password')}
          error={errors.password}
          disabled={submitting}
        />
        <PasswordField
          label="Confirm password"
          name="confirmPassword"
          autoComplete="new-password"
          value={values.confirmPassword}
          onChange={update('confirmPassword')}
          error={errors.confirmPassword}
          disabled={submitting}
        />
        <Button type="submit" variant="primary" size="lg" block loading={submitting}>
          {submitting ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
      <p className="auth-note">For your security the session is kept in memory only, so reloading the page signs you out.</p>
    </AuthLayout>
  )
}
