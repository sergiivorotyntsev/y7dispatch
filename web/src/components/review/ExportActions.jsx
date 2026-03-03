/**
 * Section 9: Export Actions
 * Preflight summary, export/save buttons, progress summary.
 *
 * States:
 * - Default: shows preflight + field counter + approve button
 * - isApproved: shows "Export to CD" button, hides approve
 * - isExported: shows exported summary, hides counters/buttons/helper text
 */
import { useState, useEffect } from 'react'
import PreflightBanner from '../PreflightBanner'
import api from '../../api'

function ReplyPreviewModal({ runId, onClose, onSent }) {
  const [state, setState] = useState('loading') // loading | error | ready | sending
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.previewConfirmationReply(runId).then(data => {
      if (cancelled) return
      if (data.success) {
        setPreview(data)
        setState('ready')
      } else {
        setError(data.error || 'Failed to load preview')
        setState('error')
      }
    }).catch(err => {
      if (cancelled) return
      setError(err.message || 'Network error')
      setState('error')
    })
    return () => { cancelled = true }
  }, [runId])

  const handleSend = async () => {
    setState('sending')
    setError(null)
    try {
      const result = await api.sendConfirmationReply(runId)
      if (result.success) {
        onSent(result)
      } else if (result.already_sent) {
        onSent(result)
      } else {
        setError(result.error || 'Failed to send reply')
        setState('ready')
      }
    } catch (err) {
      setError(err.message || 'Network error')
      setState('ready')
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <div style={{
        backgroundColor: '#fff', borderRadius: '12px', width: '100%', maxWidth: '680px',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 25px 50px rgba(0,0,0,0.15)',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid #e5e7eb' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#111827' }}>
              Preview Confirmation Email
            </h3>
            <button
              onClick={onClose}
              disabled={state === 'sending'}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: '20px', color: '#6b7280', lineHeight: 1, padding: '4px',
              }}
            >
              &times;
            </button>
          </div>
          {/* Metadata */}
          {preview && (
            <div style={{ marginTop: '12px', fontSize: '13px', color: '#4b5563', lineHeight: '1.7' }}>
              <div><span style={{ color: '#9ca3af', fontWeight: 500 }}>To:</span> {preview.recipient_name ? `${preview.recipient_name} <${preview.recipient_email}>` : preview.recipient_email}</div>
              {preview.subject && <div><span style={{ color: '#9ca3af', fontWeight: 500 }}>Subject:</span> Re: {preview.subject}</div>}
              <div><span style={{ color: '#9ca3af', fontWeight: 500 }}>Load ID:</span> <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{preview.cd_listing_id}</span></div>
            </div>
          )}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: 'auto', padding: '24px' }}>
          {state === 'loading' && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px 0' }}>
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" style={{ marginRight: '12px' }}></div>
              <span style={{ color: '#6b7280', fontSize: '14px' }}>Loading preview...</span>
            </div>
          )}
          {state === 'error' && !preview && (
            <div style={{
              padding: '16px', backgroundColor: '#fef2f2', border: '1px solid #fecaca',
              borderRadius: '8px', color: '#991b1b', fontSize: '14px',
            }}>
              {error}
            </div>
          )}
          {preview && (
            <div style={{
              border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#fff',
              boxShadow: '0 1px 3px rgba(0,0,0,0.08)', padding: '24px',
            }}>
              <div dangerouslySetInnerHTML={{ __html: preview.preview_html }} />
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '16px 24px', borderTop: '1px solid #e5e7eb',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div style={{ fontSize: '13px', color: '#dc2626', minHeight: '20px' }}>
            {error && state !== 'loading' && preview && error}
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={onClose}
              disabled={state === 'sending'}
              style={{
                padding: '8px 16px', fontSize: '14px', fontWeight: 500, borderRadius: '6px',
                border: '1px solid #d1d5db', backgroundColor: '#fff', color: '#374151',
                cursor: state === 'sending' ? 'not-allowed' : 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              onClick={handleSend}
              disabled={state !== 'ready'}
              style={{
                padding: '8px 16px', fontSize: '14px', fontWeight: 500, borderRadius: '6px',
                border: 'none', color: '#fff', cursor: state === 'ready' ? 'pointer' : 'not-allowed',
                backgroundColor: state === 'ready' ? '#2563eb' : '#9ca3af',
                display: 'flex', alignItems: 'center', gap: '6px',
              }}
            >
              {state === 'sending' ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  Sending...
                </>
              ) : (
                'Send'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function ExportActions({
  runId, isTrainingMode, saving,
  handleSubmitTraining, handleSubmitProduction, handleSaveChanges,
  showExportModal, setShowExportModal,
  exportResult, exportError, exporting,
  selectedWarehouse, isApproved, isExported, runStatus,
  correctCount, totalCount, correctedCount, needsReviewCount,
  // Reply state — managed by parent (Review.jsx)
  replyStatus, repliedTo, replyError, onReplyClick,
}) {
  return (
    <div className="space-y-4">

      {/* Preflight Banner — hide after export, show "Exported" instead */}
      {isExported ? (
        <div className="mb-4 border rounded-lg bg-green-50 border-green-200">
          <div className="px-4 py-3 flex items-center space-x-3">
            <span className="text-green-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-medium text-sm text-green-800">Exported to Central Dispatch</span>
            {exportResult?.cd_listing_id && exportResult.cd_listing_id !== 'unknown' && (
              <span className="text-sm text-green-700">
                CD Listing ID: <span className="font-mono font-medium">{exportResult.cd_listing_id}</span>
              </span>
            )}
          </div>
          {/* Send Confirmation Email button */}
          <div className="px-4 pb-3 flex items-center gap-3">
            {replyStatus === 'sent' ? (
              <span className="inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-green-700 bg-green-100 border border-green-300 rounded-md">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Confirmation Sent
                {repliedTo && <span className="text-green-600 font-normal ml-1">to {repliedTo}</span>}
              </span>
            ) : replyStatus === 'loading' ? (
              <button disabled className="px-3 py-1.5 text-sm font-medium text-gray-500 bg-gray-100 border border-gray-300 rounded-md cursor-not-allowed">
                Loading...
              </button>
            ) : replyStatus === 'failed' ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={onReplyClick}
                  className="px-3 py-1.5 text-sm font-medium text-red-700 bg-red-50 border border-red-300 rounded-md hover:bg-red-100"
                >
                  Retry Send Email
                </button>
                {replyError && <span className="text-xs text-red-600">{replyError}</span>}
              </div>
            ) : (
              <button
                onClick={onReplyClick}
                className="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-300 rounded-md hover:bg-blue-100"
              >
                Send Confirmation Email
              </button>
            )}
          </div>
        </div>
      ) : (
        <PreflightBanner
          runId={parseInt(runId)}
          mode={isTrainingMode ? 'training' : 'production'}
          warehouseId={selectedWarehouse ? parseInt(selectedWarehouse) : null}
        />
      )}

      {/* Export to CD section (production only, not yet exported) */}
      {!isTrainingMode && !isExported && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          {exportResult ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-100 text-purple-800">
                  Exported
                </span>
                <span className="text-sm text-gray-600">
                  CD Listing ID: <span className="font-mono font-medium">{exportResult.cd_listing_id}</span>
                </span>
              </div>
            </div>
          ) : (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-3">Export to Central Dispatch</h3>
              {exportError && (
                <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                  <p className="font-medium">Export failed</p>
                  <p>{typeof exportError === 'object' ? exportError.message || JSON.stringify(exportError) : exportError}</p>
                </div>
              )}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowExportModal(true)}
                  disabled={exporting}
                  className={exportError
                    ? "px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-md"
                    : "btn btn-primary bg-green-600 hover:bg-green-700"
                  }
                >
                  {exporting ? 'Exporting...' : exportError ? 'Retry Export' : 'Export to CD'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Bottom Actions Bar — hidden when exported */}
      {!isExported && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex justify-between items-center">
            {/* Field counters */}
            <div className="text-sm text-gray-600">
              <span className="text-green-600 font-medium">{correctCount}</span> correct
              {correctedCount > 0 && (
                <> {' \u2022 '} <span className="text-blue-600 font-medium">{correctedCount}</span> corrected</>
              )}
              {needsReviewCount > 0 && (
                <> {' \u2022 '} <span className="text-orange-600 font-medium">{needsReviewCount}</span> need review</>
              )}
            </div>
            {/* Action buttons */}
            {isTrainingMode ? (
              <button onClick={handleSubmitTraining} className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving...' : 'Save & Train'}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                {/* Save Changes — all non-exported, non-archived */}
                {!isExported && runStatus !== 'archived' && handleSaveChanges && (
                  <button
                    onClick={handleSaveChanges}
                    className="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-300 rounded-md hover:bg-blue-100"
                    disabled={saving}
                  >
                    {saving ? 'Saving...' : 'Save Changes'}
                  </button>
                )}
                {isApproved ? (
                  <span className="px-4 py-2 rounded-md text-sm font-medium bg-green-100 text-green-800 border border-green-300">
                    Approved
                  </span>
                ) : !isExported ? (
                  <button
                    onClick={handleSubmitProduction}
                    className={`btn btn-primary ${selectedWarehouse ? 'bg-green-600 hover:bg-green-700' : 'bg-gray-300 text-gray-500 cursor-not-allowed'}`}
                    disabled={saving || !selectedWarehouse}
                    title={!selectedWarehouse ? 'Select a delivery warehouse first' : ''}
                  >
                    {saving ? 'Approving...' : 'Approve for Export'}
                  </button>
                ) : null}
              </div>
            )}
          </div>
          {/* Warehouse required warning */}
          {!isTrainingMode && !isApproved && !selectedWarehouse && (
            <p className="text-xs text-amber-600 mt-2 font-medium">
              Select a delivery warehouse before approving for export.
            </p>
          )}
          {/* Helper text — hidden when approved */}
          {!isApproved && selectedWarehouse && (
            <p className="text-xs text-gray-500 mt-3">
              {isTrainingMode
                ? 'Your corrections help train the system to extract similar documents more accurately.'
                : 'After approval, this listing will be ready for export to Central Dispatch.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export { ReplyPreviewModal }
export default ExportActions
