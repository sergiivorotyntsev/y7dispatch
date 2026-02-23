import { useState } from 'react'

/**
 * Section 7: Additional Info
 * Load ID (auto, readonly), gate pass, additional vehicle info, load-specific terms, transport instructions, CD App checkbox.
 * Note: Attachments are now displayed in EmailContextPanel (unified view).
 */
function AdditionalInfoSection({
  loadId, setLoadId,
  isApproved, exportResult,
  fields,
  updateField,
  loadSpecificTerms, setLoadSpecificTerms,
  transportSpecialInstructions, setTransportSpecialInstructions,
  requiresInspection, setRequiresInspection,
}) {
  const [copied, setCopied] = useState(false)

  function copyLoadId() {
    if (loadId) {
      navigator.clipboard.writeText(loadId).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      })
    }
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        Additional Info
      </h3>

      {/* Load ID */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Your Load ID
          <span className="ml-1 text-gray-400 font-normal">
            {exportResult ? '(locked after export)' : '(auto-generated, editable)'}
          </span>
        </label>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={loadId || (exportResult ? '' : 'Generating...')}
            onChange={(e) => setLoadId && setLoadId(e.target.value)}
            readOnly={!!exportResult}
            className={`form-input flex-1 text-sm font-mono ${exportResult ? 'bg-gray-100 text-gray-500' : 'bg-white'}`}
          />
          <button
            type="button"
            onClick={copyLoadId}
            className="px-3 py-2 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
            title="Copy to clipboard"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Gate Pass */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">Gate Pass</label>
        <input
          type="text"
          value={fields.gate_pass?.corrected || ''}
          onChange={(e) => updateField('gate_pass', e.target.value)}
          className="form-input w-full text-sm"
          placeholder="Gate pass from email (if available)"
        />
      </div>

      {/* Additional Vehicle Information */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Additional Vehicle Information
          <span className="ml-1 text-gray-400 font-normal">(visible to carrier after dispatch)</span>
        </label>
        <textarea
          value={fields.vehicle_additional_info?.corrected || ''}
          onChange={(e) => updateField('vehicle_additional_info', e.target.value)}
          rows={2}
          className="form-textarea w-full text-sm"
          placeholder="Gate Pass: ABC123, special notes for carrier..."
          maxLength={500}
        />
      </div>

      {/* Load-Specific Terms */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Load-Specific Terms
          <span className="ml-1 text-gray-400 font-normal">(payment/contact info for carrier)</span>
        </label>
        <textarea
          value={loadSpecificTerms}
          onChange={(e) => setLoadSpecificTerms(e.target.value)}
          rows={2}
          className="form-textarea w-full text-sm"
          placeholder="TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY)..."
          maxLength={500}
        />
      </div>

      {/* Transport Special Instructions */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Transport Special Instructions
          <span className="ml-1 text-gray-400 font-normal">(warehouse hours/requirements)</span>
        </label>
        <textarea
          value={transportSpecialInstructions}
          onChange={(e) => setTransportSpecialInstructions(e.target.value)}
          rows={2}
          className="form-textarea w-full text-sm"
          placeholder="Mon-Fri 8am-5pm, call ahead for delivery appointment..."
        />
      </div>

      {/* Request carrier use CD App */}
      <label className="flex items-center space-x-2 cursor-pointer">
        <input
          type="checkbox"
          checked={requiresInspection}
          onChange={(e) => setRequiresInspection(e.target.checked)}
          className="form-checkbox h-4 w-4"
        />
        <span className="text-sm text-gray-700">Request carrier use CD App</span>
      </label>
    </div>
  )
}

export default AdditionalInfoSection
