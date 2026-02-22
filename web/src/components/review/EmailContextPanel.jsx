import { useState, useEffect } from 'react'
import api from '../../api'
import { parseUTCDate } from '../../utils/date'

/**
 * Email Context Panel
 *
 * Shows the originating email context for email-sourced documents:
 * sender, subject, date, body text, and attachment list.
 * Displayed on the Review page for all email-sourced docs.
 */
export default function EmailContextPanel({ runId, document }) {
  const [emailCtx, setEmailCtx] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    if (!runId || document?.source !== 'email') {
      setLoading(false)
      return
    }
    api.getEmailContext(runId)
      .then(data => {
        if (data.source === 'email') setEmailCtx(data)
      })
      .catch(err => console.debug('Email context not available:', err.message))
      .finally(() => setLoading(false))
  }, [runId, document?.source])

  if (loading || !emailCtx) return null

  const dateStr = emailCtx.date
    ? parseUTCDate(emailCtx.date)?.toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : null

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-blue-600 text-lg">&#9993;</span>
          <span className="font-medium text-blue-800">Email Context</span>
        </div>
        <svg
          className={`w-4 h-4 text-blue-600 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-2">
          {emailCtx.sender && (
            <div className="text-sm">
              <span className="text-blue-700 font-medium">From:</span>{' '}
              <span className="text-gray-800">{emailCtx.sender}</span>
            </div>
          )}
          {emailCtx.subject && (
            <div className="text-sm">
              <span className="text-blue-700 font-medium">Subject:</span>{' '}
              <span className="text-gray-800">{emailCtx.subject}</span>
            </div>
          )}
          {dateStr && (
            <div className="text-sm">
              <span className="text-blue-700 font-medium">Date:</span>{' '}
              <span className="text-gray-800">{dateStr}</span>
            </div>
          )}

          {emailCtx.body && (
            <div className="mt-2">
              <div className="text-xs text-blue-700 font-medium mb-1">Body:</div>
              <div className="bg-white rounded p-3 text-sm text-gray-700 whitespace-pre-wrap border border-blue-100 max-h-32 overflow-auto">
                {emailCtx.body}
              </div>
            </div>
          )}

          {emailCtx.attachments?.length > 0 && (
            <div className="mt-2">
              <div className="text-xs text-blue-700 font-medium mb-1">Attachments:</div>
              <div className="space-y-1">
                {emailCtx.attachments.map((att, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="text-gray-500">&#128196;</span>
                    <span className="text-gray-800">{att.filename}</span>
                    {att.is_main_document && (
                      <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Main</span>
                    )}
                    {att.view_url && (
                      <a
                        href={att.view_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-600 hover:text-blue-800 underline"
                      >
                        View
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
