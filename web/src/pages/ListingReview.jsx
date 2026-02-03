import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../api'

/**
 * Listing Review & Posting Page - Production Workflow
 *
 * Key features (per ТЗ):
 * 1. ALWAYS shows ALL fields from CD API registry (even if empty)
 * 2. Warehouse selection fills delivery stop + transport notes
 * 3. Production corrections → training ingestion (second channel)
 * 4. Blocking issues validation before posting
 * 5. Single and batch posting support
 */
function ListingReview() {
  const { id } = useParams() // extraction run ID
  const navigate = useNavigate()

  // Loading and error states
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [errorDetails, setErrorDetails] = useState(null)

  // Data
  const [extraction, setExtraction] = useState(null)
  const [document, setDocument] = useState(null)
  const [fieldRegistry, setFieldRegistry] = useState(null)
  const [fields, setFields] = useState({})
  const [originalFields, setOriginalFields] = useState({}) // For tracking corrections
  const [warehouses, setWarehouses] = useState([])
  const [selectedWarehouse, setSelectedWarehouse] = useState(null)

  // Blocking issues
  const [blockingIssues, setBlockingIssues] = useState([])
  const [isReady, setIsReady] = useState(false)

  // Export state
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState(null)
  const [showPayloadPreview, setShowPayloadPreview] = useState(false)
  const [payloadPreview, setPayloadPreview] = useState(null)

  // Track corrections for training
  const [corrections, setCorrections] = useState([])

  // =========================================================================
  // LOAD DATA
  // =========================================================================

  // Load field registry (single source of truth)
  const loadFieldRegistry = useCallback(async () => {
    try {
      const result = await api.getFieldRegistry()
      setFieldRegistry(result)
      return result
    } catch (err) {
      console.error('Failed to load field registry:', err)
      return null
    }
  }, [])

  // Load blocking issues
  const loadBlockingIssues = useCallback(async () => {
    try {
      const result = await api.getBlockingIssues(id)
      setBlockingIssues(result.issues || [])
      setIsReady(result.is_ready)
    } catch (err) {
      console.error('Failed to load blocking issues:', err)
    }
  }, [id])

  // Main data loader
  useEffect(() => {
    async function loadData() {
      setLoading(true)
      setError(null)
      setErrorDetails(null)

      try {
        // Load field registry first
        const registry = await loadFieldRegistry()

        // Load extraction details
        const extResult = await api.getExtraction(id)
        setExtraction(extResult)

        // Parse outputs_json and initialize ALL fields from registry
        let outputs = {}
        if (extResult.outputs_json) {
          outputs = typeof extResult.outputs_json === 'string'
            ? JSON.parse(extResult.outputs_json)
            : extResult.outputs_json
        }

        // Initialize fields from registry (ensures ALL fields are present)
        const initialFields = {}
        if (registry?.sections) {
          Object.values(registry.sections).forEach(section => {
            section.fields.forEach(fieldDef => {
              initialFields[fieldDef.key] = outputs[fieldDef.key] || ''
            })
          })
        }

        // Also include any extra fields from extraction
        Object.keys(outputs).forEach(key => {
          if (!(key in initialFields)) {
            initialFields[key] = outputs[key]
          }
        })

        setFields(initialFields)
        setOriginalFields({ ...initialFields })

        // Load document
        if (extResult.document_id) {
          try {
            const docResult = await api.getDocument(extResult.document_id)
            setDocument(docResult)
          } catch (err) {
            console.error('Failed to load document:', err)
          }
        }

        // Load warehouses
        const whResult = await api.listWarehouses()
        setWarehouses(whResult.items || [])

        // Set selected warehouse if already set
        if (outputs.warehouse_id) {
          const wh = (whResult.items || []).find(w => w.id === parseInt(outputs.warehouse_id))
          if (wh) setSelectedWarehouse(wh)
        }

        // Load blocking issues
        await loadBlockingIssues()
      } catch (err) {
        setError(err.message || 'Failed to load document')
        setErrorDetails({
          endpoint: `/api/extractions/${id}`,
          requestId: err.requestId || null,
          status: err.status || 500,
        })
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [id, loadFieldRegistry, loadBlockingIssues])

  // =========================================================================
  // FIELD HANDLING
  // =========================================================================

  // Update field value and track correction
  function handleFieldChange(key, value) {
    const oldValue = originalFields[key]

    setFields(prev => ({ ...prev, [key]: value }))

    // Track correction if value changed
    if (value !== oldValue) {
      setCorrections(prev => {
        const existing = prev.findIndex(c => c.field_key === key)
        if (existing >= 0) {
          const updated = [...prev]
          updated[existing] = { ...updated[existing], new_value: value }
          return updated
        }
        return [...prev, {
          field_key: key,
          old_value: oldValue || '',
          new_value: value,
        }]
      })
    }
  }

  // Handle warehouse selection - auto-fill delivery fields
  function handleWarehouseSelect(warehouseId) {
    const wh = warehouses.find(w => w.id === parseInt(warehouseId))
    setSelectedWarehouse(wh)

    if (wh) {
      const deliveryFields = {
        warehouse_id: wh.id,
        delivery_name: wh.name || '',
        delivery_address: wh.address || '',
        delivery_city: wh.city || '',
        delivery_state: wh.state || '',
        delivery_zip: wh.zip_code || '',
        delivery_phone: wh.contact?.phone || '',
        delivery_contact: wh.contact?.notes || '',
        transport_special_instructions: wh.requirements?.special_instructions || fields.transport_special_instructions || '',
      }

      setFields(prev => ({ ...prev, ...deliveryFields }))

      // Track warehouse-sourced corrections
      Object.entries(deliveryFields).forEach(([key, value]) => {
        if (value && value !== originalFields[key]) {
          setCorrections(prev => {
            const existing = prev.findIndex(c => c.field_key === key)
            if (existing >= 0) {
              const updated = [...prev]
              updated[existing] = { ...updated[existing], new_value: value }
              return updated
            }
            return [...prev, {
              field_key: key,
              old_value: originalFields[key] || '',
              new_value: value,
              source: 'warehouse',
            }]
          })
        }
      })
    }

    // Recheck blocking issues
    setTimeout(loadBlockingIssues, 100)
  }

  // =========================================================================
  // SAVE & EXPORT
  // =========================================================================

  // Save changes (draft)
  async function handleSave() {
    setSaving(true)
    setError(null)

    try {
      // Update extraction with new field values
      await api.updateExtraction(id, {
        outputs_json: fields,
        status: 'reviewed',
      })

      // Submit production corrections for training (second channel)
      if (corrections.length > 0) {
        await api.submitProductionCorrections({
          run_id: parseInt(id),
          corrections: corrections,
          save_to_extraction: false, // Already saved above
        })
      }

      // Reload extraction
      const extResult = await api.getExtraction(id)
      setExtraction(extResult)
      setOriginalFields({ ...fields })
      setCorrections([])

      // Recheck blocking issues
      await loadBlockingIssues()
    } catch (err) {
      setError(`Save failed: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Preview CD payload
  async function handlePreviewPayload() {
    try {
      // Save first to ensure payload reflects current values
      await api.updateExtraction(id, {
        outputs_json: fields,
      })
      const result = await api.getCDPayloadPreview(id)
      setPayloadPreview(result)
      setShowPayloadPreview(true)
    } catch (err) {
      setError(`Preview failed: ${err.message}`)
    }
  }

  // Export to Central Dispatch
  async function handleExport() {
    // Validate
    if (!selectedWarehouse) {
      setError('Please select a delivery warehouse before posting')
      return
    }

    if (blockingIssues.length > 0) {
      setError(`Cannot post: ${blockingIssues.length} blocking issues`)
      return
    }

    setExporting(true)
    setExportResult(null)

    try {
      // Save first
      await api.updateExtraction(id, {
        outputs_json: fields,
        status: 'approved',
      })

      // Submit production corrections for training
      if (corrections.length > 0) {
        await api.submitProductionCorrections({
          run_id: parseInt(id),
          corrections: corrections,
          save_to_extraction: false,
        })
      }

      // Export
      const result = await api.exportToCentralDispatch(id)
      setExportResult({
        success: true,
        message: 'Successfully posted to Central Dispatch',
        orderId: result.cd_listing_id || result.order_id,
      })

      // Reload extraction
      const extResult = await api.getExtraction(id)
      setExtraction(extResult)
      setCorrections([])
    } catch (err) {
      setExportResult({
        success: false,
        message: err.message || 'Export failed',
      })
    } finally {
      setExporting(false)
    }
  }

  // =========================================================================
  // RENDER HELPERS
  // =========================================================================

  // Get field source for display
  function getFieldSource(key) {
    if (corrections.find(c => c.field_key === key)) {
      return { label: 'User Override', color: 'bg-blue-100 text-blue-800' }
    }
    if (selectedWarehouse && key.startsWith('delivery_')) {
      return { label: 'Warehouse', color: 'bg-green-100 text-green-800' }
    }
    if (originalFields[key]) {
      return { label: 'Extracted', color: 'bg-gray-100 text-gray-600' }
    }
    return { label: 'Empty', color: 'bg-orange-100 text-orange-800' }
  }

  // Render field input
  function renderFieldInput(fieldDef) {
    const value = fields[fieldDef.key] || ''
    const isDisabled = extraction?.status === 'exported'
    const hasIssue = blockingIssues.find(i => i.field === fieldDef.key)
    const source = getFieldSource(fieldDef.key)

    const baseClass = `form-input w-full ${isDisabled ? 'bg-gray-100' : ''} ${
      hasIssue ? 'border-red-300 bg-red-50' : ''
    } ${!value && fieldDef.required ? 'border-orange-300' : ''}`

    const wrapper = (input) => (
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="block text-sm font-medium text-gray-700">
            {fieldDef.label}
            {fieldDef.required && <span className="text-red-500 ml-1">*</span>}
          </label>
          <span className={`text-xs px-1.5 py-0.5 rounded ${source.color}`}>
            {source.label}
          </span>
        </div>
        {input}
        {hasIssue && (
          <p className="text-xs text-red-600 mt-1">{hasIssue.issue}</p>
        )}
        {fieldDef.help_text && !hasIssue && (
          <p className="text-xs text-gray-500 mt-1">{fieldDef.help_text}</p>
        )}
      </div>
    )

    if (fieldDef.field_type === 'select' && fieldDef.options?.length) {
      return wrapper(
        <select
          value={value}
          onChange={(e) => handleFieldChange(fieldDef.key, e.target.value)}
          disabled={isDisabled}
          className={`form-select w-full ${isDisabled ? 'bg-gray-100' : ''}`}
        >
          <option value="">Select...</option>
          {fieldDef.options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      )
    }

    if (fieldDef.field_type === 'textarea') {
      return wrapper(
        <textarea
          value={value}
          onChange={(e) => handleFieldChange(fieldDef.key, e.target.value)}
          disabled={isDisabled}
          className={baseClass}
          rows={3}
        />
      )
    }

    return wrapper(
      <input
        type={fieldDef.field_type === 'number' ? 'number' : fieldDef.field_type === 'date' ? 'date' : 'text'}
        value={value}
        onChange={(e) => handleFieldChange(fieldDef.key, e.target.value)}
        disabled={isDisabled}
        className={baseClass}
        placeholder={fieldDef.extraction_hint || `Enter ${fieldDef.label.toLowerCase()}`}
      />
    )
  }

  // Render section
  function renderSection(sectionKey, sectionData) {
    const sectionLabels = {
      vehicle: 'Vehicle Information',
      pickup: 'Pickup Location',
      delivery: 'Delivery Location',
      pricing: 'Pricing',
      additional: 'Additional Information',
      notes: 'Notes & Special Instructions',
    }

    const sectionIcons = {
      vehicle: '🚗',
      pickup: '📍',
      delivery: '🏭',
      pricing: '💰',
      additional: '📋',
      notes: '📝',
    }

    return (
      <div key={sectionKey} className="bg-white rounded-lg border border-gray-200">
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
          <h2 className="font-medium text-gray-900">
            <span className="mr-2">{sectionIcons[sectionKey]}</span>
            {sectionLabels[sectionKey] || sectionData.label}
          </h2>
          {sectionKey === 'delivery' && selectedWarehouse && (
            <span className="text-xs bg-green-100 text-green-800 px-2 py-1 rounded">
              From Warehouse: {selectedWarehouse.name}
            </span>
          )}
        </div>
        <div className="p-4 space-y-4">
          {sectionData.fields.map((fieldDef) => (
            <div key={fieldDef.key}>
              {renderFieldInput(fieldDef)}
            </div>
          ))}
        </div>
      </div>
    )
  }

  // =========================================================================
  // ERROR & LOADING STATES
  // =========================================================================

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse">
          <div className="h-8 bg-gray-200 rounded w-1/4 mb-4"></div>
          <div className="h-64 bg-gray-200 rounded"></div>
        </div>
      </div>
    )
  }

  if (error && !extraction) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h3 className="text-red-800 font-medium text-lg mb-2">Error Loading Document</h3>
          <p className="text-red-600 mb-4">{error}</p>
          {errorDetails && (
            <div className="bg-red-100 rounded p-3 mb-4 text-sm">
              <p><strong>Endpoint:</strong> {errorDetails.endpoint}</p>
              <p><strong>Status:</strong> {errorDetails.status}</p>
              {errorDetails.requestId && (
                <p><strong>Request ID:</strong> {errorDetails.requestId}</p>
              )}
            </div>
          )}
          <div className="flex gap-3">
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
            >
              Retry
            </button>
            <button
              onClick={() => navigate('/documents')}
              className="px-4 py-2 border border-gray-300 rounded text-gray-700 hover:bg-gray-50"
            >
              Back to Documents
            </button>
          </div>
        </div>
      </div>
    )
  }

  // =========================================================================
  // MAIN RENDER
  // =========================================================================

  const isExported = extraction?.status === 'exported'
  const canExport = !isExported && selectedWarehouse && isReady

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-2">
            <Link to="/documents" className="hover:text-blue-600">&larr; Documents</Link>
            <span>/</span>
            <span>Review & Post</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">
            Review & Post to Central Dispatch
          </h1>
          <div className="flex items-center gap-3 mt-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${
              extraction?.auction_type_code === 'COPART' ? 'bg-blue-100 text-blue-800' :
              extraction?.auction_type_code === 'IAA' ? 'bg-purple-100 text-purple-800' :
              extraction?.auction_type_code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
              'bg-gray-100 text-gray-800'
            }`}>
              {extraction?.auction_type_code}
            </span>
            <span className={`px-2 py-1 rounded text-xs font-medium ${
              extraction?.status === 'exported' ? 'bg-green-100 text-green-800' :
              extraction?.status === 'reviewed' || extraction?.status === 'approved' ? 'bg-blue-100 text-blue-800' :
              extraction?.status === 'needs_review' ? 'bg-yellow-100 text-yellow-800' :
              'bg-gray-100 text-gray-800'
            }`}>
              {extraction?.status === 'exported' ? 'Posted' :
               extraction?.status === 'reviewed' || extraction?.status === 'approved' ? 'Ready to Post' :
               extraction?.status === 'needs_review' ? 'Needs Review' :
               extraction?.status}
            </span>
            {fields.vehicle_lot && (
              <span className="text-sm text-gray-600">
                Lot: <span className="font-medium">{fields.vehicle_lot}</span>
              </span>
            )}
            {corrections.length > 0 && (
              <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                {corrections.length} unsaved correction{corrections.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handlePreviewPayload}
            className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
          >
            Preview Payload
          </button>
          <button
            onClick={handleSave}
            disabled={saving || isExported}
            className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Draft'}
          </button>
          <button
            onClick={handleExport}
            disabled={!canExport || exporting}
            className={`px-4 py-2 rounded-lg font-medium ${
              canExport
                ? 'bg-green-600 text-white hover:bg-green-700'
                : 'bg-gray-200 text-gray-500 cursor-not-allowed'
            }`}
          >
            {exporting ? 'Posting...' : isExported ? 'Already Posted' : 'Post to CD'}
          </button>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {error}
          <button onClick={() => setError(null)} className="ml-4 text-sm underline">Dismiss</button>
        </div>
      )}

      {exportResult && (
        <div className={`mb-6 p-4 rounded-lg ${
          exportResult.success
            ? 'bg-green-50 border border-green-200'
            : 'bg-red-50 border border-red-200'
        }`}>
          <p className={exportResult.success ? 'text-green-800' : 'text-red-800'}>
            {exportResult.message}
            {exportResult.orderId && (
              <span className="ml-2 font-medium">(CD Listing ID: {exportResult.orderId})</span>
            )}
          </p>
        </div>
      )}

      {/* Blocking Issues Alert */}
      {!isExported && blockingIssues.length > 0 && (
        <div className="mb-6 bg-orange-50 border border-orange-200 rounded-lg p-4">
          <h3 className="font-medium text-orange-800 mb-2">
            ⚠️ Blocking Issues ({blockingIssues.length})
          </h3>
          <ul className="list-disc list-inside text-sm text-orange-700 space-y-1">
            {blockingIssues.map((issue, i) => (
              <li key={i}>
                <strong>{issue.field}:</strong> {issue.issue}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warehouse Selection Banner */}
      {!isExported && (
        <div className="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-medium text-blue-800">Delivery Warehouse</h3>
              <p className="text-sm text-blue-700">
                Select warehouse to auto-fill delivery address and transport instructions
              </p>
            </div>
            <select
              value={selectedWarehouse?.id || ''}
              onChange={(e) => handleWarehouseSelect(e.target.value)}
              className="form-select"
            >
              <option value="">Select Warehouse...</option>
              {warehouses.map((wh) => (
                <option key={wh.id} value={wh.id}>
                  {wh.name} - {wh.city}, {wh.state}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Main Content Grid */}
      {fieldRegistry?.sections && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Vehicle */}
          {fieldRegistry.sections.vehicle && renderSection('vehicle', fieldRegistry.sections.vehicle)}

          {/* Pickup */}
          {fieldRegistry.sections.pickup && renderSection('pickup', fieldRegistry.sections.pickup)}

          {/* Delivery */}
          {fieldRegistry.sections.delivery && renderSection('delivery', fieldRegistry.sections.delivery)}

          {/* Pricing */}
          {fieldRegistry.sections.pricing && renderSection('pricing', fieldRegistry.sections.pricing)}

          {/* Additional - Full Width */}
          {fieldRegistry.sections.additional && (
            <div className="lg:col-span-2">
              {renderSection('additional', fieldRegistry.sections.additional)}
            </div>
          )}

          {/* Notes - Full Width */}
          {fieldRegistry.sections.notes && (
            <div className="lg:col-span-2">
              {renderSection('notes', fieldRegistry.sections.notes)}
            </div>
          )}
        </div>
      )}

      {/* Extraction Metadata */}
      <div className="mt-6 bg-gray-50 rounded-lg p-4">
        <h3 className="font-medium text-gray-900 mb-2">Extraction Details</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
          <div>
            <div className="text-gray-500">Run ID</div>
            <div className="font-medium">{extraction?.id}</div>
          </div>
          <div>
            <div className="text-gray-500">Document</div>
            <div className="font-medium truncate">{document?.filename || '-'}</div>
          </div>
          <div>
            <div className="text-gray-500">Status</div>
            <div className="font-medium">{extraction?.status}</div>
          </div>
          <div>
            <div className="text-gray-500">Confidence</div>
            <div className="font-medium">
              {extraction?.extraction_score
                ? `${Math.round(extraction.extraction_score * 100)}%`
                : 'N/A'}
            </div>
          </div>
          <div>
            <div className="text-gray-500">Created</div>
            <div className="font-medium">
              {extraction?.created_at ? new Date(extraction.created_at).toLocaleString() : '-'}
            </div>
          </div>
        </div>
      </div>

      {/* Payload Preview Modal */}
      {showPayloadPreview && payloadPreview && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-3xl w-full mx-4 max-h-[80vh] overflow-auto">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold">Central Dispatch API Payload</h2>
              <button
                onClick={() => setShowPayloadPreview(false)}
                className="text-gray-500 hover:text-gray-700 text-2xl"
              >
                &times;
              </button>
            </div>

            {payloadPreview.validation_errors?.length > 0 && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                <h3 className="font-medium text-red-800 mb-2">Validation Errors</h3>
                <ul className="list-disc list-inside text-sm text-red-700">
                  {payloadPreview.validation_errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mb-4">
              <p className="text-sm text-gray-600 mb-2">
                <strong>Content-Type:</strong>{' '}
                <code className="bg-gray-100 px-1 rounded">application/vnd.coxauto.v2+json</code>
              </p>
              <p className="text-sm text-gray-600">
                <strong>Dispatch ID:</strong>{' '}
                <code className="bg-gray-100 px-1 rounded">{payloadPreview.dispatch_id}</code>
              </p>
            </div>

            <pre className="bg-gray-100 p-4 rounded-lg text-xs overflow-auto max-h-96">
              {JSON.stringify(payloadPreview.payload, null, 2)}
            </pre>

            <div className="mt-4 flex justify-end">
              <button
                onClick={() => setShowPayloadPreview(false)}
                className="btn btn-secondary"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ListingReview
