import { useQuery } from '@tanstack/react-query'

async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export default function Home() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
  })

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900">Finance</h1>
        <p className="mt-4 text-gray-600">
          {isLoading && 'Connecting...'}
          {error && `Backend unavailable: ${error.message}`}
          {data && `Backend status: ${data.status}`}
        </p>
      </div>
    </div>
  )
}
