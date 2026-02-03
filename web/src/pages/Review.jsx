import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api'
import PreflightBanner from '../components/PreflightBanner'
import PDFViewer from '../components/PDFViewer'

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

  // Training mode flag - from URL or default
  const isTrainingMode = searchParams.get('mode') === 'training' || true

  const [run, setRun] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  // PDF viewer state
  const [showPdf, setShowPdf] = useState(true)
  const [pdfUrl, setPdfUrl] = useState(null)

  // Highlighted field for evidence display (M3.P2.2)
  const [highlightedField, setHighlightedField] = useState(null)

  // Field values and status
  const [fields, setFields] = useState({})

  // Warehouses for delivery destination
  const [warehouses, setWarehouses] = useState([])
  const [selectedWarehouse, setSelectedWarehouse] = useState('')

  // Load warehouses
  const loadWarehouses = useCallback(async () => {
    try {
      const data = await api.listWarehouses()
      setWarehouses(data.items || [])
      const defaultWh = (data.items || []).find(w => w.is_default)
      if (defaultWh) {
        setSelectedWarehouse(defaultWh.id.toString())
      } else if (data.items?.length > 0) {
        setSelectedWarehouse(data.items[0].id.toString())
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

      // Initialize field values
      const initialFields = {}
      for (const item of (itemsData.items || [])) {
        initialFields[item.source_key || item.cd_key] = {
          id: item.id,
          key: item.source_key || item.cd_key,
          label: item.display_name || item.source_key,
          predicted: item.predicted_value || '',
          corrected: item.corrected_value || item.predicted_value || '',
          confidence: item.confidence,
          cdKey: item.cd_key,
          status: item.is_match_ok ? 'correct' : 'review', // 'correct', 'corrected', 'review'
          export: item.export_field !== false,
        }
      }
      setFields(initialFields)

      await loadWarehouses()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [runId, loadWarehouses])

  useEffect(() => {
    fetchData()
  }, [fetchData])

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

  // Submit for training
  async function handleSubmitTraining() {
    setSaving(true)
    setError(null)
    setSuccess(null)

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

      setSuccess(`Training data saved! ${result.saved_count} corrections recorded.`)

      // Stay on page in training mode, or go to test lab
      setTimeout(() => {
        navigate('/test-lab')
      }, 2000)

    } catch (err) {
      setError(`Failed to submit: ${err.message}`)
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
          <button onClick={() => navigate('/test-lab')} className="btn btn-primary">
            Back to Test Lab
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
            <h1 className="text-xl font-bold text-gray-900">Review & Train</h1>
            <p className="text-sm text-gray-500">
              {run.document_filename} • {run.auction_type_code}
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
              onClick={() => navigate('/test-lab')}
              className="btn btn-secondary text-sm"
            >
              Cancel
            </button>

            <button
              onClick={handleSubmitTraining}
              className="btn btn-primary"
              disabled={saving}
            >
              {saving ? 'Saving...' : 'Save & Train'}
            </button>
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
        <div className="mx-6 mt-4 p-4 bg-green-50 border border-green-200 rounded-lg text-green-700">
          {success}
        </div>
      )}

      {/* Main Content */}
      <div className="p-6">
        <div className={`flex gap-6 ${showPdf && pdfUrl ? '' : ''}`}>
          {/* PDF Viewer with Evidence Overlay (M3.P2.1 & M3.P2.2) */}
          {showPdf && pdfUrl && (
            <div className="w-1/2 flex-shrink-0 sticky top-6">
              <PDFViewer
                pdfUrl={pdfUrl}
                runId={parseInt(runId)}
                highlightedField={highlightedField}
                onBlockClick={(block) => console.log('Block clicked:', block)}
              />
            </div>
          )}

          {/* Fields Panel */}
          <div className={showPdf && pdfUrl ? 'w-1/2' : 'w-full'}>
            {/* Preflight Banner (M3.P2.3) */}
            <PreflightBanner
              runId={parseInt(runId)}
              onIssueClick={(fieldKey) => setHighlightedField(fieldKey)}
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
                  onChange={(e) => setSelectedWarehouse(e.target.value)}
                  className="form-select w-full"
                >
                  <option value="">-- Select Warehouse --</option>
                  {warehouses.map((wh) => (
                    <option key={wh.id} value={wh.id}>
                      {wh.name} ({wh.city}, {wh.state})
                    </option>
                  ))}
                </select>
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
                <h2 className="font-medium text-gray-900">Extracted Fields</h2>
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
                          {field.label || field.key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                        </span>
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
                <button
                  onClick={handleSubmitTraining}
                  className="btn btn-primary"
                  disabled={saving}
                >
                  {saving ? 'Saving...' : 'Save & Train'}
                </button>
              </div>
              <p className="text-xs text-gray-500 mt-3">
                Your corrections help train the system to extract similar documents more accurately.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Review
