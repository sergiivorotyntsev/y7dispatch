import { useState, useEffect } from 'react'
import api from '../api'

function Dashboard() {
  const [health, setHealth] = useState(null)
  const [stats, setStats] = useState(null)
  const [recentRuns, setRecentRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadData()
    // Refresh every 30 seconds
    const interval = setInterval(loadData, 30000)
    return () => clearInterval(interval)
  }, [])

  async function loadData() {
    try {
      const [healthData, statsData, runsData] = await Promise.all([
        api.getHealth(),
        api.getExtractionStats(),
        api.listExtractions({ limit: 20 }),
      ])
      setHealth(healthData)
      // Map extraction stats to expected format
      setStats({
        total: statsData.total || 0,
        last_24h: statsData.last_24h || 0,
        by_status: statsData.by_status || {},
        by_auction: statsData.by_auction_type || {},
        needs_review_count: statsData.needs_review_count || 0,
      })
      setRecentRuns(runsData.items || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse">
          <div className="h-8 bg-gray-200 rounded w-1/4 mb-6"></div>
          <div className="grid grid-cols-4 gap-4 mb-6">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-gray-200 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h1>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Integration Status */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Integration Status</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <IntegrationCard
            name="Email"
            status={health?.integrations?.email?.status || 'unknown'}
            details={health?.integrations?.email?.provider || 'Not configured'}
          />
          <IntegrationCard
            name="ClickUp"
            status={health?.integrations?.clickup?.status || 'unknown'}
            details={health?.integrations?.clickup?.list_id ? `List: ${health.integrations.clickup.list_id}` : 'Not configured'}
          />
          <IntegrationCard
            name="Google Sheets"
            status={health?.integrations?.sheets?.status || 'unknown'}
            details={health?.integrations?.sheets?.spreadsheet_id ? 'Connected' : 'Not configured'}
          />
          <IntegrationCard
            name="Central Dispatch"
            status={health?.integrations?.cd?.status || 'unknown'}
            details={health?.integrations?.cd?.marketplace_id || 'Not configured'}
          />
        </div>
      </div>

      {/* Stats Overview */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Statistics</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
          <StatCard label="Total Runs" value={stats?.total || 0} />
          <StatCard label="Last 24h" value={stats?.last_24h || 0} />
          <StatCard label="Needs Review" value={stats?.needs_review_count || stats?.by_status?.needs_review || 0} color="yellow" />
          <StatCard label="Approved" value={(stats?.by_status?.approved || 0) + (stats?.by_status?.reviewed || 0)} color="green" />
          <StatCard label="Failed" value={(stats?.by_status?.failed || 0) + (stats?.by_status?.error || 0)} color="red" />
          <StatCard label="Manual Required" value={stats?.by_status?.manual_required || 0} color="blue" />
        </div>
      </div>

      {/* By Auction */}
      {stats?.by_auction && Object.keys(stats.by_auction).length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-700 mb-4">By Auction Source</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Object.entries(stats.by_auction).map(([auction, count]) => (
              <StatCard key={auction} label={auction} value={count} />
            ))}
          </div>
        </div>
      )}

      {/* Recent Runs */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-700">Recent Runs</h2>
          <a href="/runs" className="text-primary-600 hover:text-primary-700 text-sm">
            View all &rarr;
          </a>
        </div>
        <div className="card overflow-hidden">
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Time</th>
                <th>Extractor</th>
                <th>Auction</th>
                <th>Status</th>
                <th>Score</th>
                <th>Document</th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center text-gray-500 py-8">
                    No runs yet. Upload a PDF in Documents to get started.
                  </td>
                </tr>
              ) : (
                recentRuns.map((run) => (
                  <tr key={run.id}>
                    <td className="font-mono text-xs">{run.id}</td>
                    <td className="text-xs text-gray-500">
                      {run.created_at ? new Date(run.created_at).toLocaleString() : '-'}
                    </td>
                    <td>
                      <span className="badge badge-gray">{run.extractor_kind || 'rule'}</span>
                    </td>
                    <td>
                      {run.auction_type_code ? (
                        <span className="badge badge-info">{run.auction_type_code}</span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td>
                      {run.extraction_score != null ? (
                        <span className={`font-medium ${
                          run.extraction_score >= 0.6 ? 'text-green-600' :
                          run.extraction_score >= 0.3 ? 'text-yellow-600' : 'text-red-600'
                        }`}>
                          {(run.extraction_score * 100).toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td className="text-xs text-gray-500 truncate max-w-[200px]">
                      {run.document_filename || (run.errors && run.errors[0]?.error) || '-'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function IntegrationCard({ name, status, details }) {
  const statusColors = {
    ok: 'bg-green-100 border-green-200',
    configured: 'bg-green-100 border-green-200',
    enabled: 'bg-green-100 border-green-200',
    disabled: 'bg-gray-100 border-gray-200',
    error: 'bg-red-100 border-red-200',
    unknown: 'bg-gray-100 border-gray-200',
  }

  const dotColors = {
    ok: 'bg-green-500',
    configured: 'bg-green-500',
    enabled: 'bg-green-500',
    disabled: 'bg-gray-400',
    error: 'bg-red-500',
    unknown: 'bg-gray-400',
  }

  return (
    <div className={`card p-4 ${statusColors[status] || statusColors.unknown}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-gray-900">{name}</span>
        <span className={`w-3 h-3 rounded-full ${dotColors[status] || dotColors.unknown}`}></span>
      </div>
      <p className="text-sm text-gray-600 truncate">{details}</p>
    </div>
  )
}

function StatCard({ label, value, color = 'blue' }) {
  const colors = {
    blue: 'text-primary-600',
    green: 'text-green-600',
    red: 'text-red-600',
    yellow: 'text-yellow-600',
  }

  return (
    <div className="card p-4">
      <p className="text-sm text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colors[color]}`}>{value}</p>
    </div>
  )
}

function StatusBadge({ status }) {
  const styles = {
    ok: 'badge-success',
    completed: 'badge-success',
    success: 'badge-success',
    approved: 'badge-success',
    reviewed: 'badge-success',
    exported: 'badge-success',
    failed: 'badge-error',
    error: 'badge-error',
    pending: 'badge-warning',
    needs_review: 'badge-warning',
    processing: 'badge-info',
    manual_required: 'badge-info',
  }

  const labels = {
    needs_review: 'Needs Review',
    manual_required: 'Manual Required',
  }

  return (
    <span className={`badge ${styles[status] || 'badge-gray'}`}>
      {labels[status] || status}
    </span>
  )
}

export default Dashboard
