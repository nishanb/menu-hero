import type { ApiErrorBody, ValidationErrorItem } from '~/types/api'

/**
 * Normalised error thrown by the `$api` plugin (and by `toApiError`) for every
 * failed request, so callers never have to inspect raw fetch errors.
 *
 * - `status`  HTTP status of the response, or 0 when no response was received
 *             (network failure, aborted request, ...).
 * - `detail`  Human-readable message: FastAPI's `detail` when present, Nitro's
 *             `message`/`statusMessage` for proxy errors, otherwise a generic text.
 * - `data`    The raw error body, if any, for callers that need more.
 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly data: unknown

  constructor(status: number, detail: string, data?: unknown) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.data = data
  }

  /** True when the request never reached a server (or the proxy could not reach the backend). */
  get isUnreachable(): boolean {
    return this.status === 0 || this.status === 502 || this.status === 503
  }

  /** Message suitable for showing to a user, e.g. "Agent timed out (HTTP 504)". */
  get displayMessage(): string {
    return this.status > 0 ? `${this.detail} (HTTP ${this.status})` : this.detail
  }

  /** Build an ApiError from an HTTP status and the parsed (or unparsed) error body. */
  static fromResponse(status: number, body: unknown): ApiError {
    return new ApiError(status, describeErrorBody(status, body), body)
  }
}

function isValidationItems(value: unknown): value is ValidationErrorItem[] {
  return Array.isArray(value) && value.every(item => typeof item === 'object' && item !== null && 'msg' in item)
}

function hasDetail(body: unknown): body is ApiErrorBody {
  return typeof body === 'object' && body !== null && 'detail' in body
}

/** Turn an error body into a readable sentence. */
export function describeErrorBody(status: number, body: unknown): string {
  if (hasDetail(body)) {
    const { detail } = body
    if (typeof detail === 'string' && detail.trim()) return detail
    if (isValidationItems(detail) && detail.length > 0) {
      return `Invalid request: ${detail.map(item => item.msg).join('; ')}`
    }
  }
  if (status === 502 || status === 503) return 'The backend is unreachable'
  if (status === 504) return 'The backend timed out'
  if (typeof body === 'object' && body !== null) {
    const record = body as Record<string, unknown>
    for (const key of ['message', 'statusMessage', 'error'] as const) {
      const value = record[key]
      if (typeof value === 'string' && value.trim()) return value
    }
  }
  if (typeof body === 'string' && body.trim()) return body.slice(0, 200)
  return status > 0 ? `Request failed with status ${status}` : 'Request failed'
}

interface FetchErrorLike {
  status?: number
  statusCode?: number
  data?: unknown
  response?: { status?: number; _data?: unknown }
  message?: string
}

/**
 * Coerce anything thrown while calling the API into an ApiError.
 * Handles: ApiError (returned as is), ofetch FetchError, plain Error, unknown.
 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (typeof error === 'object' && error !== null) {
    const err = error as FetchErrorLike
    const status = err.response?.status ?? err.status ?? err.statusCode ?? 0
    const body = err.response?._data ?? err.data
    if (status > 0 || body !== undefined) return ApiError.fromResponse(status, body)
    if (err.message) return new ApiError(0, 'Cannot reach the API. Is the server running?', error)
  }
  return new ApiError(0, 'Cannot reach the API. Is the server running?', error)
}
