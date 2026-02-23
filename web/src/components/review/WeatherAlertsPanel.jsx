import { useState, useEffect, useCallback } from 'react'
import api from '../../api'

/**
 * Weather Alerts Panel — shows NWS alerts along transport route.
 * Placed under DeliverySection in Review page.
 */
function WeatherAlertsPanel({ runId, warehouseId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [infoMessage, setInfoMessage] = useState(null)
  const [collapsed, setCollapsed] = useState(false) // start expanded

  const fetchAlerts = useCallback(async () => {
    if (!runId) return
    setLoading(true)
    setError(null)
    setInfoMessage(null)
    try {
      const result = await api.getRouteAlertsForRun(runId, warehouseId)
      setData(result)
    } catch (err) {
      if (err.message?.includes('400') || err.message?.includes('pickup ZIP')) {
        setInfoMessage('Pickup ZIP not available — weather check requires a pickup location.')
        setData(null)
      } else if (err.message?.includes('404')) {
        setInfoMessage('No warehouses configured — add a warehouse in Settings to check route weather.')
        setData(null)
      } else {
        setError(err.message)
      }
    } finally {
      setLoading(false)
    }
  }, [runId, warehouseId])

  useEffect(() => {
    fetchAlerts()
  }, [fetchAlerts])

  // Don't render if no runId
  if (!runId) return null

  // Severity styles
  const severityStyles = {
    critical: 'bg-red-50 border-red-300 text-red-800',
    warning: 'bg-red-50 border-red-200 text-red-700',
    advisory: 'bg-amber-50 border-amber-200 text-amber-800',
    info: 'bg-blue-50 border-blue-200 text-blue-700',
  }

  const severityDot = {
    critical: 'bg-red-500',
    warning: 'bg-red-400',
    advisory: 'bg-amber-400',
    info: 'bg-blue-400',
  }

  const alertCount = data?.alerts?.length || 0
  const hasAlerts = alertCount > 0

  // Format relative time
  function timeAgo(isoStr) {
    if (!isoStr) return ''
    const checked = new Date(isoStr)
    const now = new Date()
    const mins = Math.round((now - checked) / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.round(mins / 60)
    return `${hrs}h ago`
  }

  // Format date range
  function formatDateRange(onset, expires) {
    const parts = []
    if (onset) {
      try {
        const d = new Date(onset)
        parts.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
          d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }))
      } catch { parts.push(onset) }
    }
    if (expires) {
      try {
        const d = new Date(expires)
        parts.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
          d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }))
      } catch { parts.push(expires) }
    }
    return parts.join(' \u2192 ')
  }

  const isCollapsed = collapsed

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      {/* Header */}
      <button
        type="button"
        onClick={() => setCollapsed(!isCollapsed)}
        className="w-full flex items-center justify-between text-left"
      >
        <h3 className="text-sm font-semibold text-gray-900 flex items-center">
          <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
          </svg>
          Route Weather
          {loading && (
            <span className="ml-2 animate-spin inline-block w-3 h-3 border-2 border-gray-300 border-t-primary-600 rounded-full"></span>
          )}
          {!loading && data && (
            hasAlerts ? (
              <span className="ml-2 text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-medium">
                {alertCount} alert{alertCount !== 1 ? 's' : ''}
              </span>
            ) : (
              <span className="ml-2 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">
                Clear
              </span>
            )
          )}
          {!loading && !data && infoMessage && (
            <span className="ml-2 text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded font-medium">
              N/A
            </span>
          )}
        </h3>
        <svg className={`w-4 h-4 text-gray-400 transition-transform ${isCollapsed ? '' : 'rotate-180'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Body */}
      {!isCollapsed && (
        <div className="mt-3">
          {/* Loading */}
          {loading && !data && (
            <div className="p-4 text-center">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600 mx-auto mb-2"></div>
              <p className="text-xs text-gray-500">Checking weather along route...</p>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 mb-2">
              Failed to check weather: {error}
            </div>
          )}

          {/* Info message (no pickup ZIP, no warehouses, etc.) */}
          {!loading && !data && !error && infoMessage && (
            <div className="p-2 bg-gray-50 border border-gray-200 rounded text-xs text-gray-500">
              {infoMessage}
            </div>
          )}

          {/* AI Summary + Recommendation */}
          {data?.ai_summary && (
            <div className={`p-3 rounded border mb-2 ${
              data.risk_level === 'high' ? 'bg-red-50 border-red-300' :
              data.risk_level === 'medium' ? 'bg-amber-50 border-amber-200' :
              'bg-blue-50 border-blue-200'
            }`}>
              <div className="flex items-start gap-2">
                <span className={`mt-0.5 text-xs font-semibold px-1.5 py-0.5 rounded ${
                  data.risk_level === 'high' ? 'bg-red-200 text-red-800' :
                  data.risk_level === 'medium' ? 'bg-amber-200 text-amber-800' :
                  'bg-blue-200 text-blue-800'
                }`}>{data.risk_level.toUpperCase()} RISK</span>
                <p className="text-sm text-gray-800">{data.ai_summary}</p>
              </div>

              {/* Recommended pickup date */}
              {data.recommended_pickup_date && (
                <div className="mt-2 ml-14 p-2 bg-white bg-opacity-60 rounded border border-gray-200">
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-primary-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span className="text-sm font-medium text-gray-900">
                      Recommended pickup: {data.recommended_pickup_date}
                    </span>
                  </div>
                  {data.recommendation_reason && (
                    <p className="text-xs text-gray-600 mt-1 ml-6">{data.recommendation_reason}</p>
                  )}
                </div>
              )}

              {/* Fallback: old optimal_pickup_suggestion if no structured recommendation */}
              {!data.recommended_pickup_date && data.optimal_pickup_suggestion && (
                <p className="text-xs mt-2 ml-14 text-gray-600">
                  Suggested pickup: after {data.optimal_pickup_suggestion}
                </p>
              )}
            </div>
          )}

          {/* Pickup Scenarios */}
          {data?.scenarios?.length > 0 && (
            <div className="mb-2 space-y-1">
              <p className="text-xs font-medium text-gray-600 mb-1">Pickup Scenarios:</p>
              {data.scenarios.map((s, idx) => (
                <div key={idx} className={`p-2 rounded border text-xs flex items-start gap-2 ${
                  s.risk === 'high' ? 'bg-red-50 border-red-200' :
                  s.risk === 'medium' ? 'bg-amber-50 border-amber-200' :
                  'bg-green-50 border-green-200'
                }`}>
                  <span className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${
                    s.risk === 'high' ? 'bg-red-400' :
                    s.risk === 'medium' ? 'bg-amber-400' :
                    'bg-green-400'
                  }`}></span>
                  <div>
                    <span className="font-medium text-gray-800">{s.label}</span>
                    <span className="text-gray-600 ml-1">— {s.detail}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Transit info */}
          {data?.transit && (
            <div className="p-2 bg-gray-50 border border-gray-200 rounded mb-2 flex items-center gap-4 text-xs text-gray-600">
              <span className="font-medium text-gray-700">Transit:</span>
              {data.transit.distance_miles && (
                <span>{Math.round(data.transit.distance_miles)} mi</span>
              )}
              {data.transit.drive_hours && (
                <span>{data.transit.drive_hours}h drive</span>
              )}
              {data.transit.total_hours && (
                <span>{data.transit.total_hours}h total (incl. loading)</span>
              )}
            </div>
          )}

          {/* Alerts */}
          {data && hasAlerts && (
            <div className="space-y-2">
              {data.alerts.map((alert, idx) => (
                <div
                  key={alert.alert_id || idx}
                  className={`p-3 rounded border ${severityStyles[alert.severity] || severityStyles.info}`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${severityDot[alert.severity] || severityDot.info}`}></span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium">{alert.event}</span>
                        <span className="text-xs opacity-75">{alert.urgency}</span>
                      </div>
                      {alert.headline && (
                        <p className="text-xs mt-1 opacity-90">{alert.headline}</p>
                      )}
                      <div className="flex items-center gap-3 mt-1 text-xs opacity-75">
                        {alert.area && <span>{alert.area}</span>}
                        {(alert.onset || alert.expires) && (
                          <span>{formatDateRange(alert.onset, alert.expires)}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Clear route */}
          {data && !hasAlerts && !loading && (
            <div className="p-3 bg-green-50 border border-green-200 rounded">
              <div className="flex items-center gap-2 text-sm text-green-700">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <span className="font-medium">No active weather alerts along route</span>
              </div>
              {data.route_states?.length > 0 && (
                <p className="text-xs text-green-600 mt-1 ml-6">
                  Route through: {data.route_states.join(', ')}
                </p>
              )}
            </div>
          )}

          {/* Footer: cached status + refresh */}
          {data && (
            <div className="flex items-center justify-between mt-2 text-xs text-gray-400">
              <span>
                {data.cached ? 'Cached' : 'Live'} &middot; {timeAgo(data.checked_at)}
                {data.route_states?.length > 0 && hasAlerts && (
                  <> &middot; {data.waypoints_checked} waypoints &middot; {data.route_states.length} states</>
                )}
              </span>
              <button
                type="button"
                onClick={fetchAlerts}
                disabled={loading}
                className="text-primary-600 hover:text-primary-800 underline"
              >
                {loading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default WeatherAlertsPanel
