import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './index.css'
import { useAuth } from './hooks/useAuth'
import NavBar from './components/NavBar'
import { InstallPrompt } from './components/InstallPrompt'
import Home from './routes/Home'

const Categories = lazy(() => import('./routes/Categories'))
const Budgets = lazy(() => import('./routes/Budgets'))
const Transactions = lazy(() => import('./routes/Transactions'))
const ReceiptProcessing = lazy(() => import('./routes/ReceiptProcessing'))
const ReceiptReview = lazy(() => import('./routes/ReceiptReview'))
const Login = lazy(() => import('./routes/Login'))
const QuickenSync = lazy(() => import('./routes/QuickenSync'))
const ImportPage = lazy(() => import('./routes/Import'))
const ExportPage = lazy(() => import('./routes/Export'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Show cached data immediately, refetch in the background.
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
  },
})

function FullscreenSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-gray-500">Loading…</p>
    </div>
  )
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <FullscreenSpinner />
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function LoginGuard({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <FullscreenSpinner />
  if (user) return <Navigate to="/" replace />
  return <>{children}</>
}

function App() {
  return (
    <>
      <NavBar />
      <Suspense fallback={<FullscreenSpinner />}>
        <Routes>
          <Route
            path="/login"
            element={
              <LoginGuard>
                <Login />
              </LoginGuard>
            }
          />
          <Route
            path="/"
            element={
              <AuthGuard>
                <Home />
              </AuthGuard>
            }
          />
          <Route
            path="/categories"
            element={
              <AuthGuard>
                <Categories />
              </AuthGuard>
            }
          />
          <Route
            path="/budgets"
            element={
              <AuthGuard>
                <Budgets />
              </AuthGuard>
            }
          />
          <Route
            path="/transactions"
            element={
              <AuthGuard>
                <Transactions />
              </AuthGuard>
            }
          />
          <Route
            path="/receipts/:id/processing"
            element={
              <AuthGuard>
                <ReceiptProcessing />
              </AuthGuard>
            }
          />
          <Route
            path="/receipts/:id/review"
            element={
              <AuthGuard>
                <ReceiptReview />
              </AuthGuard>
            }
          />
          <Route
            path="/sync"
            element={
              <AuthGuard>
                <QuickenSync />
              </AuthGuard>
            }
          />
          <Route path="/import" element={<Navigate to="/sync" replace />} />
          <Route path="/export" element={<Navigate to="/sync" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      <InstallPrompt />
    </>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
