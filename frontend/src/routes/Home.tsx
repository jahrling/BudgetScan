import { useQuery } from '@tanstack/react-query'
import { Layout } from '../components/Layout'
import { SnapReceiptButton } from '../components/SnapReceiptButton'

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
    <Layout>
      <div className="text-center pt-8">
        <h1 className="text-4xl font-bold text-gray-900">Finance</h1>
        <p className="mt-4 text-gray-600">
          {isLoading && 'Connecting...'}
          {error && `Backend unavailable: ${error.message}`}
          {data && `Backend status: ${data.status}`}
        </p>
      </div>

      <div className="mt-10 flex justify-center">
        <SnapReceiptButton className="w-full max-w-xs" />
      </div>
    </Layout>
  )
}
