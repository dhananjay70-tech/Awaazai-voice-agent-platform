// Small fetch wrapper for the AwaazAI Backend. Backend errors look like
//   { "error": { "code": "...", "message": "...", "details": ..., "request_id": "..." } }   (details is optional)
// and are normalised into ApiError so screens only ever handle one error shape.

export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/api/v1'

export class ApiError extends Error {
  constructor({ status, code, message, details = null, requestId = null }) {
    super(message)
    this.name = 'ApiError'
    this.status = status // HTTP status, or 0 when no response was received
    this.code = code
    this.details = details
    this.requestId = requestId
  }

  get isUnauthorized() {
    return this.status === 401
  }

  get isNetworkError() {
    return this.status === 0
  }

  /** "Request ID: abc" for support/diagnostics, or null. */
  get diagnostic() {
    return this.requestId ? `Request ID: ${this.requestId}` : null
  }
}

export function isAbortError(error) {
  return error?.name === 'AbortError'
}

const STATUS_MESSAGES = {
  400: 'The request was not valid.',
  401: 'Your session has ended. Please sign in again.',
  403: 'You do not have permission to do that.',
  404: 'We could not find what you were looking for.',
  409: 'That conflicts with something that already exists.',
  422: 'Some of the information was not valid.',
  429: 'Too many requests. Please wait a moment and try again.',
  500: 'Something went wrong on our side. Please try again.',
  502: 'The server is temporarily unavailable. Please try again.',
  503: 'The service is temporarily unavailable. Please try again.',
  504: 'The server took too long to respond. Please try again.',
}

function fallbackMessage(status) {
  return STATUS_MESSAGES[status] ?? (status >= 500 ? STATUS_MESSAGES[500] : 'The request failed.')
}

/** Build an ApiError from a failed response body (already read as text). Never throws. */
export function parseErrorResponse(status, text) {
  let body
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null // not JSON (a proxy error page, for example)
  }
  const error = body && typeof body === 'object' ? body.error : null
  if (error && typeof error === 'object') {
    return new ApiError({
      status,
      code: typeof error.code === 'string' ? error.code : `http_${status}`,
      message: typeof error.message === 'string' && error.message ? error.message : fallbackMessage(status),
      details: error.details ?? null,
      requestId: error.request_id ?? null,
    })
  }
  return new ApiError({ status, code: `http_${status}`, message: fallbackMessage(status) })
}

/**
 * Map a 422 validation error to { fieldName: message } so forms can show messages next to their fields.
 * Backend details: [{ field: "voice_config.speed", message: "..." }].
 */
export function fieldErrorsFrom(error) {
  const result = {}
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return result
  for (const item of error.details) {
    if (item && typeof item.field === 'string' && typeof item.message === 'string' && !(item.field in result)) {
      result[item.field] = item.message
    }
  }
  return result
}

function buildQuery(query) {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

/**
 * createClient({ baseUrl, getToken, onUnauthorized, fetchImpl })
 *   getToken()        -> the in-memory bearer token, or null
 *   onUnauthorized()  -> called when a protected request is answered with 401 (or has no token at all)
 */
export function createClient({ baseUrl, getToken = () => null, onUnauthorized = () => {}, fetchImpl } = {}) {
  const root = String(baseUrl || DEFAULT_API_BASE_URL).replace(/\/+$/, '')

  async function request(path, { method = 'GET', body, query, auth = true, signal } = {}) {
    const headers = { Accept: 'application/json' }
    if (auth) {
      const token = getToken()
      if (!token) {
        onUnauthorized()
        throw new ApiError({ status: 401, code: 'not_authenticated', message: STATUS_MESSAGES[401] })
      }
      headers.Authorization = `Bearer ${token}`
    }
    const init = { method, headers, signal }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }

    const doFetch = fetchImpl ?? globalThis.fetch.bind(globalThis)
    let response
    try {
      response = await doFetch(`${root}${path}${buildQuery(query)}`, init)
    } catch (error) {
      if (isAbortError(error)) throw error
      throw new ApiError({
        status: 0,
        code: 'network_error',
        message: 'Could not reach the server. Check your connection and that the backend is running.',
      })
    }

    let text = ''
    try {
      text = await response.text()
    } catch (error) {
      if (isAbortError(error)) throw error
      // A body that cannot be read is treated like an empty one; the status decides the outcome.
    }

    if (!response.ok) {
      const error = parseErrorResponse(response.status, text)
      if (response.status === 401 && auth) onUnauthorized()
      throw error
    }
    if (!text) return null // 204 and other empty successes
    try {
      return JSON.parse(text)
    } catch {
      throw new ApiError({
        status: response.status,
        code: 'invalid_response',
        message: 'The server sent a response we could not read.',
      })
    }
  }

  return {
    request,
    get: (path, options) => request(path, { ...options, method: 'GET' }),
    post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
    patch: (path, body, options) => request(path, { ...options, method: 'PATCH', body }),
    delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
  }
}
