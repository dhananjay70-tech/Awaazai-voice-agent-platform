import assert from 'node:assert/strict'
import { test } from 'node:test'
import { hasErrors, validateEmail, validateLogin, validateRegistration } from './validation.js'

test('email must be present and look like an address', () => {
  assert.match(validateEmail(''), /Enter your email/)
  assert.match(validateEmail('nope'), /valid email/)
  assert.equal(validateEmail('  a@b.co '), null)
})

test('login needs an email and a password but does not enforce password rules', () => {
  assert.deepEqual(Object.keys(validateLogin({ email: '', password: '' })).sort(), ['email', 'password'])
  assert.equal(hasErrors(validateLogin({ email: 'a@b.co', password: 'x' })), false)
})

test('registration enforces the backend password length and a matching confirmation', () => {
  const ok = { fullName: 'Ada', email: 'a@b.co', password: 'longenough', confirmPassword: 'longenough' }
  assert.equal(hasErrors(validateRegistration(ok)), false)
  assert.match(validateRegistration({ ...ok, password: 'short', confirmPassword: 'short' }).password, /at least 8/)
  assert.match(validateRegistration({ ...ok, confirmPassword: 'different1' }).confirmPassword, /do not match/)
  assert.match(validateRegistration({ ...ok, confirmPassword: '' }).confirmPassword, /Confirm/)
})

test('passwords over the bcrypt byte limit are rejected even when short in characters', () => {
  const password = 'é'.repeat(40) // 40 characters, 80 bytes
  assert.match(validateRegistration({ fullName: '', email: 'a@b.co', password, confirmPassword: password }).password, /72 bytes/)
})

test('full name is optional but limited to 120 characters', () => {
  const base = { email: 'a@b.co', password: 'longenough', confirmPassword: 'longenough' }
  assert.equal(hasErrors(validateRegistration({ ...base, fullName: '' })), false)
  assert.ok(validateRegistration({ ...base, fullName: 'x'.repeat(121) }).fullName)
})
