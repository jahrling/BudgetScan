import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi, ApiError } from '../lib/api'
import type { UserRead } from '../lib/api'

const USER_KEY = ['auth', 'me'] as const

export function useAuth() {
  const qc = useQueryClient()

  const { data: user, isLoading, error } = useQuery<UserRead | null>({
    queryKey: USER_KEY,
    queryFn: async () => {
      try {
        return await authApi.me()
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 1000 * 60 * 5,
    refetchOnWindowFocus: true,
  })

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authApi.login(username, password),
    onSuccess: (data) => qc.setQueryData(USER_KEY, data),
  })

  const setupMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authApi.setup(username, password),
    onSuccess: (data) => qc.setQueryData(USER_KEY, data),
  })

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => qc.setQueryData(USER_KEY, null),
  })

  return {
    user: user ?? null,
    isLoading,
    error,
    login: loginMutation.mutateAsync,
    setup: setupMutation.mutateAsync,
    logout: logoutMutation.mutateAsync,
    loginError: loginMutation.error,
    setupError: setupMutation.error,
  }
}
