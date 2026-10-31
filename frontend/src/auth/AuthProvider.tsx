import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  getMe,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  setCsrfToken,
  type AuthResponse,
  type Role,
  type User,
} from '../lib/api'
import { AuthContext } from './context'

function adopt(response: AuthResponse): User {
  setCsrfToken(response.csrf_token)
  return response.user
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true

    getMe()
      .then((response) => {
        if (active) setUser(adopt(response))
      })
      .catch(() => {
        if (active) {
          setCsrfToken(null)
          setUser(null)
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(adopt(await apiLogin({ email, password })))
  }, [])

  const signUp = useCallback(
    async (email: string, password: string, role: Role) => {
      if (role === 'admin') {
        throw new Error('Admin accounts cannot be self-registered.')
      }
      setUser(adopt(await apiRegister({ email, password, role })))
    },
    [],
  )

  const signOut = useCallback(async () => {
    try {
      await apiLogout()
    } finally {
      setCsrfToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut }),
    [user, loading, signIn, signUp, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}