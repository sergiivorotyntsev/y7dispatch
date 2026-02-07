import { useState, useEffect } from 'react'
import api from '../api'

/**
 * Export Preview Modal - Shows all fields that will be exported to CD
 *
 * Displays:
 * - All fields grouped by source (extracted, constant, warehouse, user_input)
 * - Validation status for each field
 * - Visual indicators for field types
 * - Option to edit before export
 */

const SOURCE_BADGES = {
  extracted: { label: 'Extracted', icon: '📄', bg: 'bg-green-50', text: 'text-green-700', border: 'border-green-200' },
  constant: { label: 'Constant', icon: '🔒', bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  warehouse_ref: { label: 'Warehouse', icon: '🏭', bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
  user_input: { label: 'User Input', icon: '✏️', bg: 'bg-cyan-50', text: 'text-cyan-700', border: 'border-cyan-200' },
  computed: { label: 'Computed', icon: '⚙️', bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200' },
  default: { label: 'Default', icon: '📋', bg: 'bg-gray-50', text: 'text-gray-700', border: 'border-gray-200' },
}

const CATEGORY_STYLES = {
  cd_required: { label: 'Required', bg: 'bg-red-100', text: 'text-red-800' },
  cd_optional: { label: 'Optional', bg: 'bg-blue-100', text: 'text-blue-800' },
  internal: { label: 'Internal', bg: 'bg-gray-100', text: 'text-gray-600' },
}

function FieldRow({ field, value, source, category, isValid, error }) {
  const sourceBadge = SOURCE_BADGES[source] || SOURCE_BADGES.default
  const catStyle = CATEGORY_STYLES[category] || CATEGORY_STYLES.cd_optional

  return (
    <tr className={`${isValid ? '' : 'bg-red-50'}`}>
      <td className="px-3 py-2 text-sm font-medium text-gray-900">
        {field}
        {!isValid && (
          <span className="ml-2 text-xs text-red-600">⚠</span>
        )}
      </td>
      <td className="px-3 py-2">
        <span className={`text-sm ${value ? 'text-gray-900' : 'text-gray-400 italic'}`}>
          {value || '(empty)'}
        </span>
        {error && (
          <div className="text-xs text-red-600 mt-0.5">{error}</div>
        )}
      </td>
      <td className="px-3 py-2">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded ${sourceBadge.bg} ${sourceBadge.text}`}>
          {sourceBadge.icon} {sourceBadge.label}
        </span>
      </td>
      <td className="px-3 py-2">
        <span className={`px-2 py-0.5 text-xs rounded ${catStyle.bg} ${catStyle.text}`}>
          {catStyle.label}
        </span>
      </td>
    </tr>
  )
}

export default function ExportPreviewModal({ extractionId, documentId, onClose, onExport }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [previewData, setPreviewData] = useState(null)
  const [fieldSources, setFieldSources] = useState({})
  const [exporting, setExporting] = useState(false)
  const [view, setView] = useState('table') // 'table' or 'json'

  useEffect(() => {
    loadPreview()
  }, [extractionId, documentId])

  async function loadPreview() {
    setLoading(true)
    setError(null)
    try {
      // Load preview data from API
      const preview = await api.previewCDPayload(extractionId)
      setPreviewData(preview)

      // Try to get field sources from extraction
      try {
        const extraction = await api.getExtraction(extractionId)
        setFieldSources(extraction.field_sources_json || extraction.field_sources || {})
      } catch (e) {
        console.warn('Could not load field sources:', e)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleExport(dryRun = false) {
    setExporting(true)
    try {
      const result = await api.exportToCD([extractionId], dryRun, true)
      if (onExport) {
        onExport(result)
      }
      if (!dryRun && result.posted > 0) {
        onClose()
      }
    } catch (err) {
      setError(`Export failed: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  // Parse fields from preview payload
  const fields = []
  if (previewData?.payload) {
    const payload = previewData.payload

    // Vehicle info
    if (payload.vehicles?.[0]) {
      const v = payload.vehicles[0]
      fields.push({ key: 'vin', value: v.vin, category: 'cd_required' })
      fields.push({ key: 'year', value: v.year, category: 'cd_required' })
      fields.push({ key: 'make', value: v.make, category: 'cd_required' })
      fields.push({ key: 'model', value: v.model, category: 'cd_required' })
      fields.push({ key: 'vehicle_type', value: v.type, category: 'cd_optional' })
      fields.push({ key: 'is_operable', value: v.is_operable?.toString(), category: 'cd_optional' })
    }

    // Origin (pickup)
    if (payload.origin) {
      const o = payload.origin
      fields.push({ key: 'pickup_name', value: o.contact?.name, category: 'cd_optional' })
      fields.push({ key: 'pickup_address', value: o.address?.street, category: 'cd_optional' })
      fields.push({ key: 'pickup_city', value: o.address?.city, category: 'cd_required' })
      fields.push({ key: 'pickup_state', value: o.address?.state, category: 'cd_required' })
      fields.push({ key: 'pickup_zip', value: o.address?.zip, category: 'cd_optional' })
    }

    // Destination (delivery)
    if (payload.destination) {
      const d = payload.destination
      fields.push({ key: 'delivery_name', value: d.contact?.name, category: 'cd_optional' })
      fields.push({ key: 'delivery_address', value: d.address?.street, category: 'cd_optional' })
      fields.push({ key: 'delivery_city', value: d.address?.city, category: 'cd_required' })
      fields.push({ key: 'delivery_state', value: d.address?.state, category: 'cd_required' })
      fields.push({ key: 'delivery_zip', value: d.address?.zip, category: 'cd_optional' })
    }

    // Pricing
    if (payload.pricing) {
      fields.push({ key: 'price', value: payload.pricing.carrier_pay, category: 'cd_optional' })
    }

    // Dates
    if (payload.dates) {
      fields.push({ key: 'available_date', value: payload.dates.available_date, category: 'cd_optional' })
      fields.push({ key: 'pickup_date', value: payload.dates.pickup_date, category: 'cd_optional' })
    }
  }

  // Add source info to fields
  const enrichedFields = fields.map(f => ({
    ...f,
    source: fieldSources[f.key] || 'extracted',
    isValid: f.category !== 'cd_required' || (f.value && f.value !== ''),
  }))

  const validationErrors = previewData?.validation_errors || []
  const isValid = validationErrors.length === 0

  // Count by source
  const sourceCounts = enrichedFields.reduce((acc, f) => {
    acc[f.source] = (acc[f.source] || 0) + 1
    return acc
  }, {})

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-5xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Export Preview
            </h2>
            <p className="text-sm text-gray-500">
              Review all fields before exporting to Central Dispatch
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">
            &times;
          </button>
        </div>

        {/* Source Summary */}
        {!loading && !error && (
          <div className="px-6 py-3 bg-gray-50 border-b flex flex-wrap gap-3">
            {Object.entries(SOURCE_BADGES).map(([key, badge]) => {
              const count = sourceCounts[key] || 0
              if (count === 0) return null
              return (
                <div key={key} className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${badge.bg} ${badge.border} border`}>
                  <span>{badge.icon}</span>
                  <span className={`text-sm font-medium ${badge.text}`}>{badge.label}</span>
                  <span className={`text-xs ${badge.text}`}>({count})</span>
                </div>
              )
            })}
          </div>
        )}

        {/* Validation Status */}
        {!loading && !error && (
          <div className={`px-6 py-3 ${isValid ? 'bg-green-50' : 'bg-red-50'}`}>
            {isValid ? (
              <div className="flex items-center gap-2 text-green-700">
                <span className="text-lg">✅</span>
                <span className="font-medium">All required fields are valid</span>
              </div>
            ) : (
              <div>
                <div className="flex items-center gap-2 text-red-700 mb-2">
                  <span className="text-lg">⚠️</span>
                  <span className="font-medium">Validation errors ({validationErrors.length})</span>
                </div>
                <ul className="list-disc list-inside text-sm text-red-600">
                  {validationErrors.slice(0, 5).map((e, i) => <li key={i}>{e}</li>)}
                  {validationErrors.length > 5 && (
                    <li>...and {validationErrors.length - 5} more</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* View Toggle */}
        {!loading && !error && (
          <div className="px-6 py-2 border-b flex gap-2">
            <button
              onClick={() => setView('table')}
              className={`px-3 py-1 text-sm rounded ${view === 'table' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700'}`}
            >
              Table View
            </button>
            <button
              onClick={() => setView('json')}
              className={`px-3 py-1 text-sm rounded ${view === 'json' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700'}`}
            >
              JSON View
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-auto px-6 py-4">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              <span className="ml-3 text-gray-600">Loading preview...</span>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded p-4 text-red-700">
              <strong>Error:</strong> {error}
            </div>
          )}

          {!loading && !error && view === 'table' && (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Field</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Value</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {enrichedFields.map((f, i) => (
                  <FieldRow
                    key={i}
                    field={f.key}
                    value={f.value}
                    source={f.source}
                    category={f.category}
                    isValid={f.isValid}
                  />
                ))}
              </tbody>
            </table>
          )}

          {!loading && !error && view === 'json' && (
            <pre className="bg-gray-50 border rounded p-4 text-xs font-mono overflow-auto max-h-[50vh] whitespace-pre-wrap">
              {JSON.stringify(previewData?.payload, null, 2)}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t bg-gray-50">
          <button
            onClick={() => navigator.clipboard.writeText(JSON.stringify(previewData?.payload, null, 2))}
            disabled={!previewData?.payload}
            className="px-4 py-2 text-sm border rounded hover:bg-gray-100 disabled:opacity-50"
          >
            Copy JSON
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm border rounded hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={() => handleExport(true)}
              disabled={exporting || !isValid}
              className="px-4 py-2 text-sm bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:opacity-50"
            >
              {exporting ? 'Validating...' : 'Dry Run'}
            </button>
            <button
              onClick={() => handleExport(false)}
              disabled={exporting || !isValid}
              className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              {exporting ? 'Exporting...' : 'Export to CD'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
