import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'

function Runs() {
  const [runs, setRuns] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Filters
  const [filters, setFilters] = useState({
    status: '',
    auction_type_id: '',
    source: '', // upload, email, batch, test_lab
    limit: 50,
    offset: 0,
  })

  // Auction types
  const [auctionTypes, setAuctionTypes] = useState([])

  // Selected run for detail view
  const [selectedRun, setSelectedRun] = useState(null)
  const [runLogs, setRunLogs] = useState([])
  const [loadingLogs, setLoadingLogs] = useState(false)

  useEffect(() => {
    loadRuns()
    loadStats()
  }, [filters])

  useEffect(() => {
    loadAuctionTypes()
  }, [])

  async function loadAuctionTypes() {
    try {
      const data = await api.listAuctionTypes()
      setAuctionTypes(data.items || [])
    } catch (err) {
      console.error('Failed to load auction types:', err)
    }
  }

  async function loadRuns() {
    setLoading(true)
    try {
      const params = {}
      if (filters.status) params.status = filters.status
      if (filters.auction_type_id) params.auction_type_id = filters.auction_type_id
      params.limit = filters.limit
      params.offset = filters.offset

      const data = await api.listExtractions(params)
      setRuns(data.items || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function loadStats() {
    try {
      const data = await api.getExtractionStats()
      setStats({
        total: data.total || 0,
        by_status: data.by_status || {},
        by_auction: data.by_auction_type || {},
        needs_review_count: data.needs_review_count || 0,
      })
    } catch (err) {
      console.error('Failed to load stats:', err)
    }
  }

  async function selectRun(run) {
    setSelectedRun(run)
    setLoadingLogs(true)
    try {
      // Get extraction details with review items
      const details = await api.getExtraction(run.id)
      setSelectedRun({
        ...run,
        ...details.run,
        fields: details.fields || [],
        raw_text_preview: details.raw_text_preview,
      })
      // Convert errors to log format
      const logs = (run.errors || []).map((e, i) => ({
        id: i,
        run_id: run.id,
        timestamp: run.created_at,
        level: 'ERROR',
        message: e.error || JSON.stringify(e),
      }))
      setRunLogs(logs)
    } catch (err) {
      console.error('Failed to load run details:', err)
      setRunLogs([])
    } finally {
      setLoadingLogs(false)
    }
  }

  async function handleDeleteRun(runId) {
    if (!confirm('Are you sure you want to delete this run?')) return

    try {
      // Extraction runs don't have a delete endpoint yet, so we just remove from UI
      setRuns(runs.filter(r => r.id !== runId))
      if (selectedRun?.id === runId) {
        setSelectedRun(null)
        setRunLogs([])
      }
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleRerunExtraction(documentId) {
    try {
      const result = await api.runExtraction(documentId)
      alert(`Re-extraction started: Run #${result.id}`)
      loadRuns()
    } catch (err) {
      setError(err.message)
    }
  }

  function exportCsv() {
    const url = api.exportExtractionsCsv(filters)
    window.open(url, '_blank')
  }

  function updateFilter(key, value) {
    setFilters({ ...filters, [key]: value, offset: 0 })
  }

  function nextPage() {
    setFilters({ ...filters, offset: filters.offset + filters.limit })
  }

  function prevPage() {
    setFilters({ ...filters, offset: Math.max(0, filters.offset - filters.limit) })
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Runs & Logs</h1>
        <button onClick={exportCsv} className="btn btn-secondary">
          <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Export CSV
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Filters */}
      <div className="card mb-6">
        <div className="card-body">
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            <div>
              <label className="form-label">Status</label>
              <select
                value={filters.status}
                onChange={e => updateFilter('status', e.target.value)}
                className="form-select"
              >
                <option value="">All</option>
                <option value="needs_review">Needs Review</option>
                <option value="approved">Approved</option>
                <option value="reviewed">Reviewed</option>
                <option value="exported">Exported</option>
                <option value="manual_required">Manual Required</option>
                <option value="failed">Failed</option>
                <option value="pending">Pending</option>
                <option value="processing">Processing</option>
              </select>
            </div>
            <div>
              <label className="form-label">Auction Type</label>
              <select
                value={filters.auction_type_id}
                onChange={e => updateFilter('auction_type_id', e.target.value)}
                className="form-select"
              >
                <option value="">All Types</option>
                {auctionTypes.map(at => (
                  <option key={at.id} value={at.id}>{at.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="form-label">Source</label>
              <select
                value={filters.source}
                onChange={e => updateFilter('source', e.target.value)}
                className="form-select"
              >
                <option value="">All Sources</option>
                <option value="upload">Upload</option>
                <option value="email">Email</option>
                <option value="batch">Batch</option>
                <option value="test_lab">Test Lab</option>
              </select>
            </div>
            <div>
              <label className="form-label">Per Page</label>
              <select
                value={filters.limit}
                onChange={e => updateFilter('limit', parseInt(e.target.value))}
                className="form-select"
              >
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
            <div className="flex items-end">
              <button onClick={loadRuns} className="btn btn-secondary w-full">
                Refresh
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Runs List */}
        <div className="lg:col-span-2">
          <div className="card overflow-hidden">
            {loading ? (
              <div className="p-8 text-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
              </div>
            ) : runs.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                No runs found matching your filters
              </div>
            ) : (
              <>
                <table className="table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Order ID</th>
                      <th>Time</th>
                      <th>Document</th>
                      <th>Auction</th>
                      <th>Status</th>
                      <th>Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map(run => (
                      <tr
                        key={run.id}
                        onClick={() => selectRun(run)}
                        className={`cursor-pointer ${selectedRun?.id === run.id ? 'bg-primary-50' : ''}`}
                      >
                        <td className="font-mono text-xs">{run.id}</td>
                        <td className="font-mono text-xs text-primary-600">
                          {run.outputs_json?.order_id || '-'}
                        </td>
                        <td className="text-xs text-gray-500">
                          {run.created_at ? new Date(run.created_at).toLocaleString() : '-'}
                        </td>
                        <td className="text-xs truncate max-w-[150px]" title={run.document_filename}>
                          {run.document_filename || `Doc #${run.document_id}`}
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
                          ) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Pagination */}
                <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between">
                  <div className="text-sm text-gray-500">
                    Showing {filters.offset + 1} - {filters.offset + runs.length}
                    {stats && ` of ${stats.total}`}
                  </div>
                  <div className="flex space-x-2">
                    <button
                      onClick={prevPage}
                      disabled={filters.offset === 0}
                      className="btn btn-sm btn-secondary disabled:opacity-50"
                    >
                      Previous
                    </button>
                    <button
                      onClick={nextPage}
                      disabled={runs.length < filters.limit}
                      className="btn btn-sm btn-secondary disabled:opacity-50"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Run Details */}
        <div className="lg:col-span-1">
          {selectedRun ? (
            <div className="card">
              <div className="card-header flex items-center justify-between">
                <h3 className="font-medium">Extraction Details</h3>
                <button
                  onClick={() => { setSelectedRun(null); setRunLogs([]); }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="card-body space-y-4">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-gray-500">Run ID</p>
                    <p className="font-mono">{selectedRun.id}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Status</p>
                    <StatusBadge status={selectedRun.status} />
                  </div>
                  <div>
                    <p className="text-gray-500">Extractor</p>
                    <p>{selectedRun.extractor_kind || 'rule'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Auction Type</p>
                    <p>{selectedRun.auction_type_code || '-'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Score</p>
                    <p>{selectedRun.extraction_score != null ? `${(selectedRun.extraction_score * 100).toFixed(1)}%` : '-'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Processing Time</p>
                    <p>{selectedRun.processing_time_ms ? `${selectedRun.processing_time_ms}ms` : '-'}</p>
                  </div>
                </div>

                {selectedRun.document_filename && (
                  <div className="text-sm">
                    <p className="text-gray-500">Document</p>
                    <p className="truncate">{selectedRun.document_filename}</p>
                  </div>
                )}

                {/* Timeline */}
                <div className="border-t border-gray-200 pt-4">
                  <h4 className="font-medium text-sm mb-3">Status Timeline</h4>
                  <RunTimeline status={selectedRun.status} createdAt={selectedRun.created_at} />
                </div>

                {selectedRun.errors && selectedRun.errors.length > 0 && (
                  <div className="text-sm">
                    <p className="text-red-600 font-medium">Errors</p>
                    {selectedRun.errors.map((err, i) => (
                      <p key={i} className="text-red-600">{err.error || JSON.stringify(err)}</p>
                    ))}
                  </div>
                )}

                {/* Action Buttons */}
                <div className="flex space-x-2">
                  {selectedRun.status === 'needs_review' && (
                    <Link
                      to={`/review/${selectedRun.id}`}
                      className="btn btn-sm btn-primary flex-1 text-center"
                    >
                      Review
                    </Link>
                  )}
                  {(selectedRun.status === 'failed' || selectedRun.status === 'manual_required') && selectedRun.document_id && (
                    <button
                      onClick={() => handleRerunExtraction(selectedRun.document_id)}
                      className="btn btn-sm btn-secondary flex-1"
                    >
                      Re-extract
                    </button>
                  )}
                </div>

                {/* Extracted Fields */}
                {selectedRun.fields && selectedRun.fields.length > 0 && (
                  <div className="border-t border-gray-200 pt-4">
                    <h4 className="font-medium text-sm mb-2">Extracted Fields ({selectedRun.fields.length})</h4>
                    <div className="space-y-2 max-h-48 overflow-auto">
                      {selectedRun.fields.map((field, i) => (
                        <div key={i} className="text-xs p-2 rounded bg-gray-50">
                          <div className="flex justify-between">
                            <span className="font-medium text-gray-700">{field.source_key}</span>
                            {field.confidence && (
                              <span className="text-gray-400">{(field.confidence * 100).toFixed(0)}%</span>
                            )}
                          </div>
                          <p className="text-gray-600 truncate">{field.value || '-'}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Logs/Errors */}
                {runLogs.length > 0 && (
                  <div className="border-t border-gray-200 pt-4">
                    <h4 className="font-medium text-sm mb-2">Logs</h4>
                    {loadingLogs ? (
                      <div className="text-center py-4">
                        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600 mx-auto"></div>
                      </div>
                    ) : (
                      <div className="space-y-2 max-h-64 overflow-auto">
                        {runLogs.map(log => (
                          <div key={log.id} className={`text-xs p-2 rounded ${
                            log.level === 'ERROR' ? 'bg-red-50 text-red-700' :
                            log.level === 'WARNING' ? 'bg-yellow-50 text-yellow-700' :
                            'bg-gray-50 text-gray-700'
                          }`}>
                            <div className="flex items-center justify-between">
                              <span className="font-medium">{log.level}</span>
                              <span className="text-gray-400">{log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ''}</span>
                            </div>
                            <p className="mt-1">{log.message}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="card">
              <div className="card-body text-center text-gray-500 py-12">
                <svg className="w-12 h-12 mx-auto text-gray-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                <p>Select a run to view details</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function RunTimeline({ status, createdAt }) {
  // Define the pipeline stages
  const stages = [
    { key: 'received', label: 'Received', icon: '📥' },
    { key: 'classified', label: 'Classified', icon: '🏷️' },
    { key: 'extracted', label: 'Extracted', icon: '📝' },
    { key: 'reviewed', label: 'Reviewed', icon: '✅' },
    { key: 'exported', label: 'Exported', icon: '🚀' },
  ]

  // Determine current stage based on status
  const getStageIndex = (status) => {
    switch (status) {
      case 'pending':
      case 'processing':
        return 0 // received
      case 'needs_review':
        return 2 // extracted (waiting for review)
      case 'reviewed':
      case 'approved':
        return 3 // reviewed
      case 'exported':
        return 4 // exported (complete)
      case 'failed':
      case 'error':
      case 'manual_required':
        return -1 // failed at some point
      default:
        return 1 // classified
    }
  }

  const currentIndex = getStageIndex(status)
  const isFailed = status === 'failed' || status === 'error' || status === 'manual_required'

  return (
    <div className="relative">
      {/* Progress line */}
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200"></div>

      {stages.map((stage, index) => {
        const isCompleted = currentIndex >= index
        const isCurrent = currentIndex === index
        const isFailedStage = isFailed && index === 2 // typically fails at extraction

        return (
          <div key={stage.key} className="relative flex items-start mb-3 last:mb-0">
            {/* Circle indicator */}
            <div className={`relative z-10 flex items-center justify-center w-8 h-8 rounded-full text-sm ${
              isFailedStage ? 'bg-red-100 text-red-600' :
              isCompleted ? 'bg-green-100 text-green-600' :
              'bg-gray-100 text-gray-400'
            }`}>
              {isFailedStage ? '❌' : stage.icon}
            </div>

            {/* Label */}
            <div className="ml-3 flex-1">
              <p className={`text-sm font-medium ${
                isFailedStage ? 'text-red-600' :
                isCompleted ? 'text-gray-900' : 'text-gray-400'
              }`}>
                {stage.label}
              </p>
              {isCurrent && createdAt && (
                <p className="text-xs text-gray-500">
                  {new Date(createdAt).toLocaleString()}
                </p>
              )}
              {isFailedStage && (
                <p className="text-xs text-red-500">
                  {status === 'manual_required' ? 'OCR Required' : 'Failed'}
                </p>
              )}
            </div>
          </div>
        )
      })}
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
    needs_review: 'badge-warning',
    pending: 'badge-warning',
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

export default Runs
