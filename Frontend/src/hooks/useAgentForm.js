import { useState } from 'react'

/** Form state with change handlers that also clear the field's error. */
export function useAgentFormState(initial) {
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState({})

  const set = (name) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: undefined }))
  }
  const setField = (name, value) => {
    setForm((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: undefined }))
  }

  return { form, setForm, errors, setErrors, set, setField }
}
