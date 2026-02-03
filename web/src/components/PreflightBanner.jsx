/**
 * PreflightBanner Component (M3.P2.3)
 *
 * Shows validation status and blocking issues before export.
 * Displays at top of Review page with color-coded severity.
 */
import { useState, useEffect } from 'react'
import api from '../api'

function PreflightBanner({ runId, onIssueClick }) {
  const [preflight, setPreflight] = useState(null)
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (!runId) return

    const fetchPreflight = async () => {
      setLoading(true)
      try {
        const data = await api.getRunPreflight(runId)
        setPreflight(data)
      } catch (err) {
        console.error('Failed to fetch preflight:', err)
        setPreflight(null)
      } finally {
        setLoading(false)
      }
    }

    fetchPreflight()
  }, [runId])

  if (loading) {
    return (
      <div className="mb-4 p-3 bg-gray-100 rounded-lg animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-1/3"></div>
      </div>
    )
  }

  if (!preflight) {
    return null
  }

  const { is_ready, blocking_count, warning_count, issues } = preflight

  // Determine banner style based on status
  let bannerClass = 'bg-green-50 border-green-200'
  let iconClass = 'text-green-600'
  let title = 'Ready for Export'
  let icon = (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  )

  if (blocking_count > 0) {
    bannerClass = 'bg-red-50 border-red-200'
    iconClass = 'text-red-600'
    title = `${blocking_count} Blocking Issue${blocking_count > 1 ? 's' : ''}`
    icon = (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    )
  } else if (warning_count > 0) {
    bannerClass = 'bg-yellow-50 border-yellow-200'
    iconClass = 'text-yellow-600'
    title = `${warning_count} Warning${warning_count > 1 ? 's' : ''}`
    icon = (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    )
  }

  const blockingIssues = issues.filter(i => i.severity === 'blocking')
  const warningIssues = issues.filter(i => i.severity === 'warning')

  return (
    <div className={`mb-4 border rounded-lg ${bannerClass}`}>
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center justify-between cursor-pointer"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center space-x-3">
          <span className={iconClass}>{icon}</span>
          <span className="font-medium text-sm">{title}</span>
          {is_ready && warning_count === 0 && (
            <span className="text-xs text-green-600">All required fields present</span>
          )}
        </div>
        <button className="text-gray-500 hover:text-gray-700">
          <svg
            className={`w-4 h-4 transform transition-transform ${collapsed ? '' : 'rotate-180'}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Issues list */}
      {!collapsed && issues.length > 0 && (
        <div className="px-4 pb-3 border-t border-gray-200 mt-1 pt-3">
          {/* Blocking issues */}
          {blockingIssues.length > 0 && (
            <div className="mb-3">
              <div className="text-xs font-medium text-red-700 mb-2">Must fix before export:</div>
              <ul className="space-y-1">
                {blockingIssues.map((issue, idx) => (
                  <li
                    key={idx}
                    className="flex items-start text-sm text-red-800 cursor-pointer hover:bg-red-100 rounded px-2 py-1 -mx-2"
                    onClick={() => onIssueClick && onIssueClick(issue.field_key)}
                  >
                    <span className="text-red-500 mr-2">&#x2022;</span>
                    <span>
                      <span className="font-medium">{issue.field_key.replace(/_/g, ' ')}</span>
                      {': '}
                      {issue.issue}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Warning issues */}
          {warningIssues.length > 0 && (
            <div>
              <div className="text-xs font-medium text-yellow-700 mb-2">Warnings (optional):</div>
              <ul className="space-y-1">
                {warningIssues.map((issue, idx) => (
                  <li
                    key={idx}
                    className="flex items-start text-sm text-yellow-800 cursor-pointer hover:bg-yellow-100 rounded px-2 py-1 -mx-2"
                    onClick={() => onIssueClick && onIssueClick(issue.field_key)}
                  >
                    <span className="text-yellow-500 mr-2">&#x2022;</span>
                    <span>
                      <span className="font-medium">{issue.field_key.replace(/_/g, ' ')}</span>
                      {': '}
                      {issue.issue}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default PreflightBanner
