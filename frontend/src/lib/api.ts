const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

export type Role = 'buyer' | 'seller' | 'admin'

export interface User {
  id: number
  email: string
  role: Role
  created_at: string
}

export interface AuthResponse {
  user: User
  csrf_token: string
}

export interface Health {
  status: string
  service: string
  env: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/*
 * The CSRF token lives in memory only. On reload it is re-fetched from
 * /auth/me, which is the only endpoint that echoes it back.
 */
let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...options.headers,
  }

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  if (method !== 'GET' && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  if (!response.ok) {
    let message = `Request failed with ${response.status}`
    try {
      const data: unknown = await response.json()
      const detail = (data as { detail?: unknown }).detail
      if (typeof detail === 'string') {
        message = detail
      } else if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { msg?: unknown }
        if (typeof first.msg === 'string') message = first.msg
      }
    } catch {
      // Non-JSON error body: keep the status-based message.
    }
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export function getHealth(): Promise<Health> {
  return request<Health>('/health')
}

export function register(input: {
  email: string
  password: string
  role: 'buyer' | 'seller'
}): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/register', {
    method: 'POST',
    body: input,
  })
}

export function login(input: {
  email: string
  password: string
}): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/login', {
    method: 'POST',
    body: input,
  })
}

export function logout(): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' })
}

export function getMe(): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/me')
}

/* ------------------------------------------------------------------ */
/* Auctions                                                            */
/* ------------------------------------------------------------------ */

export type AuctionStatus =
  | 'draft'
  | 'open'
  | 'closed'
  | 'awarded'
  | 'cancelled'

export interface Auction {
  id: number
  buyer_id: number
  buyer_email: string
  title: string
  description: string
  /** Integer minor units (paise). */
  starting_price: number
  /** Integer minor units (paise). */
  min_decrement: number
  currency: string
  starts_at: string
  ends_at: string
  status: AuctionStatus
  winning_bid_id: number | null
  created_at: string
  bid_count: number
  lowest_bid: number | null
}

export interface AuctionInput {
  title: string
  description: string
  /** Integer minor units (paise). */
  starting_price: number
  /** Integer minor units (paise). */
  min_decrement: number
  duration_hours: number
}

export function listAuctions(): Promise<Auction[]> {
  return request<Auction[]>('/auctions')
}

export function listMyAuctions(): Promise<Auction[]> {
  return request<Auction[]>('/auctions/mine')
}

export function getAuction(id: number): Promise<Auction> {
  return request<Auction>(`/auctions/${id}`)
}

export function createAuction(input: AuctionInput): Promise<Auction> {
  return request<Auction>('/auctions', { method: 'POST', body: input })
}

export function closeAuction(id: number): Promise<Auction> {
  return request<Auction>(`/auctions/${id}/close`, { method: 'POST' })
}

export function cancelAuction(id: number): Promise<Auction> {
  return request<Auction>(`/auctions/${id}/cancel`, { method: 'POST' })
}

/* ------------------------------------------------------------------ */
/* Signed bid ledger                                                   */
/* ------------------------------------------------------------------ */

export interface Bid {
  id: number
  auction_id: number
  seller_id: number
  seller_email: string
  /** Integer minor units (paise). */
  amount: number
  nonce: string
  prev_hash: string | null
  signature: string
  created_at: string
}

export interface ChainVerification {
  auction_id: number
  bid_count: number
  checked: number
  valid: boolean
  first_invalid_bid_id: number | null
  reason: string | null
}

export function listBids(auctionId: number): Promise<Bid[]> {
  return request<Bid[]>(`/auctions/${auctionId}/bids`)
}

export function placeBid(
  auctionId: number,
  input: { amount: number; idempotency_key: string },
): Promise<Bid> {
  return request<Bid>(`/auctions/${auctionId}/bids`, {
    method: 'POST',
    body: input,
  })
}

export function verifyAuction(auctionId: number): Promise<ChainVerification> {
  return request<ChainVerification>(`/auctions/${auctionId}/verify`)
}