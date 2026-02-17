import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api'
import PdfZoneViewer from '../components/PdfZoneViewer'
import ExportPreviewModal from '../components/ExportPreviewModal'

// Section components (CD-aligned layout)
import ExtractionInfoBar from '../components/review/ExtractionInfoBar'
import VehicleSection from '../components/review/VehicleSection'
import PickupSection from '../components/review/PickupSection'
import DeliverySection from '../components/review/DeliverySection'
import DatesSection from '../components/review/DatesSection'
import PricingPaymentSection from '../components/review/PricingPaymentSection'
import AdditionalInfoSection from '../components/review/AdditionalInfoSection'
import DocumentDetails from '../components/review/DocumentDetails'
import ExportActions from '../components/review/ExportActions'

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
 * Review & Training Page — CD-Aligned Layout
 *
 * Restructured into 9 sections matching Central Dispatch "Create Listing" form:
 * 1. Extraction Info Bar
 * 2. Vehicle Information
 * 3. Pick-Up Location
 * 4. Delivery Location
 * 5. Dates
 * 6. Pricing and Payment
 * 7. Additional Info
 * 8. Document Details (collapsible)
 * 9. Export Actions
 */
function Review() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // Mode: 'training' (from Test Lab) or 'production' (from Documents)
  const isTrainingMode = searchParams.get('mode') === 'training'

  const [run, setRun] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [warning, setWarning] = useState(null)

  // PDF viewer state
  const [showPdf, setShowPdf] = useState(true)
  const [pdfUrl, setPdfUrl] = useState(null)
  const [zones, setZones] = useState([])
  const [highlightedField, setHighlightedField] = useState(null)

  // Field values and status
  const [fields, setFields] = useState({})

  // Warehouses for delivery destination
  const [warehouses, setWarehouses] = useState([])
  const [selectedWarehouse, setSelectedWarehouse] = useState('')
  const [manualDeliveryOverride, setManualDeliveryOverride] = useState(false)

  // Market Intelligence Pricing
  const [pricing, setPricing] = useState(null)
  const [pricingLoading, setPricingLoading] = useState(false)
  const [urgency, setUrgency] = useState('STANDARD')
  const [finalPrice, setFinalPrice] = useState('')

  // Export flow state
  const [showExportModal, setShowExportModal] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState(null)
  const [exportError, setExportError] = useState(null)

  // Production mode fields
  const [loadSpecificTerms, setLoadSpecificTerms] = useState('')
  const [transportSpecialInstructions, setTransportSpecialInstructions] = useState('')

  // Day 10: New state for CD-aligned layout
  const [loadId, setLoadId] = useState('')
  const [trailerType, setTrailerType] = useState('OPEN')
  const [requiresInspection, setRequiresInspection] = useState(true)
  const [availableDate, setAvailableDate] = useState('')
  const [expirationDate, setExpirationDate] = useState('')
  const [desiredDeliveryDate, setDesiredDeliveryDate] = useState('')
  const [codAmount, setCodAmount] = useState('0')
  const [codPaymentMethod, setCodPaymentMethod] = useState('CASH_CERTIFIED_FUNDS')
  const [codPaymentLocation, setCodPaymentLocation] = useState('DELIVERY')
  const [balancePaymentMethod, setBalancePaymentMethod] = useState('CERTIFIED_FUNDS')
  const [balancePaymentTime, setBalancePaymentTime] = useState('2_BUSINESS_DAYS_QUICK_PAY')
  const [balanceTermsBeginOn, setBalanceTermsBeginOn] = useState('RECEIVING_SIGNED_BOL')

  // Load pricing recommendation
  const loadPricing = useCallback(async (urg) => {
    if (!runId) return
    setPricingLoading(true)
    try {
      const data = await api.getFullPricing(runId, urg || urgency)
      setPricing(data)
    } catch (err) {
      console.error('Failed to load full pricing, falling back:', err)
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

  // Generate Load-Specific Terms template
  const generateLoadSpecificTerms = useCallback((auctionType, warehouseName) => {
    const pickupName = auctionType?.toUpperCase() || 'AUCTION'
    const whName = warehouseName || 'WAREHOUSE'
    return `TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - ${pickupName}, Delivery - ${whName}`
  }, [])

  // Load warehouses
  const loadWarehouses = useCallback(async () => {
    try {
      const data = await api.listWarehouses()
      setWarehouses(data.items || [])
      const defaultWh = (data.items || []).find(w => w.is_default)
      if (defaultWh) {
        setSelectedWarehouse(defaultWh.id.toString())
        setTransportSpecialInstructions(defaultWh.transport_special_instructions || defaultWh.hours || '')
      } else if (data.items?.length > 0) {
        setSelectedWarehouse(data.items[0].id.toString())
        setTransportSpecialInstructions(data.items[0].transport_special_instructions || data.items[0].hours || '')
      }
    } catch (err) {
      console.error('Failed to load warehouses:', err)
    }
  }, [])

  // Initialize dates
  function initializeDates(fieldsData, auctionType) {
    const manheimRelease = fieldsData.manheim_release_date?.corrected || fieldsData.manheim_release_date?.predicted
    const isManheim = auctionType?.toUpperCase() === 'MANHEIM'
    let avDate

    if (isManheim && manheimRelease && manheimRelease !== 'AVAILABLE_NOW' && manheimRelease !== 'NO_RELEASE_DOCUMENT') {
      avDate = manheimRelease // ISO date from extraction
    } else {
      avDate = new Date().toISOString().split('T')[0] // today
    }

    setAvailableDate(avDate)
    // Auto-calculate expiration: available + 30 days
    const expDate = new Date(avDate)
    expDate.setDate(expDate.getDate() + 30)
    setExpirationDate(expDate.toISOString().split('T')[0])
  }

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
          status: item.is_match_ok ? 'correct' : 'review',
          export: item.export_field !== false,
          section: item.section || 'additional',
          fieldType: item.field_type || 'text',
          required: item.required || false,
        }
      }
      setFields(initialFields)

      // Initialize dates based on extraction data
      initializeDates(initialFields, runData.run?.auction_type_code)

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
        const auctionTypes = await api.listAuctionTypes()
        const auctionType = auctionTypes.items?.find(at => at.id === run.auction_type_id)
        if (!auctionType) { setZones([]); return }

        const templates = await api.listZoneTemplates({ auction_type: auctionType.code })
        if (templates.items?.length > 0) {
          const template = templates.items[0]
          const displayZones = (template.zones || []).map(zone => ({
            ...zone,
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

  // Auto-generate Load ID when make/model are available
  useEffect(() => {
    const make = fields.vehicle_make?.corrected
    const model = fields.vehicle_model?.corrected
    if (make && model && !loadId) {
      api.generateLoadId(make, model).then(data => {
        setLoadId(data.load_id)
      }).catch(err => console.error('Load ID generation failed:', err))
    }
  }, [fields.vehicle_make?.corrected, fields.vehicle_model?.corrected, loadId])

  // Update field value
  function updateField(key, value) {
    setFields((prev) => {
      const existing = prev[key]
      if (existing) {
        return {
          ...prev,
          [key]: {
            ...existing,
            corrected: value,
            status: value !== existing.predicted ? 'corrected' : (existing.predicted ? 'correct' : 'review'),
          },
        }
      }
      // Create field entry if it doesn't exist yet (for new fields like vehicle_is_inoperable)
      return {
        ...prev,
        [key]: {
          key,
          label: _formatFieldLabel(key),
          predicted: '',
          corrected: value,
          status: 'corrected',
          export: true,
          section: 'additional',
          fieldType: 'text',
          required: false,
        },
      }
    })
  }

  // Handle warehouse change
  function handleWarehouseChange(warehouseId) {
    setSelectedWarehouse(warehouseId)
    const wh = warehouses.find(w => w.id.toString() === warehouseId)
    if (wh) {
      setTransportSpecialInstructions(wh.transport_special_instructions || wh.hours || '')
      if (run?.auction_type_code) {
        setLoadSpecificTerms(generateLoadSpecificTerms(run.auction_type_code, wh.name))
      }
    }
  }

  // Handle urgency change
  function handleUrgencyChange(newUrgency) {
    setUrgency(newUrgency)
    loadPricing(newUrgency)
  }

  // Submit for training
  async function handleSubmitTraining() {
    setSaving(true)
    setError(null)
    setSuccess(null)
    setWarning(null)

    try {
      const corrections = Object.values(fields).map(f => ({
        field_key: f.key,
        predicted_value: f.predicted || null,
        corrected_value: f.corrected || null,
        was_correct: f.status === 'correct' && f.predicted === f.corrected,
      }))

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

      let successMsg = result.message || `Training data saved! ${result.saved_count} corrections recorded.`
      let unmatchedWarning = null
      const ls = result.learning_summary
      if (ls) {
        const parts = []
        if (ls.rules_created > 0) parts.push(`${ls.rules_created} new pattern${ls.rules_created > 1 ? 's' : ''} learned`)
        if (ls.rules_updated > 0) parts.push(`${ls.rules_updated} pattern${ls.rules_updated > 1 ? 's' : ''} improved`)
        if (ls.fields_improved?.length > 0) {
          parts.push(`confidence improved for: ${ls.fields_improved.slice(0, 3).join(', ')}`)
        }
        if (parts.length > 0) successMsg = `${result.saved_count} corrections saved. ${parts.join('. ')}.`
        if (ls.unmatched_fields?.length > 0) {
          const unmatchedList = ls.unmatched_fields.slice(0, 3).join(', ')
          unmatchedWarning = `Note: Could not learn patterns for ${unmatchedList}${ls.unmatched_fields.length > 3 ? ` (+${ls.unmatched_fields.length - 3} more)` : ''} - values not found in document text.`
        }
      }

      // Submit the review to update run status
      const itemsToSubmit = Object.values(fields).filter(f => f.id).map(f => ({
        item_id: f.id,
        corrected_value: f.corrected || '',
        is_match_ok: f.status === 'correct' || f.status === 'corrected',
        export_field: f.export,
      }))

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
      if (unmatchedWarning) setWarning(unmatchedWarning)

      setTimeout(() => {
        navigate('/test-lab')
      }, unmatchedWarning ? 5000 : 3000)

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
      const itemsToSubmit = Object.values(fields).filter(f => f.id).map(f => ({
        item_id: f.id,
        corrected_value: f.corrected || '',
        is_match_ok: f.status === 'correct' || f.status === 'corrected',
        export_field: f.export,
      }))

      // Apply warehouse data
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

      await api.submitReview({
        run_id: parseInt(runId),
        items: itemsToSubmit,
        warehouse_id: selectedWarehouse ? parseInt(selectedWarehouse) : null,
        mark_for_export: true,
        load_specific_terms: loadSpecificTerms,
        transport_special_instructions: transportSpecialInstructions,
      })

      setSuccess('Document approved for export to Central Dispatch!')
      setTimeout(() => { navigate('/') }, 2000)

    } catch (err) {
      setError(`Failed to approve: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Handle CD export execution
  async function handleExport(result) {
    if (result?.exported_count > 0 || result?.posted > 0) {
      const listingId = result?.previews?.[0]?.cd_listing_id || result?.cd_listing_id || 'unknown'
      setExportResult({ cd_listing_id: listingId, status: 'exported' })
      setSuccess(`Exported! Listing ID: ${listingId}`)
      setShowExportModal(false)
    } else if (result?.status === 'preview') {
      setShowExportModal(false)
    }
  }

  // Loading state
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
  const correctedCount = fieldList.filter(f => f.status === 'corrected').length
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
              {run.document_filename} {'\u2022'} {run.auction_type_code}
              {!isTrainingMode && <span className="ml-2 text-primary-600 font-medium">{'\u2192'} Central Dispatch</span>}
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
              <button onClick={() => setShowPdf(!showPdf)} className="btn btn-secondary text-sm">
                {showPdf ? 'Hide PDF' : 'Show PDF'}
              </button>
            )}

            <button onClick={() => navigate(isTrainingMode ? '/test-lab' : '/')} className="btn btn-secondary text-sm">
              Cancel
            </button>

            {isTrainingMode ? (
              <button onClick={handleSubmitTraining} className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving...' : 'Save & Train'}
              </button>
            ) : (
              <button onClick={handleSubmitProduction} className="btn btn-primary bg-green-600 hover:bg-green-700" disabled={saving}>
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

      {/* Failed Extraction Notice */}
      {run.status === 'failed' && (
        <div className="mx-6 mt-4 bg-orange-50 border border-orange-200 rounded-lg p-4">
          <h3 className="font-medium text-orange-800 mb-1">Manual Entry Required</h3>
          <p className="text-sm text-orange-700">
            Automatic extraction failed. Enter values manually - your corrections will train the system.
          </p>
        </div>
      )}

      {/* Main Content */}
      <div className="p-6">
        <div className="flex gap-6">
          {/* PDF Viewer with Zone Overlay (Left Panel) */}
          {showPdf && pdfUrl && (
            <div className="w-1/2 flex-shrink-0 sticky top-6">
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                <div className="px-4 py-2 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                  <span className="font-medium text-sm text-gray-700">
                    Original Document
                    {zones.length > 0 && (
                      <span className="ml-2 text-xs text-gray-500">({zones.length} zones)</span>
                    )}
                  </span>
                  <a href={pdfUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-primary-600 hover:text-primary-800">
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

          {/* Fields Panel (Right Panel) — 9 CD-Aligned Sections */}
          <div className={showPdf && pdfUrl ? 'w-1/2' : 'w-full'}>

            {/* Section 1: Extraction Info Bar */}
            <ExtractionInfoBar run={run} />

            {/* Section 2: Vehicle Information */}
            <VehicleSection
              fields={fields}
              updateField={updateField}
              trailerType={trailerType}
              setTrailerType={setTrailerType}
              highlightedField={highlightedField}
              setHighlightedField={setHighlightedField}
            />

            {/* Section 3: Pick-Up Location */}
            <PickupSection
              fields={fields}
              updateField={updateField}
              highlightedField={highlightedField}
              setHighlightedField={setHighlightedField}
            />

            {/* Section 4: Delivery Location */}
            <DeliverySection
              warehouses={warehouses}
              selectedWarehouse={selectedWarehouse}
              handleWarehouseChange={handleWarehouseChange}
              manualOverride={manualDeliveryOverride}
              setManualOverride={setManualDeliveryOverride}
              fields={fields}
              updateField={updateField}
            />

            {/* Section 5: Dates */}
            <DatesSection
              availableDate={availableDate}
              setAvailableDate={setAvailableDate}
              expirationDate={expirationDate}
              setExpirationDate={setExpirationDate}
              desiredDeliveryDate={desiredDeliveryDate}
              setDesiredDeliveryDate={setDesiredDeliveryDate}
              manheimReleaseDate={fields.manheim_release_date?.corrected}
              auctionType={run?.auction_type_code}
            />

            {/* Section 6: Pricing and Payment */}
            <PricingPaymentSection
              pricing={pricing}
              pricingLoading={pricingLoading}
              urgency={urgency}
              handleUrgencyChange={handleUrgencyChange}
              finalPrice={finalPrice}
              setFinalPrice={setFinalPrice}
              codAmount={codAmount}
              setCodAmount={setCodAmount}
              codPaymentMethod={codPaymentMethod}
              setCodPaymentMethod={setCodPaymentMethod}
              codPaymentLocation={codPaymentLocation}
              setCodPaymentLocation={setCodPaymentLocation}
              balancePaymentMethod={balancePaymentMethod}
              setBalancePaymentMethod={setBalancePaymentMethod}
              balancePaymentTime={balancePaymentTime}
              setBalancePaymentTime={setBalancePaymentTime}
              balanceTermsBeginOn={balanceTermsBeginOn}
              setBalanceTermsBeginOn={setBalanceTermsBeginOn}
            />

            {/* Section 7: Additional Info */}
            {!isTrainingMode && (
              <AdditionalInfoSection
                loadId={loadId}
                fields={fields}
                updateField={updateField}
                loadSpecificTerms={loadSpecificTerms}
                setLoadSpecificTerms={setLoadSpecificTerms}
                transportSpecialInstructions={transportSpecialInstructions}
                setTransportSpecialInstructions={setTransportSpecialInstructions}
                requiresInspection={requiresInspection}
                setRequiresInspection={setRequiresInspection}
              />
            )}

            {/* Section 8: Document Details (collapsible) */}
            <DocumentDetails fields={fields} run={run} />

            {/* Section 9: Export Actions */}
            <ExportActions
              runId={runId}
              isTrainingMode={isTrainingMode}
              saving={saving}
              handleSubmitTraining={handleSubmitTraining}
              handleSubmitProduction={handleSubmitProduction}
              showExportModal={showExportModal}
              setShowExportModal={setShowExportModal}
              exportResult={exportResult}
              exportError={exportError}
              exporting={exporting}
              selectedWarehouse={selectedWarehouse}
              correctCount={correctCount}
              totalCount={fieldList.length}
              correctedCount={correctedCount}
              needsReviewCount={needsReviewCount}
            />
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
