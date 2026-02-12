import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api'
import PreflightBanner from '../components/PreflightBanner'
import PdfZoneViewer from '../components/PdfZoneViewer'
import ExportPreviewModal from '../components/ExportPreviewModal'

/**
 * Format a field key into a human-readable label.
 * Converts snake_case to Title Case.
 */
function _formatFieldLabel(key) {
  if (!key) return ''
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase())
}

/**
 * Review & Training Page
 *
 * This page allows users to:
 * 1. Review extracted fields and correct errors
 * 2. Submit corrections for training the extraction system
 * 3. Optionally export to Central Dispatch
 *
 * User corrections are saved and used to improve future extractions
 * for the same auction type.
 */
function Review() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // Mode: 'training' (from Test Lab) or 'production' (from Documents)
  // Training mode only if explicitly set via URL param
  const isTrainingMode = searchParams.get('mode') === 'training'

  const [run, setRun] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [warning, setWarning] = useState(null)  // For unmatched fields warning

  // PDF viewer state
  const [showPdf, setShowPdf] = useState(true)
  const [pdfUrl, setPdfUrl] = useState(null)
  const [zones, setZones] = useState([])

  // Highlighted field for evidence display (M3.P2.2)
  const [highlightedField, setHighlightedField] = useState(null)

  // Field values and status
  const [fields, setFields] = useState({})

  // Warehouses for delivery destination
  const [warehouses, setWarehouses] = useState([])
  const [selectedWarehouse, setSelectedWarehouse] = useState('')

  // Market Intelligence Pricing
  const [pricing, setPricing] = useState(null)
  const [pricingLoading, setPricingLoading] = useState(false)
  const [urgency, setUrgency] = useState('STANDARD')
  const [finalPrice, setFinalPrice] = useState('')

  // Export flow state
  const [showExportModal, setShowExportModal] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState(null) // {cd_listing_id, status}
  const [exportError, setExportError] = useState(null)

  // Production mode fields
  const [loadSpecificTerms, setLoadSpecificTerms] = useState('')
  const [transportSpecialInstructions, setTransportSpecialInstructions] = useState('')

  // Load pricing recommendation
  const loadPricing = useCallback(async (urg) => {
    if (!runId) return
    setPricingLoading(true)
    try {
      const data = await api.getFullPricing(runId, urg || urgency)
      setPricing(data)
    } catch (err) {
      console.error('Failed to load full pricing, falling back:', err)
      // Fallback to existing endpoint
      try {
        const fallback = await api.getPricingRecommendation(runId)
        setPricing(fallback)
      } catch (err2) {
        console.error('Pricing fallback also failed:', err2)
      }
    } finally {
      setPricingLoading(false)
    }
  }, [runId, urgency])

  // Generate Load-Specific Terms template based on auction and warehouse
  const generateLoadSpecificTerms = useCallback((auctionType, warehouseName) => {
    const auctionName = auctionType?.toUpperCase() || 'AUCTION'
    const whName = warehouseName || 'WAREHOUSE'
    return `TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - ${auctionName}, Delivery - ${whName}`
  }, [])

  // Load warehouses
  const loadWarehouses = useCallback(async () => {
    try {
      const data = await api.listWarehouses()
      setWarehouses(data.items || [])
      const defaultWh = (data.items || []).find(w => w.is_default)
      if (defaultWh) {
        setSelectedWarehouse(defaultWh.id.toString())
        // Set transport special instructions from warehouse
        setTransportSpecialInstructions(defaultWh.transport_special_instructions || defaultWh.hours || '')
      } else if (data.items?.length > 0) {
        setSelectedWarehouse(data.items[0].id.toString())
        setTransportSpecialInstructions(data.items[0].transport_special_instructions || data.items[0].hours || '')
      }
    } catch (err) {
      console.error('Failed to load warehouses:', err)
    }
  }, [])

  // Fetch run and review items
  const fetchData = useCallback(async () => {
    if (!runId) return

    setLoading(true)
    setError(null)
    try {
      const runData = await api.getExtraction(runId)
      setRun(runData.run)

      if (runData.run?.document_id) {
        setPdfUrl(`/api/documents/${runData.run.document_id}/file`)
      }

      const itemsData = await api.getReviewItems(runId)
      setItems(itemsData.items || [])

      // Initialize field values with enriched metadata from API
      const initialFields = {}
      for (const item of (itemsData.items || [])) {
        const fieldKey = item.source_key || item.cd_key
        initialFields[fieldKey] = {
          id: item.id,
          key: fieldKey,
          label: item.display_name || _formatFieldLabel(fieldKey),
          predicted: item.predicted_value || '',
          corrected: item.corrected_value || item.predicted_value || '',
          confidence: item.confidence,
          cdKey: item.cd_key,
          status: item.is_match_ok ? 'correct' : 'review', // 'correct', 'corrected', 'review'
          export: item.export_field !== false,
          section: item.section || 'additional',  // UI section for grouping
          fieldType: item.field_type || 'text',   // Input type
          required: item.required || false,        // Required for CD export
        }
      }
      setFields(initialFields)

      await loadWarehouses()
      await loadPricing()

      // Set initial Load-Specific Terms for production mode
      if (!isTrainingMode && runData.run?.auction_type_code) {
        setLoadSpecificTerms(generateLoadSpecificTerms(runData.run.auction_type_code, null))
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [runId, loadWarehouses, loadPricing, isTrainingMode, generateLoadSpecificTerms])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Load zones for the auction type
  useEffect(() => {
    if (!run?.auction_type_id) return

    async function loadZones() {
      try {
        // Get auction type code from ID
        const auctionTypes = await api.listAuctionTypes()
        const auctionType = auctionTypes.items?.find(at => at.id === run.auction_type_id)
        if (!auctionType) {
          setZones([])
          return
        }

        // Get templates for this auction type
        const templates = await api.listZoneTemplates({ auction_type: auctionType.code })
        if (templates.items?.length > 0) {
          // Use the first active template
          const template = templates.items[0]
          // Convert zone fields to simple format for display
          const displayZones = (template.zones || []).map(zone => ({
            ...zone,
            x0: zone.x0,
            y0: zone.y0,
            x1: zone.x1,
            y1: zone.y1,
            name: zone.name,
            fields: (zone.fields || []).map(f => typeof f === 'string' ? f : f.key),
          }))
          setZones(displayZones)
        } else {
          setZones([])
        }
      } catch (err) {
        console.error('Failed to load zones:', err)
        setZones([])
      }
    }

    loadZones()
  }, [run?.auction_type_id])

  // Update field value
  function updateField(key, value) {
    setFields((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        corrected: value,
        status: value !== prev[key].predicted ? 'corrected' : (prev[key].predicted ? 'correct' : 'review'),
      },
    }))
  }

  // Mark field as correct (accept prediction)
  function acceptPrediction(key) {
    setFields((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        corrected: prev[key].predicted,
        status: 'correct',
      },
    }))
  }

  // Toggle export for field
  function toggleExport(key) {
    setFields((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        export: !prev[key].export,
      },
    }))
  }

  // Handle warehouse change - update transport instructions and load terms
  function handleWarehouseChange(warehouseId) {
    setSelectedWarehouse(warehouseId)
    const wh = warehouses.find(w => w.id.toString() === warehouseId)
    if (wh) {
      // Update transport special instructions from warehouse
      setTransportSpecialInstructions(wh.transport_special_instructions || wh.hours || '')
      // Update load-specific terms with warehouse name
      if (run?.auction_type_code) {
        setLoadSpecificTerms(generateLoadSpecificTerms(run.auction_type_code, wh.name))
      }
    }
  }

  // Submit for training
  async function handleSubmitTraining() {
    setSaving(true)
    setError(null)
    setSuccess(null)
    setWarning(null)

    try {
      // Prepare corrections for training API
      const corrections = Object.values(fields).map(f => ({
        field_key: f.key,
        predicted_value: f.predicted || null,
        corrected_value: f.corrected || null,
        was_correct: f.status === 'correct' && f.predicted === f.corrected,
      }))

      // Submit to training API
      const trainingResult = await fetch('/api/training/submit-corrections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          extraction_run_id: parseInt(runId),
          corrections: corrections,
          mark_as_validated: true,
          stay_in_training: true,
        }),
      })

      if (!trainingResult.ok) {
        const err = await trainingResult.json()
        throw new Error(err.detail || 'Failed to save training data')
      }

      const result = await trainingResult.json()

      // Build success message from learning summary
      let successMsg = result.message || `Training data saved! ${result.saved_count} corrections recorded.`
      let unmatchedWarning = null
      const ls = result.learning_summary
      if (ls) {
        const parts = []
        if (ls.rules_created > 0) {
          parts.push(`${ls.rules_created} new pattern${ls.rules_created > 1 ? 's' : ''} learned`)
        }
        if (ls.rules_updated > 0) {
          parts.push(`${ls.rules_updated} pattern${ls.rules_updated > 1 ? 's' : ''} improved`)
        }
        if (ls.fields_improved && ls.fields_improved.length > 0) {
          const fields = ls.fields_improved.slice(0, 3).join(', ')
          parts.push(`confidence improved for: ${fields}`)
        }
        if (parts.length > 0) {
          successMsg = `${result.saved_count} corrections saved. ${parts.join('. ')}.`
        }
        // Warn about unmatched fields (value not found in document text)
        if (ls.unmatched_fields && ls.unmatched_fields.length > 0) {
          const unmatchedList = ls.unmatched_fields.slice(0, 3).join(', ')
          unmatchedWarning = `Note: Could not learn patterns for ${unmatchedList}${ls.unmatched_fields.length > 3 ? ` (+${ls.unmatched_fields.length - 3} more)` : ''} - values not found in document text. Try using values exactly as they appear in the PDF.`
        }
      }

      // Also submit the review to update run status
      const itemsToSubmit = Object.values(fields).map(f => ({
        item_id: f.id,
        corrected_value: f.corrected || '',
        is_match_ok: f.status === 'correct' || f.status === 'corrected',
        export_field: f.export,
      }))

      // Apply warehouse if selected
      if (selectedWarehouse) {
        const wh = warehouses.find(w => w.id.toString() === selectedWarehouse)
        if (wh) {
          const deliveryMappings = {
            'delivery_name': wh.name,
            'delivery_address': wh.address,
            'delivery_city': wh.city,
            'delivery_state': wh.state,
            'delivery_zip': wh.zip_code,
            'delivery_phone': wh.contact?.phone || '',
            'delivery_contact': wh.contact?.notes || '',
            'transport_special_instructions': wh.requirements?.special_instructions || '',
          }
          for (const item of itemsToSubmit) {
            const fieldData = Object.values(fields).find(f => f.id === item.item_id)
            if (fieldData && deliveryMappings[fieldData.key]) {
              item.corrected_value = deliveryMappings[fieldData.key]
            }
          }
        }
      }

      await api.submitReview({
        run_id: parseInt(runId),
        items: itemsToSubmit,
        warehouse_id: selectedWarehouse ? parseInt(selectedWarehouse) : null,
      })

      setSuccess(successMsg)
      if (unmatchedWarning) {
        setWarning(unmatchedWarning)
      }

      // Stay on page longer to show learning feedback, then go to test lab
      setTimeout(() => {
        navigate('/test-lab')
      }, unmatchedWarning ? 5000 : 3000)  // Extra time if there's a warning

    } catch (err) {
      setError(`Failed to submit: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Submit for production export
  async function handleSubmitProduction() {
    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      // Prepare items with all fields
      const itemsToSubmit = Object.values(fields).map(f => ({
        item_id: f.id,
        corrected_value: f.corrected || '',
        is_match_ok: f.status === 'correct' || f.status === 'corrected',
        export_field: f.export,
      }))

      // Apply warehouse data if selected
      const wh = warehouses.find(w => w.id.toString() === selectedWarehouse)
      if (wh) {
        const deliveryMappings = {
          'delivery_name': wh.name,
          'delivery_address': wh.address,
          'delivery_city': wh.city,
          'delivery_state': wh.state,
          'delivery_zip': wh.zip_code,
          'delivery_phone': wh.phone || '',
          'delivery_contact': wh.contact_name || '',
          'transport_special_instructions': transportSpecialInstructions,
          'load_specific_terms': loadSpecificTerms,
        }
        for (const item of itemsToSubmit) {
          const fieldData = Object.values(fields).find(f => f.id === item.item_id)
          if (fieldData && deliveryMappings[fieldData.key]) {
            item.corrected_value = deliveryMappings[fieldData.key]
          }
        }
      }

      // Submit review with production flag
      await api.submitReview({
        run_id: parseInt(runId),
        items: itemsToSubmit,
        warehouse_id: selectedWarehouse ? parseInt(selectedWarehouse) : null,
        mark_for_export: true,
        load_specific_terms: loadSpecificTerms,
        transport_special_instructions: transportSpecialInstructions,
      })

      setSuccess('Document approved for export to Central Dispatch!')

      // Navigate back to Documents after short delay
      setTimeout(() => {
        navigate('/')
      }, 2000)

    } catch (err) {
      setError(`Failed to approve: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Quick actions
  function markAllCorrect() {
    const updated = {}
    Object.keys(fields).forEach(key => {
      updated[key] = {
        ...fields[key],
        corrected: fields[key].predicted || fields[key].corrected,
        status: fields[key].predicted ? 'correct' : 'review',
      }
    })
    setFields(updated)
  }

  // Handle urgency change
  function handleUrgencyChange(newUrgency) {
    setUrgency(newUrgency)
    loadPricing(newUrgency)
  }

  // Handle CD export execution
  async function handleExport(result) {
    if (result?.exported_count > 0 || result?.posted > 0) {
      const listingId = result?.previews?.[0]?.cd_listing_id || result?.cd_listing_id || 'unknown'
      setExportResult({ cd_listing_id: listingId, status: 'exported' })
      setSuccess(`Exported! Listing ID: ${listingId}`)
      setShowExportModal(false)
    } else if (result?.status === 'preview') {
      // Dry run succeeded
      setShowExportModal(false)
    }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading extraction data...</p>
        </div>
      </div>
    )
  }

  if (!run) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <h2 className="text-lg font-medium text-red-800 mb-2">Extraction Not Found</h2>
          <p className="text-red-600 mb-4">The requested extraction run could not be found.</p>
          <button onClick={() => navigate(isTrainingMode ? '/test-lab' : '/')} className="btn btn-primary">
            {isTrainingMode ? 'Back to Test Lab' : 'Back to Documents'}
          </button>
        </div>
      </div>
    )
  }

  const fieldList = Object.values(fields)
  const correctCount = fieldList.filter(f => f.status === 'correct' || f.status === 'corrected').length
  const needsReviewCount = fieldList.filter(f => f.status === 'review').length

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-xl font-bold text-gray-900">
              {isTrainingMode ? 'Review & Train' : 'Review for Export'}
            </h1>
            <p className="text-sm text-gray-500">
              {run.document_filename} • {run.auction_type_code}
              {!isTrainingMode && <span className="ml-2 text-primary-600 font-medium">→ Central Dispatch</span>}
            </p>
          </div>
          <div className="flex items-center space-x-3">
            <span className={`px-3 py-1 rounded-full text-sm font-medium ${
              run.status === 'needs_review' ? 'bg-yellow-100 text-yellow-800' :
              run.status === 'approved' ? 'bg-green-100 text-green-800' :
              run.status === 'failed' ? 'bg-red-100 text-red-800' :
              'bg-gray-100 text-gray-800'
            }`}>
              {run.status === 'needs_review' ? 'Needs Review' : run.status}
            </span>

            {pdfUrl && (
              <button
                onClick={() => setShowPdf(!showPdf)}
                className="btn btn-secondary text-sm"
              >
                {showPdf ? 'Hide PDF' : 'Show PDF'}
              </button>
            )}

            <button
              onClick={() => navigate(isTrainingMode ? '/test-lab' : '/')}
              className="btn btn-secondary text-sm"
            >
              Cancel
            </button>

            {isTrainingMode ? (
              <button
                onClick={handleSubmitTraining}
                className="btn btn-primary"
                disabled={saving}
              >
                {saving ? 'Saving...' : 'Save & Train'}
              </button>
            ) : (
              <button
                onClick={handleSubmitProduction}
                className="btn btn-primary bg-green-600 hover:bg-green-700"
                disabled={saving}
              >
                {saving ? 'Approving...' : 'Approve for Export'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="mx-6 mt-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}
      {success && (
        <div className="mx-6 mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center">
            <svg className="w-5 h-5 text-green-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="font-medium text-green-800">
              {isTrainingMode ? 'Training Updated!' : 'Approved for Export!'}
            </span>
          </div>
          <p className="text-green-700 mt-1 ml-7">{success}</p>
          <p className="text-green-600 text-sm mt-2 ml-7">
            Redirecting to {isTrainingMode ? 'Test Lab' : 'Documents'}...
          </p>
        </div>
      )}
      {warning && (
        <div className="mx-6 mt-2 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
          <div className="flex items-start">
            <svg className="w-5 h-5 text-yellow-500 mr-2 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <span className="font-medium text-yellow-800">Learning Limited</span>
              <p className="text-yellow-700 text-sm mt-1">{warning}</p>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="p-6">
        <div className={`flex gap-6 ${showPdf && pdfUrl ? '' : ''}`}>
          {/* PDF Viewer with Zone Overlay */}
          {showPdf && pdfUrl && (
            <div className="w-1/2 flex-shrink-0 sticky top-6">
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                <div className="px-4 py-2 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                  <span className="font-medium text-sm text-gray-700">
                    Original Document
                    {zones.length > 0 && (
                      <span className="ml-2 text-xs text-gray-500">
                        ({zones.length} zones)
                      </span>
                    )}
                  </span>
                  <a
                    href={pdfUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary-600 hover:text-primary-800"
                  >
                    Open in new tab
                  </a>
                </div>
                <PdfZoneViewer
                  pdfUrl={pdfUrl}
                  zones={zones}
                  selectedZoneIdx={null}
                  editMode={false}
                  height={600}
                  initialScale={1.0}
                />
              </div>
            </div>
          )}

          {/* Fields Panel */}
          <div className={showPdf && pdfUrl ? 'w-1/2' : 'w-full'}>
            {/* Preflight Banner (M3.P2.3) */}
            <PreflightBanner
              runId={parseInt(runId)}
              onIssueClick={(fieldKey) => setHighlightedField(fieldKey)}
              mode={isTrainingMode ? 'training' : 'production'}
              warehouseId={selectedWarehouse ? parseInt(selectedWarehouse) : null}
            />

            {/* Progress Bar */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-medium text-gray-700">Review Progress</span>
                <span className="text-sm text-gray-500">
                  {correctCount} of {fieldList.length} fields reviewed
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-green-500 h-2 rounded-full transition-all"
                  style={{ width: `${(correctCount / Math.max(fieldList.length, 1)) * 100}%` }}
                ></div>
              </div>
              {needsReviewCount > 0 && (
                <p className="text-xs text-orange-600 mt-2">
                  {needsReviewCount} fields need your review
                </p>
              )}
            </div>

            {/* Warehouse Selection */}
            {warehouses.length > 0 && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Delivery Destination
                </label>
                <select
                  value={selectedWarehouse}
                  onChange={(e) => handleWarehouseChange(e.target.value)}
                  className="form-select w-full"
                >
                  <option value="">-- Select Warehouse --</option>
                  {warehouses.map((wh) => (
                    <option key={wh.id} value={wh.id}>
                      {wh.name} ({wh.city}, {wh.state})
                    </option>
                  ))}
                </select>

                {/* Show selected warehouse delivery details */}
                {selectedWarehouse && (() => {
                  const wh = warehouses.find(w => w.id.toString() === selectedWarehouse)
                  if (!wh) return null
                  return (
                    <div className="mt-3 p-3 bg-gray-50 rounded border border-gray-200">
                      <div className="text-xs font-medium text-gray-500 mb-2">Delivery Address (from warehouse)</div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <span className="text-gray-500">Name: </span>
                          <span className="font-medium">{wh.name}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">Phone: </span>
                          <span className="font-medium">{wh.phone || '-'}</span>
                        </div>
                        <div className="col-span-2">
                          <span className="text-gray-500">Address: </span>
                          <span className="font-medium">{wh.address || '-'}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">City: </span>
                          <span className="font-medium">{wh.city || '-'}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">State: </span>
                          <span className="font-medium">{wh.state || '-'}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">ZIP: </span>
                          <span className="font-medium">{wh.zip_code || '-'}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">Contact: </span>
                          <span className="font-medium">{wh.contact_name || '-'}</span>
                        </div>
                      </div>
                    </div>
                  )
                })()}
              </div>
            )}

            {/* Production Mode: CD Export Fields */}
            {!isTrainingMode && (
              <div className="bg-blue-50 rounded-lg shadow-sm border border-blue-200 p-4 mb-4">
                <h3 className="text-sm font-medium text-blue-900 mb-3 flex items-center">
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Central Dispatch Export Fields
                </h3>

                {/* Load-Specific Terms */}
                <div className="mb-4">
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Load-Specific Terms
                    <span className="text-gray-400 ml-1">(payment/pickup info)</span>
                  </label>
                  <textarea
                    value={loadSpecificTerms}
                    onChange={(e) => setLoadSpecificTerms(e.target.value)}
                    rows={2}
                    className="form-textarea w-full text-sm"
                    placeholder="TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY)..."
                  />
                </div>

                {/* Transport Special Instructions */}
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Transport Special Instructions
                    <span className="text-gray-400 ml-1">(warehouse hours/requirements)</span>
                  </label>
                  <textarea
                    value={transportSpecialInstructions}
                    onChange={(e) => setTransportSpecialInstructions(e.target.value)}
                    rows={2}
                    className="form-textarea w-full text-sm"
                    placeholder="Mon-Fri 8am-5pm, call ahead..."
                  />
                </div>
              </div>
            )}

            {/* Market Intelligence Pricing */}
            {pricingLoading && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
                <div className="flex items-center text-gray-500">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600 mr-2"></div>
                  <span className="text-sm">Loading pricing recommendation...</span>
                </div>
              </div>
            )}
            {pricing && !pricingLoading && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
                {/* Header with source badge */}
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h3 className="text-sm font-medium text-gray-700">Pricing</h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {pricing.pickup_location && pricing.delivery_location
                        ? `${pricing.pickup_location} → ${pricing.delivery_location}`
                        : 'Based on route and vehicle'}
                      {pricing.distance_miles > 0 && ` (${Math.round(pricing.distance_miles)} mi)`}
                    </p>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    pricing.source === 'CD_MARKET_INTELLIGENCE' ? 'bg-green-100 text-green-800' :
                    pricing.source === 'USER_OVERRIDE' ? 'bg-blue-100 text-blue-800' :
                    pricing.price_source === 'market_intelligence' ? 'bg-green-100 text-green-800' :
                    'bg-gray-100 text-gray-600'
                  }`}>
                    {pricing.source === 'CD_MARKET_INTELLIGENCE' || pricing.price_source === 'market_intelligence'
                      ? `CD Market Intelligence (${pricing.data_points || 0} data points)`
                      : pricing.source === 'MANUAL_REQUIRED' || pricing.price_source === 'manual_required'
                        ? 'Manual Required'
                        : pricing.source || pricing.price_source || 'Default'}
                  </span>
                </div>

                {/* Source is CD_MARKET_INTELLIGENCE — show full market data */}
                {(pricing.source === 'CD_MARKET_INTELLIGENCE' || pricing.price_source === 'market_intelligence') && (
                  <>
                    {/* Market Range */}
                    {(pricing.avg_dispatch || pricing.avg_listing) && (
                      <div className="grid grid-cols-3 gap-3 mb-3">
                        <div className="text-center p-2 bg-gray-50 rounded">
                          <div className="text-xs text-gray-500">Avg Dispatch</div>
                          <div className="text-sm font-bold text-gray-900">${pricing.avg_dispatch?.toFixed(0) || '---'}</div>
                        </div>
                        <div className="text-center p-2 bg-gray-50 rounded">
                          <div className="text-xs text-gray-500">Avg Listing</div>
                          <div className="text-sm font-bold text-gray-900">${pricing.avg_listing?.toFixed(0) || '---'}</div>
                        </div>
                        <div className="text-center p-2 bg-gray-50 rounded">
                          <div className="text-xs text-gray-500">Spread</div>
                          <div className="text-sm font-bold text-gray-900">${pricing.spread?.toFixed(0) || '---'}</div>
                        </div>
                      </div>
                    )}

                    {/* Visual Price Bar */}
                    {pricing.floor != null && pricing.ceiling != null && pricing.suggested_price != null && (
                      <div className="mb-3">
                        <div className="relative h-8 bg-gray-100 rounded-full overflow-hidden">
                          {/* Floor to Ceiling range bar */}
                          <div className="absolute inset-0 flex items-center px-2">
                            <div className="w-full relative">
                              {/* Bar background */}
                              <div className="h-2 bg-gradient-to-r from-red-200 via-green-200 to-red-200 rounded-full"></div>
                              {/* Avg dispatch marker */}
                              {pricing.avg_dispatch != null && pricing.ceiling > pricing.floor && (
                                <div
                                  className="absolute top-1/2 -translate-y-1/2 w-1 h-4 bg-blue-500 rounded"
                                  style={{ left: `${Math.min(100, Math.max(0, ((pricing.avg_dispatch - pricing.floor) / (pricing.ceiling - pricing.floor)) * 100))}%` }}
                                  title={`Avg Dispatch: $${pricing.avg_dispatch.toFixed(0)}`}
                                />
                              )}
                              {/* Recommended price marker (star) */}
                              {pricing.ceiling > pricing.floor && (
                                <div
                                  className="absolute -top-1 text-yellow-500 text-sm"
                                  style={{ left: `${Math.min(100, Math.max(0, ((pricing.suggested_price - pricing.floor) / (pricing.ceiling - pricing.floor)) * 100))}%`, transform: 'translateX(-50%)' }}
                                  title={`Recommended: $${pricing.suggested_price.toFixed(0)}`}
                                >
                                  &#9733;
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
                          <span>${pricing.floor?.toFixed(0)}</span>
                          <span>${pricing.ceiling?.toFixed(0)}</span>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {/* MANUAL_REQUIRED — highlight that price is needed */}
                {(pricing.source === 'MANUAL_REQUIRED' || pricing.price_source === 'manual_required') && (
                  <div className="mb-3 p-3 bg-yellow-50 border border-yellow-200 rounded">
                    <p className="text-sm text-yellow-800">
                      Market data unavailable. Enter a price below.
                    </p>
                    {pricing.warnings?.length > 0 && (
                      <p className="text-xs text-yellow-600 mt-1">{pricing.warnings[0]}</p>
                    )}
                  </div>
                )}

                {/* Recommended Price + Urgency */}
                <div className="flex items-end gap-4 mb-3">
                  <div className="flex-1">
                    <div className="text-xs text-gray-500 mb-1">Recommended</div>
                    <div className="text-2xl font-bold text-gray-900">
                      ${pricing.suggested_price?.toFixed(2) || '---'}
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Urgency</label>
                    <select
                      value={urgency}
                      onChange={e => handleUrgencyChange(e.target.value)}
                      className="form-select text-sm"
                    >
                      <option value="STANDARD">Standard (1.0x)</option>
                      <option value="PRIORITY">Priority (1.12x)</option>
                      <option value="URGENT">Urgent (1.25x)</option>
                    </select>
                  </div>
                </div>

                {/* Final Price Override */}
                <div className="mb-3">
                  <label className="text-xs text-gray-500 block mb-1">Final Price</label>
                  <input
                    type="number"
                    value={finalPrice}
                    onChange={e => setFinalPrice(e.target.value)}
                    placeholder={pricing.suggested_price ? `Leave empty to use recommended $${pricing.suggested_price.toFixed(0)}` : 'Enter price'}
                    className={`form-input w-full text-sm ${
                      (pricing.source === 'MANUAL_REQUIRED' || pricing.price_source === 'manual_required') && !finalPrice
                        ? 'border-red-300 bg-red-50' : ''
                    }`}
                    step="0.01"
                    min="0"
                  />
                </div>

                {/* Warnings */}
                {pricing.warnings?.length > 0 && (pricing.source !== 'MANUAL_REQUIRED' && pricing.price_source !== 'manual_required') && (
                  <div className="space-y-1">
                    {pricing.warnings.map((w, i) => (
                      <p key={i} className="text-xs text-yellow-600">{w}</p>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Export Flow Section (Production mode only) */}
            {!isTrainingMode && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
                {exportResult ? (
                  /* Post-export state */
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
                  /* Pre-export state */
                  <div>
                    <h3 className="text-sm font-medium text-gray-700 mb-3">Export to Central Dispatch</h3>
                    {exportError && (
                      <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                        <p className="font-medium">Export failed</p>
                        <p>{exportError}</p>
                        <p className="text-xs mt-1 text-red-500">Check that all required fields are filled and CD API credentials are configured in Settings.</p>
                      </div>
                    )}
                    <div className="flex space-x-3">
                      <button
                        onClick={() => setShowExportModal(true)}
                        disabled={exporting}
                        className="btn btn-primary bg-green-600 hover:bg-green-700"
                      >
                        {exporting ? 'Exporting...' : 'Export to CD'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Failed Extraction Notice */}
            {run.status === 'failed' && (
              <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-4">
                <h3 className="font-medium text-orange-800 mb-1">Manual Entry Required</h3>
                <p className="text-sm text-orange-700">
                  Automatic extraction failed. Enter values manually - your corrections will train the system.
                </p>
              </div>
            )}

            {/* Fields List */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200 flex justify-between items-center">
                <div className="flex items-center space-x-2">
                  <h2 className="font-medium text-gray-900">Extracted Fields</h2>
                  {run?.outputs?.extraction_method && (
                    <span className={
                      'text-xs px-2 py-0.5 rounded-full font-medium ' +
                      (run.outputs.extraction_method === 'haiku'
                        ? 'bg-blue-100 text-blue-700'
                        : run.outputs.extraction_method === 'zone_fallback'
                        ? 'bg-yellow-100 text-yellow-700'
                        : 'bg-gray-100 text-gray-600')
                    }>
                      {run.outputs.extraction_method === 'haiku' ? 'Claude Haiku'
                        : run.outputs.extraction_method === 'zone_fallback' ? 'Zone Fallback'
                        : run.outputs.extraction_method === 'all_failed' ? 'Pattern Only'
                        : run.outputs.extraction_method}
                    </span>
                  )}
                </div>
                <button
                  onClick={markAllCorrect}
                  className="text-xs text-primary-600 hover:text-primary-800"
                >
                  Accept All Predictions
                </button>
              </div>

              <div className="divide-y divide-gray-100 max-h-[calc(100vh-400px)] overflow-y-auto">
                {fieldList.map((field) => (
                  <div
                    key={field.key}
                    className={`p-4 cursor-pointer transition-colors ${
                      field.status === 'correct' ? 'bg-green-50' :
                      field.status === 'corrected' ? 'bg-blue-50' :
                      'bg-white'
                    } ${highlightedField === field.key ? 'ring-2 ring-blue-500 ring-inset' : ''}`}
                    onClick={() => setHighlightedField(highlightedField === field.key ? null : field.key)}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center">
                        <span className="font-medium text-gray-900 text-sm">
                          {field.label}
                        </span>
                        {field.required && (
                          <span className="ml-1 text-red-500 text-xs" title="Required for CD export">*</span>
                        )}
                        <span className="ml-2 text-xs text-gray-400 font-mono">{field.key}</span>
                        {/* Evidence indicator (M3.P2.2) */}
                        {showPdf && (
                          <span
                            className={`ml-2 text-xs ${highlightedField === field.key ? 'text-blue-600' : 'text-gray-400'}`}
                            title="Click to highlight source in PDF"
                          >
                            <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            </svg>
                          </span>
                        )}
                      </div>
                      <div className="flex items-center space-x-2">
                        {/* Source type indicator */}
                        {field.key.startsWith('delivery_') && selectedWarehouse ? (
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700" title="Value from warehouse settings">
                            Warehouse
                          </span>
                        ) : field.predicted ? (
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            field.confidence && field.confidence < 0.6 ? 'bg-orange-100 text-orange-700' : 'bg-gray-100 text-gray-600'
                          }`} title={`Extracted from PDF (${field.confidence ? Math.round(field.confidence * 100) : '?'}% confidence)`}>
                            Extracted
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500" title="Manual entry required">
                            Manual
                          </span>
                        )}

                        {/* Low confidence warning */}
                        {field.confidence && field.confidence < 0.6 && field.predicted && (
                          <span className="text-orange-500" title={`Low confidence: ${Math.round(field.confidence * 100)}%`}>
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                            </svg>
                          </span>
                        )}

                        {/* Status indicator */}
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          field.status === 'correct' ? 'bg-green-100 text-green-800' :
                          field.status === 'corrected' ? 'bg-blue-100 text-blue-800' :
                          'bg-yellow-100 text-yellow-800'
                        }`}>
                          {field.status === 'correct' ? 'Correct' :
                           field.status === 'corrected' ? 'Corrected' :
                           'Review'}
                        </span>

                        {/* Export toggle */}
                        <label className="flex items-center text-xs text-gray-500 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={field.export}
                            onChange={() => toggleExport(field.key)}
                            className="form-checkbox h-3 w-3 mr-1"
                          />
                          Export
                        </label>
                      </div>
                    </div>

                    {/* Predicted value (if different from corrected) */}
                    {field.predicted && field.predicted !== field.corrected && (
                      <div className="mb-2 flex items-center">
                        <span className="text-xs text-gray-500 w-20">Predicted:</span>
                        <span className="text-xs font-mono text-gray-600 line-through">{field.predicted}</span>
                        {field.confidence && (
                          <span className="ml-1 text-xs text-gray-400">({(field.confidence * 100).toFixed(0)}%)</span>
                        )}
                      </div>
                    )}

                    {/* Editable value */}
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={field.corrected}
                        onChange={(e) => updateField(field.key, e.target.value)}
                        className={`form-input flex-1 text-sm ${
                          field.status === 'review' && !field.corrected ? 'border-orange-300 bg-orange-50' : ''
                        }`}
                        placeholder={`Enter ${field.label || field.key}`}
                      />
                      {field.predicted && field.status === 'review' && (
                        <button
                          onClick={() => acceptPrediction(field.key)}
                          className="px-3 py-2 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200"
                        >
                          Accept
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Bottom Actions */}
            <div className="mt-4 bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="flex justify-between items-center">
                <div className="text-sm text-gray-600">
                  <span className="text-green-600 font-medium">{correctCount}</span> correct
                  {fieldList.filter(f => f.status === 'corrected').length > 0 && (
                    <>
                      {' • '}
                      <span className="text-blue-600 font-medium">
                        {fieldList.filter(f => f.status === 'corrected').length}
                      </span> corrected
                    </>
                  )}
                  {needsReviewCount > 0 && (
                    <>
                      {' • '}
                      <span className="text-orange-600 font-medium">{needsReviewCount}</span> need review
                    </>
                  )}
                </div>
                {isTrainingMode ? (
                  <button
                    onClick={handleSubmitTraining}
                    className="btn btn-primary"
                    disabled={saving}
                  >
                    {saving ? 'Saving...' : 'Save & Train'}
                  </button>
                ) : (
                  <button
                    onClick={handleSubmitProduction}
                    className="btn btn-primary bg-green-600 hover:bg-green-700"
                    disabled={saving}
                  >
                    {saving ? 'Approving...' : 'Approve for Export'}
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-500 mt-3">
                {isTrainingMode
                  ? 'Your corrections help train the system to extract similar documents more accurately.'
                  : 'After approval, this listing will be ready for export to Central Dispatch.'
                }
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Export Preview Modal */}
      {showExportModal && (
        <ExportPreviewModal
          extractionId={parseInt(runId)}
          documentId={run?.document_id}
          onClose={() => setShowExportModal(false)}
          onExport={handleExport}
        />
      )}
    </div>
  )
}

export default Review
