// Client-side checks that mirror Backend/app/schemas. The server stays the authority; these only give faster feedback.

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
export const MIN_PASSWORD_LENGTH = 8
export const MAX_PASSWORD_LENGTH = 128
export const MAX_PASSWORD_BYTES = 72 // bcrypt limit enforced by the backend
export const MAX_FULL_NAME = 120

function byteLength(value) {
  return new TextEncoder().encode(value).length
}

export function validateEmail(value) {
  const email = value.trim()
  if (!email) return 'Enter your email address.'
  if (!EMAIL_PATTERN.test(email)) return 'Enter a valid email address.'
  return null
}

export function validateLogin({ email, password }) {
  const errors = {}
  const emailError = validateEmail(email)
  if (emailError) errors.email = emailError
  if (!password) errors.password = 'Enter your password.'
  else if (password.length > MAX_PASSWORD_LENGTH) errors.password = 'That password is too long.'
  return errors
}

export function validateRegistration({ fullName, email, password, confirmPassword }) {
  const errors = {}
  if (fullName.trim().length > MAX_FULL_NAME) errors.fullName = `Name must be at most ${MAX_FULL_NAME} characters.`
  const emailError = validateEmail(email)
  if (emailError) errors.email = emailError
  if (!password) errors.password = 'Choose a password.'
  else if (password.length < MIN_PASSWORD_LENGTH) errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`
  else if (password.length > MAX_PASSWORD_LENGTH) errors.password = `Use at most ${MAX_PASSWORD_LENGTH} characters.`
  else if (byteLength(password) > MAX_PASSWORD_BYTES) errors.password = `Password must be at most ${MAX_PASSWORD_BYTES} bytes.`
  if (!confirmPassword) errors.confirmPassword = 'Confirm your password.'
  else if (confirmPassword !== password) errors.confirmPassword = 'Passwords do not match.'
  return errors
}

export const hasErrors = (errors) => Object.keys(errors).length > 0
