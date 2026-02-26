import { useState, useEffect, useRef } from 'react'
import api from '../../api'

function EmailTemplateEditor() {
  const [bodyHtml, setBodyHtml] = useState('')
  const [savedHtml, setSavedHtml] = useState('')
  const [description, setDescription] = useState('')
  const [variables, setVariables] = useState([])
  const [previewHtml, setPreviewHtml] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [message, setMessage] = useState(null)
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const textareaRef = useRef(null)

  const hasUnsavedChanges = bodyHtml !== savedHtml

  // Load template on mount
  useEffect(() => {
    loadTemplate()
  }, [])

  async function loadTemplate() {
    setLoading(true)
    try {
      const data = await api.getReplyTemplate()
      setBodyHtml(data.body_html)
      setSavedHtml(data.body_html)
      setDescription(data.description || '')
      setVariables(data.available_variables || [])
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to load template: ' + (err.message || err) })
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    setMessage(null)
    try {
      await api.updateReplyTemplate(bodyHtml)
      setSavedHtml(bodyHtml)
      setMessage({ type: 'success', text: 'Template saved' })
    } catch (err) {
      const detail = err?.detail || err?.message || 'Save failed'
      setMessage({ type: 'error', text: detail })
    } finally {
      setSaving(false)
    }
  }

  async function handlePreview() {
    setPreviewing(true)
    try {
      const data = await api.previewReplyTemplate(bodyHtml)
      setPreviewHtml(data.preview_html)
    } catch (err) {
      setMessage({ type: 'error', text: 'Preview failed: ' + (err.message || err) })
    } finally {
      setPreviewing(false)
    }
  }

  async function handleReset() {
    setShowResetConfirm(false)
    setSaving(true)
    setMessage(null)
    try {
      await api.resetReplyTemplate()
      await loadTemplate()
      setPreviewHtml('')
      setMessage({ type: 'success', text: 'Template reset to default' })
    } catch (err) {
      setMessage({ type: 'error', text: 'Reset failed: ' + (err.message || err) })
    } finally {
      setSaving(false)
    }
  }

  function insertVariable(key) {
    const ta = textareaRef.current
    if (!ta) return
    const placeholder = '{{' + key + '}}'
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const before = bodyHtml.substring(0, start)
    const after = bodyHtml.substring(end)
    const newValue = before + placeholder + after
    setBodyHtml(newValue)
    // Restore cursor after the inserted placeholder
    requestAnimationFrame(() => {
      ta.focus()
      const newPos = start + placeholder.length
      ta.setSelectionRange(newPos, newPos)
    })
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <span className="ml-3 text-gray-600">Loading template...</span>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Email Reply Template</h3>
        <p className="text-sm text-gray-500 mt-1">{description || 'This template is used for confirmation emails sent after Central Dispatch export.'}</p>
      </div>

      {/* Toast message */}
      {message && (
        <div className={
          'mb-4 px-4 py-3 rounded-lg text-sm ' +
          (message.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200')
        }>
          {message.text}
        </div>
      )}

      {/* Two-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        {/* Left: Editor */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-gray-700">HTML Template</label>
            {hasUnsavedChanges && (
              <span className="inline-flex items-center gap-1 text-xs text-amber-600 font-medium">
                <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: '#d97706', display: 'inline-block' }}></span>
                Unsaved changes
              </span>
            )}
          </div>
          <textarea
            ref={textareaRef}
            value={bodyHtml}
            onChange={e => setBodyHtml(e.target.value)}
            style={{
              width: '100%',
              height: '400px',
              fontFamily: 'monospace',
              fontSize: '12px',
              lineHeight: '1.5',
              padding: '12px',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              resize: 'vertical',
              tabSize: 2,
            }}
            spellCheck={false}
          />

          {/* Action buttons */}
          <div className="flex items-center gap-2 mt-3">
            <button
              onClick={handlePreview}
              disabled={previewing}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            >
              {previewing ? 'Loading...' : 'Preview'}
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !hasUnsavedChanges}
              className={
                'px-4 py-2 text-sm font-medium rounded-md ' +
                (hasUnsavedChanges
                  ? 'text-white bg-blue-600 hover:bg-blue-700'
                  : 'text-gray-400 bg-gray-100 cursor-not-allowed')
              }
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => setShowResetConfirm(true)}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium text-red-600 bg-white border border-red-300 rounded-md hover:bg-red-50"
            >
              Reset to Default
            </button>
          </div>

          {/* Available Variables */}
          <div className="mt-4">
            <h4 className="text-sm font-medium text-gray-700 mb-2">Available Variables</h4>
            <p className="text-xs text-gray-500 mb-2">Click a variable to insert it at cursor position.</p>
            <div className="flex flex-wrap gap-1.5">
              {variables.map(v => (
                <button
                  key={v.key}
                  onClick={() => insertVariable(v.key)}
                  title={v.description}
                  className="px-2 py-1 text-xs font-mono bg-gray-100 text-gray-700 border border-gray-200 rounded hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700"
                >
                  {'{{' + v.key + '}}'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right: Preview */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-gray-700">Preview</label>
            <span className="text-xs text-gray-400">Preview uses sample data</span>
          </div>
          <div
            style={{
              height: '400px',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              overflow: 'auto',
              backgroundColor: '#fff',
              padding: '16px',
            }}
          >
            {previewHtml ? (
              <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                Click "Preview" to see rendered template
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Reset confirmation modal */}
      {showResetConfirm && (
        <div style={{
          position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
          <div style={{
            backgroundColor: '#fff', borderRadius: '8px', padding: '24px',
            maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.15)',
          }}>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Reset Template</h3>
            <p className="text-sm text-gray-600 mb-4">
              Reset the email template to the default? Your current customizations will be lost.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowResetConfirm(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleReset}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700"
              >
                Reset to Default
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default EmailTemplateEditor
