import { useEffect, useRef, useState } from 'react'
import type { AuctionSocketMessage } from '../lib/api'

export type SocketStatus = 'connecting' | 'open' | 'closed'

export interface AuctionSocketOptions {
  /** Off for anonymous visitors or invalid ids — the page then polls. */
  enabled: boolean
  onMessage: (message: AuctionSocketMessage) => void
}

const HEARTBEAT_MS = 25_000
const BASE_RETRY_MS = 500
const MAX_RETRY_MS = 15_000

/** Derive the absolute ws(s) URL from the page origin (same-origin cookies). */
function socketUrl(auctionId: number): string {
  const configured = import.meta.env.VITE_WS_BASE
  if (typeof configured === 'string' && configured.length > 0) {
    return `${configured.replace(/\/$/, '')}/ws/auctions/${auctionId}`
  }
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/ws/auctions/${auctionId}`
}

/*
 * Live auction feed with automatic reconnect and exponential backoff. The
 * caller keeps a slow poll running as a safety net, so a dropped socket only
 * delays updates rather than losing them. The handler is held in a ref so a
 * re-render never tears down an open connection.
 */
export function useAuctionSocket(
  auctionId: number,
  { enabled, onMessage }: AuctionSocketOptions,
): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>('closed')
  const handlerRef = useRef(onMessage)
  const active = enabled && Number.isInteger(auctionId) && auctionId > 0

  // Keep the latest handler without re-opening the socket on every render.
  useEffect(() => {
    handlerRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!active) return

    let disposed = false
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let heartbeat: number | undefined
    let attempt = 0

    const stopHeartbeat = () => {
      if (heartbeat !== undefined) {
        window.clearInterval(heartbeat)
        heartbeat = undefined
      }
    }

    const connect = () => {
      if (disposed) return
      setStatus('connecting')

      const current = new WebSocket(socketUrl(auctionId))
      socket = current

      current.onopen = () => {
        if (disposed) return
        attempt = 0
        setStatus('open')
        stopHeartbeat()
        heartbeat = window.setInterval(() => {
          if (current.readyState === WebSocket.OPEN) {
            current.send(JSON.stringify({ type: 'ping' }))
          }
        }, HEARTBEAT_MS)
      }

      current.onmessage = (event) => {
        if (disposed) return
        try {
          handlerRef.current(
            JSON.parse(event.data as string) as AuctionSocketMessage,
          )
        } catch {
          // Ignore frames we cannot parse; the next snapshot reconciles state.
        }
      }

      current.onclose = () => {
        stopHeartbeat()
        if (disposed) return
        setStatus('closed')
        const delay = Math.min(BASE_RETRY_MS * 2 ** attempt, MAX_RETRY_MS)
        attempt += 1
        retryTimer = window.setTimeout(connect, delay)
      }

      current.onerror = () => {
        current.close()
      }
    }

    connect()

    return () => {
      disposed = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      stopHeartbeat()
      if (socket) {
        socket.onopen = null
        socket.onmessage = null
        socket.onclose = null
        socket.onerror = null
        socket.close()
      }
    }
  }, [auctionId, active])

  // When disabled (anonymous visitor), report closed and let the page poll.
  return active ? status : 'closed'
}