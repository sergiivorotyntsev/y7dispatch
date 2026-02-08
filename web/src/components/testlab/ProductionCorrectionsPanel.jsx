import { useState, useEffect } from 'react'
import api from '../../api'

/**
 * Production Corrections Panel
 *
 * Shows corrections from production workflow (Review & Posting)
 * that can be applied to training. This is the second training channel
 * (primary channel is Test Lab).
 */
export default function ProductionCorrectionsPanel() {
  const [corrections, setCorrections] = useState([])
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [stats, setStats] = useState({ total: 0, applied_count: 0, pending_count: 0 })

  useEffect(() => {
    loadCorrections()
  }, [])

  async function loadCorrections() {
    setLoading(true)
    try {
      const result = await api.listProductionCorrections({ limit: 50 })
      setCorrections(result.items || [])
      setStats({
        total: result.total || 0,
        applied_count: result.applied_count || 0,
        pending_count: result.pending_count || 0,
      })
    } catch (err) {
      console.error('Failed to load production corrections:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleApplyAll() {
    if (!confirm('Apply all pending production corrections to training?')) return
    setApplying(true)
    try {
      await api.applyProductionCorrectionsToTraining(null, true)
      loadCorrections()
    } catch (err) {
      console.error('Failed to apply corrections:', err)
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <div>
          <h2 className="font-semibold">Production Corrections</h2>
          <p className="text-xs text-gray-500 mt-1">
            Corrections from production Review & Posting (second training channel)
          </p>
        </div>
        {stats.pending_count > 0 && (
          <button
            onClick={handleApplyAll}
            disabled={applying}
            className="btn btn-sm btn-primary"
          >
            {applying ? 'Applying...' : `Apply ${stats.pending_count} Pending`}
          </button>
        )}
      </div>
      <div className="card-body">
        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div className="bg-gray-50 rounded p-3 text-center">
            <div className="text-2xl font-bold text-gray-900">{stats.total}</div>
            <div className="text-xs text-gray-600">Total</div>
          </div>
          <div className="bg-green-50 rounded p-3 text-center">
            <div className="text-2xl font-bold text-green-700">{stats.applied_count}</div>
            <div className="text-xs text-green-600">Applied</div>
          </div>
          <div className="bg-yellow-50 rounded p-3 text-center">
            <div className="text-2xl font-bold text-yellow-700">{stats.pending_count}</div>
            <div className="text-xs text-yellow-600">Pending</div>
          </div>
        </div>

        {/* Recent Corrections List */}
        {loading ? (
          <div className="text-center py-4 text-gray-500">Loading...</div>
        ) : corrections.length === 0 ? (
          <div className="text-center py-4 text-gray-500">
            No production corrections yet.
            <br />
            <span className="text-xs">
              Corrections from Review & Posting will appear here.
            </span>
          </div>
        ) : (
          <div className="space-y-2 max-h-60 overflow-auto">
            {corrections.slice(0, 10).map((corr) => (
              <div
                key={corr.id}
                className={`p-3 rounded text-sm ${
                  corr.applied_to_training ? 'bg-green-50' : 'bg-yellow-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">{corr.field_key}</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    corr.auction_type_code === 'COPART' ? 'bg-blue-100 text-blue-800' :
                    corr.auction_type_code === 'IAA' ? 'bg-purple-100 text-purple-800' :
                    corr.auction_type_code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {corr.auction_type_code}
                  </span>
                </div>
                <div className="mt-1 text-xs">
                  {corr.old_value && (
                    <span className="text-gray-500 line-through mr-2">{corr.old_value}</span>
                  )}
                  <span className="text-gray-900">→ {corr.new_value}</span>
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  {corr.created_at ? new Date(corr.created_at).toLocaleString() : ''}
                  {corr.applied_to_training && (
                    <span className="ml-2 text-green-600">✓ Applied</span>
                  )}
                </div>
              </div>
            ))}
            {corrections.length > 10 && (
              <div className="text-center text-xs text-gray-500 py-2">
                ...and {corrections.length - 10} more
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
