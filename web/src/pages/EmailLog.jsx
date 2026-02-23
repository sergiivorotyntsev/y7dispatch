import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { parseUTCDate, formatTimeAgo as utilFormatTimeAgo } from '../utils/date'

function EmailLog() {
  const navigate = useNavigate()
  const [emails, setEmails] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [stats, setStats] = useState(null)

  // Filters
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const [searchDebounced, setSearchDebounced] = useState('')
  const [pagination, setPagination] = useState({ page: 1, limit: 50, total: 0 })

  // Expanded rows
  const [expandedId, setExpandedId] = useState(null)

  // Action states
  const [processingId, setProcessingId] = useState(null)
  const [polling, setPolling] = useState(false)

  // Poll date picker
  const [pollSinceDate, setPollSinceDate] = useState('')
  const [pollResult, setPollResult] = useState(null)

  // Auto-poll status
  const [pollStatus, setPollStatus] = useState(null)

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setSearchDebounced(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const data = await api.getEmailStats()
      setStats(data)
    } catch (err) {
      console.error('Failed to fetch email stats:', err)
    }
  }, [])

  // Fetch emails
  const fetchEmails = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        limit: pagination.limit,
        offset: (pagination.page - 1) * pagination.limit,
      }
      if (statusFilter) params.status = statusFilter
      if (searchDebounced.trim()) params.sender = searchDebounced.trim()

      const data = await api.getEmailLog(params)
      setEmails(data.items || [])
      setPagination(p => ({ ...p, total: data.total || 0 }))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, searchDebounced, pagination.page, pagination.limit])

  // Fetch poll status
  const fetchPollStatus = useCallback(async () => {
    try {
      const data = await api.getPollStatus()
      setPollStatus(data)
    } catch (err) {
      console.debug('Poll status unavailable:', err.message)
    }
  }, [])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => { fetchEmails() }, [fetchEmails])
  useEffect(() => { fetchPollStatus() }, [fetchPollStatus])

  // Refresh poll status every 30s
  useEffect(() => {
    const timer = setInterval(fetchPollStatus, 30000)
    return () => clearInterval(timer)
  }, [fetchPollStatus])

  // Actions
  async function handleProcess(emailId, e) {
    e.stopPropagation()
    setProcessingId(emailId)
    try {
      await api.processEmail(emailId)
      fetchEmails()
      fetchStats()
    } catch (err) {
      setError(`Process failed: ${err.message}`)
    } finally {
      setProcessingId(null)
    }
  }

  async function handleSkip(emailId, e) {
    e.stopPropagation()
    try {
      await api.skipEmail(emailId)
      fetchEmails()
      fetchStats()
    } catch (err) {
      setError(`Skip failed: ${err.message}`)
    }
  }

  async function handleReprocess(emailId, e) {
    e.stopPropagation()
    setProcessingId(emailId)
    try {
      await api.reprocessEmail(emailId)
      fetchEmails()
      fetchStats()
    } catch (err) {
      setError(`Reprocess failed: ${err.message}`)
    } finally {
      setProcessingId(null)
    }
  }

  async function handlePollNow(sinceDays = null) {
    setPolling(true)
    setPollResult(null)
    try {
      let result
      if (pollSinceDate) {
        result = await api.pollEmailNow(0, pollSinceDate)
      } else if (sinceDays !== null) {
        result = await api.pollEmailNow(sinceDays)
      } else {
        result = await api.pollEmailNow(7)
      }
      setError(null)
      fetchEmails()
      fetchStats()
      fetchPollStatus()
      setPollResult(result)
    } catch (err) {
      setError(`Poll failed: ${err.message}`)
    } finally {
      setPolling(false)
    }
  }

  function formatTimeAgo(dateStr) {
    return utilFormatTimeAgo(dateStr)
  }

  function getStatusBadge(status) {
    const map = {
      processed:    { label: 'Processed',    cls: 'bg-green-100 text-green-800' },
      skipped:      { label: 'Skipped',      cls: 'bg-gray-100 text-gray-600' },
      thread_reply: { label: 'Thread Reply', cls: 'bg-gray-100 text-gray-500' },
      duplicate:    { label: 'Duplicate',    cls: 'bg-gray-100 text-gray-500' },
      failed:       { label: 'Failed',       cls: 'bg-red-100 text-red-800' },
      ready:        { label: 'Ready',        cls: 'bg-blue-100 text-blue-800' },
      new:          { label: 'New',          cls: 'bg-yellow-100 text-yellow-800' },
      processing:   { label: 'Processing',   cls: 'bg-blue-100 text-blue-700' },
    }
    const badge = map[status] || { label: status || 'Unknown', cls: 'bg-gray-100 text-gray-600' }
    return <span className={`px-2 py-1 text-xs font-medium rounded ${badge.cls}`}>{badge.label}</span>
  }

  function formatDate(dateStr) {
    if (!dateStr) return '-'
    try {
      const d = parseUTCDate(dateStr)
      if (!d) return '-'
      return d.toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      })
    } catch { return dateStr }
  }

  function shortenEmail(email) {
    if (!email) return '-'
    if (email.length > 25) return email.substring(0, 22) + '...'
    return email
  }

  function shortenSubject(subject) {
    if (!subject) return '-'
    if (subject.length > 45) return subject.substring(0, 42) + '...'
    return subject
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Email Log</h1>
          <p className="text-sm text-gray-500 mt-1">Ingested emails and processing status</p>
        </div>
      </div>

      {/* Poll Controls */}
      <div className="mb-4 px-4 py-3 bg-white border rounded-lg shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-gray-700">Poll emails from:</span>
          <input
            type="date"
            value={pollSinceDate}
            onChange={e => setPollSinceDate(e.target.value)}
            className="form-input text-sm px-2 py-1.5 border-gray-300 rounded"
            max={new Date().toISOString().split('T')[0]}
          />
          <div className="flex gap-1.5">
            <button
              onClick={() => { setPollSinceDate(''); handlePollNow(7) }}
              disabled={polling}
              className="px-2.5 py-1.5 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
            >
              7 days
            </button>
            <button
              onClick={() => { setPollSinceDate(''); handlePollNow(14) }}
              disabled={polling}
              className="px-2.5 py-1.5 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
            >
              14 days
            </button>
            <button
              onClick={() => { setPollSinceDate(''); handlePollNow(30) }}
              disabled={polling}
              className="px-2.5 py-1.5 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
            >
              30 days
            </button>
          </div>
          <button
            onClick={() => handlePollNow()}
            disabled={polling}
            className="px-4 py-1.5 bg-primary-600 text-white text-sm rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {polling ? 'Polling...' : 'Poll Now'}
          </button>
        </div>

        {/* Poll result notification */}
        {pollResult && (
          <div className="mt-3 p-2.5 bg-green-50 border border-green-200 rounded text-sm">
            <div className="flex items-center gap-2 text-green-800">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span className="font-medium">
                Poll complete: {pollResult.processed || 0} processed, {pollResult.skipped || 0} skipped, {pollResult.failed || 0} failed
              </span>
              <button onClick={() => setPollResult(null)} className="ml-auto text-green-600 hover:text-green-800 text-xs">Dismiss</button>
            </div>
            {/* VIN duplicate warnings */}
            {pollResult.vin_duplicates?.length > 0 && (
              <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded">
                <div className="text-amber-800 text-xs font-medium mb-1">
                  {pollResult.vin_duplicates.length} duplicate VIN{pollResult.vin_duplicates.length !== 1 ? 's' : ''} detected:
                </div>
                {pollResult.vin_duplicates.map((dup, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-amber-700 ml-2">
                    <span className="font-mono">{dup.vin}</span>
                    <span>- already {dup.existing_status?.replace('_', ' ') || 'exists'}</span>
                    {dup.existing_run_id && (
                      <button
                        onClick={() => navigate(`/review/${dup.existing_run_id}`)}
                        className="text-blue-600 hover:text-blue-800 underline"
                      >
                        View
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Auto-poll status bar */}
      {pollStatus && (
        <div className="mb-4 px-4 py-2 bg-gray-50 border rounded-lg flex items-center justify-between text-sm">
          <div className="flex items-center space-x-4">
            <span className="flex items-center">
              <span className={`inline-block w-2 h-2 rounded-full mr-2 ${
                pollStatus.is_polling ? 'bg-blue-500 animate-pulse' :
                pollStatus.enabled ? 'bg-green-500' : 'bg-gray-400'
              }`} />
              Auto-poll: {pollStatus.enabled ? 'ON' : 'OFF'}
              {pollStatus.enabled && pollStatus.interval_minutes && (
                <span className="text-gray-500 ml-1">(every {pollStatus.interval_minutes} min)</span>
              )}
            </span>
            {pollStatus.is_polling && (
              <span className="text-blue-600 font-medium">Polling...</span>
            )}
            {pollStatus.last_poll_at && !pollStatus.is_polling && (
              <span className="text-gray-500">
                Last: {formatTimeAgo(pollStatus.last_poll_at)}
              </span>
            )}
          </div>
          {pollStatus.last_poll_error && (
            <span className="text-red-600 text-xs truncate max-w-[300px]" title={pollStatus.last_poll_error}>
              Error: {pollStatus.last_poll_error}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-3 underline">Dismiss</button>
        </div>
      )}

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-5 gap-3 mb-6">
          <div className="bg-white p-3 rounded-lg shadow text-center">
            <p className="text-xs text-gray-500">Total</p>
            <p className="text-xl font-bold text-gray-900">{stats.total}</p>
          </div>
          <div className="bg-white p-3 rounded-lg shadow text-center">
            <p className="text-xs text-gray-500">Processed</p>
            <p className="text-xl font-bold text-green-600">{stats.processed}</p>
          </div>
          <div className="bg-white p-3 rounded-lg shadow text-center">
            <p className="text-xs text-gray-500">Skipped</p>
            <p className="text-xl font-bold text-gray-500">{stats.skipped + (stats.thread_reply || 0) + (stats.duplicate || 0)}</p>
          </div>
          <div className="bg-white p-3 rounded-lg shadow text-center">
            <p className="text-xs text-gray-500">Ready/New</p>
            <p className="text-xl font-bold text-blue-600">{(stats.ready || 0) + (stats.new || 0)}</p>
          </div>
          <div className="bg-white p-3 rounded-lg shadow text-center">
            <p className="text-xs text-gray-500">Failed</p>
            <p className="text-xl font-bold text-red-600">{stats.failed}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="bg-white p-4 rounded-lg shadow mb-6">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-sm font-medium text-gray-700 mb-1">Search</label>
            <input
              type="text"
              placeholder="Search by sender or subject..."
              value={search}
              onChange={e => { setSearch(e.target.value); setPagination(p => ({ ...p, page: 1 })) }}
              className="form-input w-full text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <select
              value={statusFilter}
              onChange={e => { setStatusFilter(e.target.value); setPagination(p => ({ ...p, page: 1 })) }}
              className="form-select"
            >
              <option value="">All Status</option>
              <option value="processed">Processed</option>
              <option value="skipped">Skipped</option>
              <option value="failed">Failed</option>
              <option value="ready">Ready</option>
              <option value="new">New</option>
              <option value="thread_reply">Thread Reply</option>
              <option value="duplicate">Duplicate</option>
            </select>
          </div>
          <button onClick={() => { fetchEmails(); fetchStats() }} className="btn btn-secondary">
            Refresh
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
          <span className="ml-3 text-gray-600">Loading emails...</span>
        </div>
      ) : emails.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <p className="text-gray-500">No emails found</p>
        </div>
      ) : (
        <>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">From</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Subject</th>
                <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase">Attach</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Gate Pass</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {emails.map((email) => {
                const isExpanded = expandedId === email.id
                const attachments = Array.isArray(email.attachment_names)
                  ? email.attachment_names
                  : []
                const runIds = Array.isArray(email.extraction_run_ids)
                  ? email.extraction_run_ids
                  : []
                const canProcess = ['failed', 'skipped', 'new', 'ready'].includes(email.status)

                return (
                  <tr key={email.id} className="group">
                    <td colSpan={7} className="p-0">
                      {/* Main row */}
                      <div
                        className={`flex items-center cursor-pointer hover:bg-gray-50 ${isExpanded ? 'bg-blue-50' : ''}`}
                        onClick={() => setExpandedId(isExpanded ? null : email.id)}
                      >
                        <div className="px-4 py-3 w-[110px] text-sm text-gray-600 shrink-0">
                          {formatDate(email.received_date || email.created_at)}
                        </div>
                        <div className="px-4 py-3 w-[160px] shrink-0">
                          <span className="text-sm text-gray-700" title={email.sender}>
                            {shortenEmail(email.sender_name || email.sender)}
                          </span>
                        </div>
                        <div className="px-4 py-3 flex-1 min-w-0">
                          <span className="text-sm text-gray-900 truncate block" title={email.subject}>
                            {shortenSubject(email.subject)}
                          </span>
                        </div>
                        <div className="px-3 py-3 w-[60px] text-center shrink-0">
                          {(email.attachment_count || 0) > 0 ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                              {email.attachment_count}
                            </span>
                          ) : (
                            <span className="text-sm text-gray-400">0</span>
                          )}
                        </div>
                        <div className="px-3 py-3 w-[80px] shrink-0">
                          <span className="font-mono text-xs text-gray-700">{email.gate_pass || '-'}</span>
                        </div>
                        <div className="px-4 py-3 w-[110px] shrink-0">
                          {getStatusBadge(email.status)}
                        </div>
                        <div className="px-4 py-3 w-[120px] text-right shrink-0" onClick={e => e.stopPropagation()}>
                          {canProcess && (
                            <button
                              onClick={(e) => handleProcess(email.id, e)}
                              disabled={processingId === email.id}
                              className="text-sm text-blue-600 hover:text-blue-800 mr-2"
                              title="Process"
                            >
                              {processingId === email.id ? '...' : 'Process'}
                            </button>
                          )}
                          {email.status === 'processed' && (
                            <button
                              onClick={(e) => handleReprocess(email.id, e)}
                              disabled={processingId === email.id}
                              className="text-sm text-orange-600 hover:text-orange-800"
                              title="Reprocess from source"
                            >
                              {processingId === email.id ? '...' : 'Redo'}
                            </button>
                          )}
                          {['new', 'ready', 'failed'].includes(email.status) && (
                            <button
                              onClick={(e) => handleSkip(email.id, e)}
                              className="text-sm text-gray-500 hover:text-gray-700"
                              title="Skip email"
                            >
                              Skip
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Expanded detail */}
                      {isExpanded && (
                        <div className="px-6 py-4 bg-gray-50 border-t border-gray-100">
                          <div className="grid grid-cols-2 gap-6">
                            {/* Left: body preview */}
                            <div>
                              <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">Body Preview</h4>
                              <div className="text-sm text-gray-700 bg-white p-3 rounded border max-h-32 overflow-auto whitespace-pre-wrap">
                                {email.body_preview || '(no preview)'}
                              </div>
                              {email.skip_reason && (
                                <p className="mt-2 text-xs text-orange-600">Skip reason: {email.skip_reason}</p>
                              )}
                              {email.error_message && (
                                <p className="mt-2 text-xs text-red-600">Error: {email.error_message}</p>
                              )}
                            </div>

                            {/* Right: attachments + linked docs */}
                            <div>
                              <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">
                                Attachments ({attachments.length})
                              </h4>
                              {attachments.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                  {attachments.map((name, i) => {
                                    const isPdf = name.toLowerCase().endsWith('.pdf')
                                    // Find matching linked document for this attachment
                                    const linkedDoc = (email.linked_documents || []).find(ld =>
                                      ld.filename?.includes(name.replace(/[^a-zA-Z0-9]/g, '').substring(0, 10)) ||
                                      name.includes(ld.filename?.split('_').pop()?.replace(/[^a-zA-Z0-9.]/g, '') || '___NOMATCH')
                                    )
                                    // If only one linked doc and one PDF attachment, match them
                                    const singleMatch = isPdf && (email.linked_documents || []).length === 1 && attachments.filter(a => a.toLowerCase().endsWith('.pdf')).length <= 2
                                      ? email.linked_documents[0]
                                      : null
                                    const docLink = linkedDoc || singleMatch

                                    return docLink ? (
                                      <a
                                        key={i}
                                        href={`/api/documents/${docLink.document_id}/file`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className={`inline-flex items-center px-2.5 py-1 rounded text-xs font-medium cursor-pointer hover:shadow-sm transition-shadow ${
                                          isPdf ? 'bg-red-50 text-red-700 border border-red-200 hover:bg-red-100' : 'bg-gray-50 text-gray-700 border border-gray-200 hover:bg-gray-100'
                                        }`}
                                        title={`${name} — Click to view`}
                                      >
                                        <svg className="w-3 h-3 mr-1.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                        </svg>
                                        {name.length > 30 ? name.substring(0, 27) + '...' : name}
                                      </a>
                                    ) : (
                                      <span
                                        key={i}
                                        className={`inline-flex items-center px-2.5 py-1 rounded text-xs font-medium ${
                                          isPdf ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-gray-50 text-gray-700 border border-gray-200'
                                        }`}
                                        title={name}
                                      >
                                        <span className="mr-1.5">{isPdf ? 'PDF' : 'File'}</span>
                                        {name.length > 30 ? name.substring(0, 27) + '...' : name}
                                      </span>
                                    )
                                  })}
                                </div>
                              ) : (
                                <p className="text-sm text-gray-400">No attachments</p>
                              )}

                              {(email.linked_documents || []).length > 0 && (
                                <div className="mt-3">
                                  <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Linked Documents</h4>
                                  <div className="flex flex-wrap gap-2">
                                    {email.linked_documents.map((ld) => (
                                      <div key={ld.run_id} className="flex items-center gap-1.5">
                                        <button
                                          onClick={() => navigate(`/review/${ld.run_id}`)}
                                          className="inline-flex items-center px-2.5 py-1 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 transition-colors"
                                        >
                                          <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                          </svg>
                                          Open in Review
                                        </button>
                                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                                          ld.run_status === 'exported' ? 'bg-green-100 text-green-700' :
                                          ld.run_status === 'needs_review' ? 'bg-yellow-100 text-yellow-700' :
                                          ld.run_status === 'manual_required' ? 'bg-red-100 text-red-700' :
                                          'bg-gray-100 text-gray-600'
                                        }`}>
                                          {ld.run_status?.replace('_', ' ') || 'unknown'}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pagination.total > pagination.limit && (
          <div className="flex items-center justify-between mt-4 px-4 py-3 bg-gray-50 rounded-lg">
            <div className="text-sm text-gray-600">
              Showing {((pagination.page - 1) * pagination.limit) + 1} to {Math.min(pagination.page * pagination.limit, pagination.total)} of {pagination.total}
            </div>
            <div className="flex space-x-2">
              <button
                onClick={() => setPagination(p => ({ ...p, page: Math.max(1, p.page - 1) }))}
                disabled={pagination.page === 1}
                className="btn btn-sm btn-secondary disabled:opacity-50"
              >
                Previous
              </button>
              <span className="px-3 py-1 bg-white border rounded text-sm">
                Page {pagination.page} of {Math.ceil(pagination.total / pagination.limit)}
              </span>
              <button
                onClick={() => setPagination(p => ({ ...p, page: Math.min(Math.ceil(p.total / p.limit), p.page + 1) }))}
                disabled={pagination.page >= Math.ceil(pagination.total / pagination.limit)}
                className="btn btn-sm btn-secondary disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
        </>
      )}
    </div>
  )
}

export default EmailLog
