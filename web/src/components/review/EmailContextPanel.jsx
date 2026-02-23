import { useState, useEffect } from 'react'
import api from '../../api'
import { parseUTCDate } from '../../utils/date'

/**
 * Email Context Panel
 *
 * Shows the originating email context for email-sourced documents:
 * sender, subject, date, body text, and unified attachment list.
 *
 * Merges email-context attachments with run-level attachments for a
 * single view. Click an attachment to load it in the PDF viewer.
 */
export default function EmailContextPanel({ runId, document, runAttachments, onViewAttachment }) {
  const [emailCtx, setEmailCtx] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(true)
  const [previewImage, setPreviewImage] = useState(null)

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

  // If not an email-sourced doc but we have run attachments, still show attachments section
  const hasRunAttachments = runAttachments && runAttachments.length > 0

  if (loading || (!emailCtx && !hasRunAttachments)) return null

  const dateStr = emailCtx?.date
    ? parseUTCDate(emailCtx.date)?.toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : null

  // Merge email attachments + run attachments into a unified list.
  // Email attachments have: {filename, is_main_document, view_url, type}
  // Run attachments have: {filename, original_filename, type, url}
  const mergedAttachments = []
  const seenFilenames = new Set()

  // 1. Email attachments first (they have is_main_document flag)
  if (emailCtx?.attachments) {
    for (const att of emailCtx.attachments) {
      seenFilenames.add(att.filename)
      mergedAttachments.push({
        filename: att.filename,
        displayName: att.filename,
        isMain: att.is_main_document,
        viewUrl: att.view_url,
        type: att.type || guessType(att.filename),
      })
    }
  }

  // 2. Run attachments not already in email list
  if (runAttachments) {
    for (const att of runAttachments) {
      if (!seenFilenames.has(att.filename)) {
        seenFilenames.add(att.filename)
        mergedAttachments.push({
          filename: att.filename,
          displayName: att.original_filename || att.filename,
          isMain: false,
          viewUrl: att.url,
          type: att.type || guessType(att.filename),
        })
      }
    }
  }

  function guessType(filename) {
    const ext = (filename || '').split('.').pop().toLowerCase()
    if (ext === 'pdf') return 'pdf'
    if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'].includes(ext)) return 'image'
    return 'other'
  }

  function isImage(type) {
    return type === 'image'
  }

  function getTypeBadge(att) {
    if (att.isMain) return { label: 'Main', bg: 'bg-blue-100', text: 'text-blue-700' }
    switch (att.type) {
      case 'pdf':
      case 'listing_page':
        return { label: 'PDF', bg: 'bg-blue-50', text: 'text-blue-600' }
      case 'image':
        return { label: 'Image', bg: 'bg-green-100', text: 'text-green-700' }
      case 'vehicle_release':
        return { label: 'Release', bg: 'bg-purple-100', text: 'text-purple-700' }
      case 'condition_report':
        return { label: 'Condition', bg: 'bg-yellow-100', text: 'text-yellow-700' }
      default:
        return { label: att.type || 'File', bg: 'bg-gray-100', text: 'text-gray-600' }
    }
  }

  function handleView(att) {
    if (onViewAttachment && att.viewUrl) {
      // Load in the main viewer panel (supports both PDF iframe and image rendering)
      onViewAttachment(att.viewUrl)
    }
  }

  function handlePreview(att) {
    // Toggle inline preview for images within this panel
    setPreviewImage(previewImage === att.viewUrl ? null : att.viewUrl)
  }

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-blue-600 text-lg">&#9993;</span>
          <span className="font-medium text-blue-800">
            {emailCtx ? 'Email Context' : 'Attachments'}
          </span>
          {mergedAttachments.length > 0 && (
            <span className="text-xs text-blue-500">
              ({mergedAttachments.length} file{mergedAttachments.length !== 1 ? 's' : ''})
            </span>
          )}
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
          {/* Email metadata */}
          {emailCtx?.sender && (
            <div className="text-sm">
              <span className="text-blue-700 font-medium">From:</span>{' '}
              <span className="text-gray-800">{emailCtx.sender}</span>
            </div>
          )}
          {emailCtx?.subject && (
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

          {emailCtx?.body && (
            <div className="mt-2">
              <div className="text-xs text-blue-700 font-medium mb-1">Body:</div>
              <div className="bg-white rounded p-3 text-sm text-gray-700 whitespace-pre-wrap border border-blue-100 max-h-48 overflow-auto">
                {emailCtx.body}
              </div>
            </div>
          )}

          {/* Unified attachment list */}
          {mergedAttachments.length > 0 && (
            <div className="mt-2">
              <div className="text-xs text-blue-700 font-medium mb-1">Attachments:</div>
              <div className="space-y-1">
                {mergedAttachments.map((att, i) => {
                  const badge = getTypeBadge(att)
                  return (
                    <div key={i} className="flex items-center justify-between bg-white rounded px-3 py-2 text-sm border border-blue-100">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-gray-500 flex-shrink-0">
                          {isImage(att.type) ? '\u{1F5BC}' : '\u{1F4CE}'}
                        </span>
                        <span className="text-gray-800 truncate">{att.displayName}</span>
                        <span className={`px-1.5 py-0.5 text-xs rounded-full font-medium flex-shrink-0 ${badge.bg} ${badge.text}`}>
                          {badge.label}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                        {att.viewUrl && (
                          <button
                            type="button"
                            onClick={() => handleView(att)}
                            className={`px-2 py-1 text-xs rounded ${
                              att.isMain
                                ? 'bg-blue-100 border border-blue-400 text-blue-800 hover:bg-blue-200'
                                : 'bg-blue-50 border border-blue-300 text-blue-700 hover:bg-blue-100'
                            }`}
                          >
                            {att.isMain ? 'View main doc' : 'Open in viewer'}
                          </button>
                        )}
                        {att.viewUrl && isImage(att.type) && (
                          <button
                            type="button"
                            onClick={() => handlePreview(att)}
                            className="px-2 py-1 text-xs bg-green-50 border border-green-300 text-green-700 rounded hover:bg-green-100"
                          >
                            {previewImage === att.viewUrl ? 'Hide' : 'Preview'}
                          </button>
                        )}
                        {att.viewUrl && (
                          <button
                            type="button"
                            onClick={() => window.open(att.viewUrl, '_blank')}
                            className="px-2 py-1 text-xs bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-100"
                          >
                            New tab
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
              {/* Inline image preview */}
              {previewImage && (
                <div className="mt-2 border border-gray-200 rounded overflow-hidden bg-gray-100 p-2">
                  <img
                    src={previewImage}
                    alt="Attachment preview"
                    style={{ maxWidth: '100%', maxHeight: '400px', objectFit: 'contain' }}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
