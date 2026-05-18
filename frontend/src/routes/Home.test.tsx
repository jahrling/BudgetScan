import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import Home from './Home'

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Home', () => {
  it('renders the heading', () => {
    renderWithProviders()
    expect(screen.getByText('Finance')).toBeInTheDocument()
  })
})
