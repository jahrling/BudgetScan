import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { authApi, ApiError } from '../lib/api'

export default function Login() {
  const { login, setup, loginError, setupError } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const { data: setupStatus } = useQuery({
    queryKey: ['auth', 'needs-setup'],
    queryFn: authApi.needsSetup,
  })

  const needsSetup = setupStatus?.needs_setup ?? false

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      if (needsSetup) {
        await setup({ username, password })
      } else {
        await login({ username, password })
      }
    } catch {
      // error is available via loginError / setupError
    } finally {
      setSubmitting(false)
    }
  }

  const mutationError = needsSetup ? setupError : loginError
  const errorMessage =
    mutationError instanceof ApiError
      ? mutationError.status === 401
        ? 'Invalid username or password'
        : mutationError.status === 409
          ? 'Account already exists'
          : 'Something went wrong'
      : mutationError
        ? 'Something went wrong'
        : null

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="w-full max-w-sm rounded-lg bg-white dark:bg-gray-800 p-8 shadow">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
          {needsSetup ? 'Set up your account' : 'Sign in'}
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {needsSetup
            ? 'Create your admin account to get started.'
            : 'Welcome back.'}
        </p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Username
            </label>
            <input
              id="username"
              type="text"
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-gray-900 dark:text-gray-100 shadow-sm focus:border-sky-500 focus:ring-1 focus:ring-sky-500 focus:outline-none"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete={needsSetup ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-gray-900 dark:text-gray-100 shadow-sm focus:border-sky-500 focus:ring-1 focus:ring-sky-500 focus:outline-none"
            />
          </div>

          {errorMessage && (
            <p className="text-sm text-red-600 dark:text-red-400">{errorMessage}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded bg-sky-600 px-4 py-2 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {submitting
              ? 'Please wait...'
              : needsSetup
                ? 'Create account'
                : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
