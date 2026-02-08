import { useState, useEffect } from 'react'
import api from '../api'
import {
  CD_FIELDS,
  StatusIndicator,
  StatusBadge,
  ProductionCorrectionsPanel,
  ZoneTemplatesTab,
} from '../components/testlab'

function TestLab() {
  const [auctionTypes, setAuctionTypes] = useState([])
  const [selectedAuctionType, setSelectedAuctionType] = useState('')
  const [testFile, setTestFile] = useState(null)
  const [processing, setProcessing] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  // Recent test runs
  const [recentTests, setRecentTests] = useState([])
  const [loadingTests, setLoadingTests] = useState(true)

  // Tabs - default to unified training tab
  const [activeTab, setActiveTab] = useState('training')

  // Extracted fields from test result
  const [extractedFields, setExtractedFields] = useState(null)
  const [loadingExtractedFields, setLoadingExtractedFields] = useState(false)

  // Training stats
  const [trainingStats, setTrainingStats] = useState(null)

  // Auction type form
  const [showAuctionTypeForm, setShowAuctionTypeForm] = useState(false)
  const [auctionTypeForm, setAuctionTypeForm] = useState({
    name: '',
    code: '',
    description: '',
    parent_id: null,
  })

  // Selected auction type for editing
  const [editingAuctionType, setEditingAuctionType] = useState(null)
  const [fieldMappings, setFieldMappings] = useState([])
  const [loadingFields, setLoadingFields] = useState(false)

  // New field form
  const [showNewFieldForm, setShowNewFieldForm] = useState(false)
  const [newFieldForm, setNewFieldForm] = useState({
    field_key: '',
    display_name: '',
    field_type: 'text',
    is_required: false,
    description: '',
  })

  // Training data
  const [trainingDocuments, setTrainingDocuments] = useState([])
  const [uploadingTrainingDoc, setUploadingTrainingDoc] = useState(false)

  useEffect(() => {
    loadAuctionTypes()
    loadRecentTests()
    loadTrainingStats()
  }, [])

  // Load field mappings when editing auction type changes
  useEffect(() => {
    if (editingAuctionType) {
      loadFieldMappings(editingAuctionType.id)
    }
  }, [editingAuctionType])

  async function loadAuctionTypes() {
    try {
      const data = await api.listAuctionTypes()
      setAuctionTypes(data.items || [])
      if (data.items?.length > 0) {
        setSelectedAuctionType(data.items[0].id.toString())
      }
    } catch (err) {
      console.error('Failed to load auction types:', err)
    }
  }

  async function loadRecentTests() {
    setLoadingTests(true)
    try {
      // Only load extractions from training/test documents (is_test=true)
      // This ensures Test Lab doesn't show production documents
      const data = await api.listExtractions({ limit: 20, is_test: true })
      setRecentTests(data.items || [])
    } catch (err) {
      console.error('Failed to load recent tests:', err)
    } finally {
      setLoadingTests(false)
    }
  }

  async function loadTrainingStats() {
    try {
      const response = await fetch('/api/models/training-stats/overview')
      if (response.ok) {
        const data = await response.json()
        setTrainingStats(data)
      }
    } catch (err) {
      console.error('Failed to load training stats:', err)
    }
  }

  async function loadFieldMappings(auctionTypeId) {
    setLoadingFields(true)
    try {
      const data = await api.listFields(auctionTypeId, true)
      // Map API response to our format
      const fields = (data || []).map(f => ({
        id: f.id,
        field_key: f.source_key || f.cd_key || f.internal_key,
        display_name: f.display_name || f.source_key,
        field_type: f.field_type || 'text',
        is_required: f.is_required || false,
        description: f.description,
        sort_order: f.display_order || 0,
        is_active: f.is_active !== false,
        extraction_hints: f.extraction_hints || [],
        cd_key: f.cd_key,
        internal_key: f.internal_key,
        source_key: f.source_key,
      }))
      // If fields exist, use them; otherwise initialize with defaults
      if (fields.length > 0) {
        setFieldMappings(fields)
      } else {
        // Initialize with default CD fields
        setFieldMappings(CD_FIELDS.map((f, idx) => ({
          id: null,
          field_key: f.key,
          display_name: f.label,
          field_type: f.type,
          is_required: f.required,
          description: f.description,
          sort_order: idx,
          is_active: true,
          extraction_hints: [],
          cd_key: f.key,
          internal_key: f.key,
          source_key: f.key,
        })))
      }
    } catch (err) {
      console.error('Failed to load field mappings:', err)
      // Initialize with default CD fields if API fails
      setFieldMappings(CD_FIELDS.map((f, idx) => ({
        id: null,
        field_key: f.key,
        display_name: f.label,
        field_type: f.type,
        is_required: f.required,
        description: f.description,
        sort_order: idx,
        is_active: true,
        extraction_hints: [],
        cd_key: f.key,
        internal_key: f.key,
        source_key: f.key,
      })))
    } finally {
      setLoadingFields(false)
    }
  }

  async function handleSaveFieldMappings() {
    if (!editingAuctionType) return

    try {
      for (const field of fieldMappings) {
        if (field.id) {
          // Update existing field
          await api.updateField(editingAuctionType.id, field.id, {
            display_name: field.display_name,
            is_required: field.is_required,
            is_active: field.is_active,
            extraction_hints: field.extraction_hints || [],
            display_order: field.sort_order,
          })
        } else {
          // Create new field using correct API field names
          await api.createField(editingAuctionType.id, {
            source_key: field.field_key,
            internal_key: field.field_key,
            cd_key: field.cd_key || field.field_key,
            display_name: field.display_name,
            field_type: field.field_type,
            is_required: field.is_required,
            description: field.description,
            display_order: field.sort_order,
            extraction_hints: field.extraction_hints || [],
            is_active: true,
          })
        }
      }
      setError(null)
      alert('Field mappings saved successfully!')
      loadFieldMappings(editingAuctionType.id)
    } catch (err) {
      setError('Failed to save field mappings: ' + err.message)
    }
  }

  function handleAddField(e) {
    e.preventDefault()
    if (!newFieldForm.field_key || !newFieldForm.display_name) {
      alert('Field key and display name are required')
      return
    }

    // Check for duplicate field key
    if (fieldMappings.some(f => f.field_key === newFieldForm.field_key)) {
      alert('A field with this key already exists')
      return
    }

    // Add new field to the list
    const newField = {
      id: null, // Will be created when saved
      field_key: newFieldForm.field_key,
      display_name: newFieldForm.display_name,
      field_type: newFieldForm.field_type,
      is_required: newFieldForm.is_required,
      description: newFieldForm.description,
      sort_order: fieldMappings.length,
      is_active: true,
      value_source: 'extracted',
      default_value: '',
      cd_key: newFieldForm.field_key,
      internal_key: newFieldForm.field_key,
      source_key: newFieldForm.field_key,
    }

    setFieldMappings([...fieldMappings, newField])
    setShowNewFieldForm(false)
    setNewFieldForm({
      field_key: '',
      display_name: '',
      field_type: 'text',
      is_required: false,
      description: '',
    })
  }

  async function handleDeleteField(idx) {
    const field = fieldMappings[idx]
    if (!field) return

    const confirmMsg = field.id
      ? 'Delete this field? It will be removed from the database.'
      : 'Remove this field from the list?'

    if (!confirm(confirmMsg)) return

    if (field.id && editingAuctionType) {
      // Delete from API
      try {
        await api.deleteField(editingAuctionType.id, field.id, true)
      } catch (err) {
        alert('Error deleting field: ' + err.message)
        return
      }
    }

    // Remove from local state
    const updated = fieldMappings.filter((_, i) => i !== idx)
    setFieldMappings(updated)
  }

  async function handleUploadTrainingDoc(file, auctionTypeId) {
    setUploadingTrainingDoc(true)
    try {
      // Upload as TRAINING document (is_test=true, source=test_lab)
      await api.uploadTrainingDocument(file, auctionTypeId)
      loadTrainingStats()
      loadRecentTests()
      loadDocuments() // Refresh training documents list
    } catch (err) {
      alert('Error uploading training document: ' + err.message)
    } finally {
      setUploadingTrainingDoc(false)
    }
  }

  async function handleTestUpload() {
    if (!testFile || !selectedAuctionType) return

    setProcessing(true)
    setError(null)
    setResult(null)
    setExtractedFields(null)

    try {
      const formData = new FormData()
      formData.append('file', testFile)
      formData.append('auction_type_id', selectedAuctionType)
      formData.append('dataset_split', 'test')
      formData.append('source', 'test_lab')
      formData.append('is_test', 'true')

      const response = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || 'Upload failed')
      }

      const data = await response.json()

      setResult({
        document: data.document,
        run_id: data.run_id,
        run_status: data.run_status,
        needs_ocr: data.needs_ocr,
        text_length: data.text_length,
        detected_source: data.detected_source,
        classification_score: data.classification_score,
        raw_text_preview: data.raw_text_preview,
      })

      // Fetch extracted fields if we have a run_id
      if (data.run_id) {
        loadExtractedFields(data.run_id)
      }

      loadRecentTests()
    } catch (err) {
      setError(err.message)
    } finally {
      setProcessing(false)
    }
  }

  async function loadExtractedFields(runId) {
    setLoadingExtractedFields(true)
    try {
      const response = await fetch(`/api/extractions/${runId}`)
      if (response.ok) {
        const data = await response.json()
        setExtractedFields(data.fields || data.extracted_data || data)
      }
    } catch (err) {
      console.error('Failed to load extracted fields:', err)
    } finally {
      setLoadingExtractedFields(false)
    }
  }

  async function handleDryRunExport(runId) {
    try {
      const result = await api.cdDryRun(runId)
      alert(result.is_valid
        ? 'Dry run passed! Payload ready for export.'
        : 'Validation errors: ' + (result.validation_errors?.join(', ') || 'Unknown error')
      )
    } catch (err) {
      alert('Dry run failed: ' + err.message)
    }
  }

  async function handleDeleteDocument(documentId, e) {
    if (e) e.stopPropagation()
    if (!confirm('Delete this document and all related extraction data? This cannot be undone.')) return

    try {
      await api.deleteDocument(documentId)
      loadRecentTests()
      loadTrainingStats()
    } catch (err) {
      alert('Error deleting document: ' + err.message)
    }
  }

  async function handleClearAllTestDocuments() {
    if (!confirm('DELETE ALL TEST DOCUMENTS?\n\nThis will permanently remove all documents uploaded in Test Lab and their extraction data.\n\nThis action CANNOT be undone!')) return
    if (!confirm('Are you SURE? Type "DELETE" to confirm.')) return

    try {
      const result = await api.clearTestLabDocuments()
      alert(result.message || `Deleted ${result.deleted_count} documents`)
      loadRecentTests()
      loadTrainingStats()
    } catch (err) {
      alert('Error clearing documents: ' + err.message)
    }
  }

  async function handleCreateAuctionType(e) {
    e.preventDefault()
    try {
      const response = await fetch('/api/auction-types/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: auctionTypeForm.name,
          code: auctionTypeForm.code.toUpperCase(),
          description: auctionTypeForm.description,
          parent_id: auctionTypeForm.parent_id || null,
          is_custom: true,
        }),
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || 'Failed to create auction type')
      }

      setShowAuctionTypeForm(false)
      setAuctionTypeForm({ name: '', code: '', description: '', parent_id: null })
      loadAuctionTypes()
    } catch (err) {
      alert('Error: ' + err.message)
    }
  }

  function clearResult() {
    setResult(null)
    setTestFile(null)
    setError(null)
    setExtractedFields(null)
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Test Lab</h1>
          <p className="text-gray-500 mt-1">
            Sandbox environment for testing PDF extraction without affecting production data
          </p>
        </div>
        <span className="px-3 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm font-medium">
          Sandbox Mode
        </span>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('training')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'training'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Training & Testing
          </button>
          <button
            onClick={() => setActiveTab('auction-types')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'auction-types'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Auction Types
          </button>
          <button
            onClick={() => setActiveTab('zone-templates')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'zone-templates'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Zone Templates
          </button>
        </nav>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {error}
          <button onClick={() => setError(null)} className="ml-4 text-sm underline">Dismiss</button>
        </div>
      )}

      {/* Unified Training & Testing Tab */}
      {activeTab === 'training' && (
        <div className="space-y-6">
          {/* Info Banner */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h3 className="font-semibold text-blue-800 mb-2">Training & Testing Environment</h3>
            <p className="text-sm text-blue-700">
              Upload PDF documents to test extraction and build training data. Review extracted fields,
              correct any errors, and the system will learn from your corrections to improve accuracy for each auction type.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Upload Section */}
            <div className="card">
              <div className="card-header">
                <h2 className="font-semibold">Upload Document</h2>
              </div>
              <div className="card-body space-y-4">
                <div>
                  <label className="form-label">Auction Type</label>
                  <select
                    value={selectedAuctionType}
                    onChange={(e) => {
                      setSelectedAuctionType(e.target.value)
                      const at = auctionTypes.find(a => a.id.toString() === e.target.value)
                      if (at) loadFieldMappings(at.id)
                    }}
                    className="form-select w-full"
                  >
                    {auctionTypes.map((at) => (
                      <option key={at.id} value={at.id}>{at.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="form-label">PDF Document</label>
                  <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
                    {testFile ? (
                      <div>
                        <p className="font-medium text-gray-900">{testFile.name}</p>
                        <p className="text-sm text-gray-500">
                          {(testFile.size / 1024).toFixed(1)} KB
                        </p>
                        <button
                          onClick={() => setTestFile(null)}
                          className="mt-2 text-sm text-red-600 hover:text-red-800"
                        >
                          Remove
                        </button>
                      </div>
                    ) : (
                      <label className="cursor-pointer">
                        <input
                          type="file"
                          accept=".pdf"
                          onChange={(e) => setTestFile(e.target.files[0])}
                          className="hidden"
                        />
                        <div className="text-gray-500">
                          <svg className="w-12 h-12 mx-auto mb-2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                          </svg>
                          <p>Click to select PDF</p>
                          <p className="text-xs mt-1">or drag and drop</p>
                        </div>
                      </label>
                    )}
                  </div>
                </div>

                <button
                  onClick={handleTestUpload}
                  disabled={!testFile || processing}
                  className="btn btn-primary w-full"
                >
                  {processing ? 'Processing...' : 'Extract & Analyze'}
                </button>

                {/* Training Stats for Selected Auction Type */}
                {selectedAuctionType && trainingStats && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-sm font-medium text-gray-700 mb-2">Training Progress</p>
                    {(() => {
                      const at = auctionTypes.find(a => a.id.toString() === selectedAuctionType)
                      const stats = trainingStats?.by_auction_type?.[at?.code] || { total: 0, validated: 0 }
                      return (
                        <>
                          <div className="flex justify-between text-xs text-gray-600">
                            <span>Examples: {stats.total}</span>
                            <span>Validated: {stats.validated}</span>
                          </div>
                          <div className="w-full bg-gray-200 rounded-full h-2 mt-1">
                            <div
                              className="bg-green-500 h-2 rounded-full"
                              style={{ width: `${Math.min(100, (stats.total / 50) * 100)}%` }}
                            ></div>
                          </div>
                          <p className="text-xs text-gray-500 mt-1">
                            {stats.total >= 50 ? 'Ready for training' : `${50 - stats.total} more examples needed`}
                          </p>
                        </>
                      )
                    })()}
                  </div>
                )}
              </div>
            </div>

            {/* Extraction Result & Fields */}
            <div className="lg:col-span-2">
              <div className="card">
                <div className="card-header flex items-center justify-between">
                  <h2 className="font-semibold">Extraction Result</h2>
                  {result && (
                    <button onClick={clearResult} className="text-sm text-gray-500 hover:text-gray-700">
                      Clear
                    </button>
                  )}
                </div>
                <div className="card-body">
                  {result ? (
                    <div className="space-y-4">
                      {/* Status and Meta */}
                      <div className="flex items-center justify-between border-b pb-4">
                        <div className="flex items-center space-x-2">
                          <StatusIndicator status={result.run_status} />
                          <span className="font-medium">
                            {result.run_status === 'needs_review' ? 'Extraction Complete' :
                             result.run_status === 'failed' ? 'Extraction Failed' :
                             result.run_status}
                          </span>
                        </div>
                        <div className="text-sm text-gray-500">
                          Detected: <span className="font-medium">{result.detected_source || 'Unknown'}</span>
                          {result.classification_score && (
                            <span className="ml-2">({(result.classification_score * 100).toFixed(0)}% confidence)</span>
                          )}
                        </div>
                      </div>

                      {/* Extracted Fields Display */}
                      {loadingExtractedFields ? (
                        <div className="text-center py-8">
                          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
                          <p className="text-sm text-gray-500 mt-2">Loading extracted fields...</p>
                        </div>
                      ) : extractedFields ? (
                        <div>
                          <h3 className="font-medium text-gray-700 mb-3">Extracted Fields</h3>
                          <div className="bg-gray-50 rounded-lg divide-y divide-gray-200 max-h-[400px] overflow-y-auto">
                            {Object.entries(extractedFields).filter(([key]) => !key.startsWith('_') && key !== 'id' && key !== 'run_id').map(([key, value]) => {
                              // Find matching CD field definition
                              const cdField = CD_FIELDS.find(f => f.key === key)
                              const displayValue = value === null || value === undefined ? '-' :
                                typeof value === 'object' ? JSON.stringify(value) : String(value)
                              const isEmpty = !value || displayValue === '-' || displayValue === ''

                              return (
                                <div key={key} className={`flex items-center justify-between p-3 ${isEmpty ? 'bg-yellow-50' : ''}`}>
                                  <div className="flex-1">
                                    <span className="text-sm font-medium text-gray-700">
                                      {cdField?.label || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                                    </span>
                                    <span className="ml-2 text-xs text-gray-400 font-mono">{key}</span>
                                  </div>
                                  <div className={`text-sm ${isEmpty ? 'text-red-500 italic' : 'text-gray-900'}`}>
                                    {isEmpty ? 'Not extracted' : displayValue}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ) : (
                        <div className="text-center py-4 text-gray-500 text-sm">
                          Field extraction data not available
                        </div>
                      )}

                      {/* Text Preview */}
                      {result.raw_text_preview && (
                        <details className="bg-gray-50 rounded-lg">
                          <summary className="p-3 cursor-pointer text-sm font-medium text-gray-700">
                            Raw Text Preview ({result.text_length} chars)
                          </summary>
                          <pre className="text-xs p-3 border-t max-h-48 overflow-auto whitespace-pre-wrap">
                            {result.raw_text_preview}
                          </pre>
                        </details>
                      )}

                      {/* Actions */}
                      <div className="flex space-x-2 pt-2 border-t">
                        {result.run_id && (
                          <a
                            href={'/review/' + result.run_id}
                            className="btn btn-primary flex-1 text-center"
                          >
                            {result.run_status === 'failed' ? 'Enter Data Manually' : 'Review & Correct Fields'}
                          </a>
                        )}
                        {result.run_id && result.run_status !== 'failed' && (
                          <button
                            onClick={() => handleDryRunExport(result.run_id)}
                            className="btn btn-secondary"
                          >
                            Dry Run Export
                          </button>
                        )}
                      </div>

                      <p className="text-xs text-gray-500 bg-blue-50 p-2 rounded">
                        <strong>Training tip:</strong> Click "Review & Correct Fields" to fix any extraction errors.
                        Your corrections help train the system for better accuracy on similar documents.
                      </p>
                    </div>
                  ) : (
                    <div className="text-center py-12 text-gray-500">
                      <svg className="w-16 h-16 mx-auto text-gray-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                      <p>Upload a PDF to test extraction</p>
                      <p className="text-xs mt-2">Extracted fields will be displayed here for review</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Recent Test Runs */}
          <div className="card">
            <div className="card-header flex items-center justify-between">
              <h2 className="font-semibold">Recent Extractions</h2>
              <div className="flex space-x-2">
                <button onClick={handleClearAllTestDocuments} className="btn btn-sm bg-red-600 text-white hover:bg-red-700">
                  Clear All Test Data
                </button>
                <button onClick={loadRecentTests} className="btn btn-sm btn-secondary">
                  Refresh
                </button>
              </div>
            </div>
            <div className="card-body p-0">
              {loadingTests ? (
                <div className="p-8 text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
                </div>
              ) : recentTests.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  No extractions yet. Upload a PDF to get started.
                </div>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Auction Type</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentTests.map((run) => (
                      <tr key={run.id}>
                        <td className="text-sm">
                          <span className="truncate max-w-[200px] block">
                            {run.document_filename || 'Doc #' + run.document_id}
                          </span>
                          <span className="text-xs text-gray-400 font-mono">ID: {run.id}</span>
                        </td>
                        <td>
                          <span className={`badge ${
                            run.auction_type_code === 'COPART' ? 'bg-blue-100 text-blue-800' :
                            run.auction_type_code === 'IAA' ? 'bg-purple-100 text-purple-800' :
                            run.auction_type_code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
                            'bg-gray-100 text-gray-800'
                          }`}>{run.auction_type_code}</span>
                        </td>
                        <td>
                          <StatusBadge status={run.status} />
                        </td>
                        <td className="text-xs text-gray-500">
                          {run.created_at ? new Date(run.created_at).toLocaleString() : '-'}
                        </td>
                        <td>
                          <div className="flex space-x-2">
                            <a href={'/review/' + run.id} className="text-sm text-blue-600 hover:text-blue-800">
                              {run.status === 'failed' ? 'Enter Data' : 'Review & Train'}
                            </a>
                            {run.status !== 'failed' && (
                              <button
                                onClick={() => handleDryRunExport(run.id)}
                                className="text-sm text-gray-600 hover:text-gray-800"
                              >
                                Dry Run
                              </button>
                            )}
                            <button
                              onClick={(e) => handleDeleteDocument(run.document_id, e)}
                              className="text-sm text-red-600 hover:text-red-800"
                              title="Delete document and extraction"
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Training Stats by Auction Type */}
          <div className="card">
            <div className="card-header">
              <h2 className="font-semibold">Training Data by Auction Type</h2>
            </div>
            <div className="card-body">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {auctionTypes.map((at) => {
                  const stats = trainingStats?.by_auction_type?.[at.code] || { total: 0, validated: 0 }
                  const progress = stats.total >= 50 ? 100 : (stats.total / 50) * 100
                  return (
                    <div key={at.id} className="bg-gray-50 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-2">
                        <span className={`badge ${
                          at.code === 'COPART' ? 'bg-blue-100 text-blue-800' :
                          at.code === 'IAA' ? 'bg-purple-100 text-purple-800' :
                          at.code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>{at.name}</span>
                        {stats.total >= 50 && (
                          <span className="text-xs text-green-600 font-medium">Ready</span>
                        )}
                      </div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-gray-600">{stats.total} examples</span>
                        <span className="text-green-600">{stats.validated} validated</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${stats.total >= 50 ? 'bg-green-500' : 'bg-blue-500'}`}
                          style={{ width: `${progress}%` }}
                        ></div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Production Corrections (Second Training Channel) */}
          <ProductionCorrectionsPanel />
        </div>
      )}

      {/* Auction Types Tab */}
      {activeTab === 'auction-types' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className={editingAuctionType ? 'lg:col-span-1' : 'lg:col-span-2'}>
            <div className="card">
              <div className="card-header flex items-center justify-between">
                <h2 className="font-semibold">Auction Types</h2>
                <button
                  onClick={() => setShowAuctionTypeForm(true)}
                  className="btn btn-sm btn-primary"
                >
                  + Add Custom Type
                </button>
              </div>
              <div className="card-body p-0">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Code</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auctionTypes.map((at) => (
                      <tr
                        key={at.id}
                        className={`cursor-pointer hover:bg-gray-50 ${editingAuctionType?.id === at.id ? 'bg-primary-50' : ''}`}
                        onClick={() => setEditingAuctionType(at)}
                      >
                        <td className="font-medium">{at.name}</td>
                        <td>
                          <span className={`badge ${
                            at.code === 'COPART' ? 'bg-blue-100 text-blue-800' :
                            at.code === 'IAA' ? 'bg-purple-100 text-purple-800' :
                            at.code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
                            'bg-gray-100 text-gray-800'
                          }`}>{at.code}</span>
                        </td>
                        <td>
                          {at.is_base ? (
                            <span className="text-xs text-gray-500">Base</span>
                          ) : (
                            <span className="text-xs text-primary-600">Custom</span>
                          )}
                        </td>
                        <td>
                          {at.is_active ? (
                            <span className="badge badge-success">Active</span>
                          ) : (
                            <span className="badge badge-gray">Inactive</span>
                          )}
                        </td>
                        <td>
                          <button
                            onClick={(e) => { e.stopPropagation(); setEditingAuctionType(at); }}
                            className="text-sm text-primary-600 hover:text-primary-800"
                          >
                            Configure Fields
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Create Auction Type Form */}
            {showAuctionTypeForm && (
              <div className="card mt-6">
                <div className="card-header">
                  <h2 className="font-semibold">Create Custom Auction Type</h2>
                </div>
                <form onSubmit={handleCreateAuctionType} className="card-body space-y-4">
                  <div>
                    <label className="form-label">Name</label>
                    <input
                      type="text"
                      value={auctionTypeForm.name}
                      onChange={(e) => setAuctionTypeForm(f => ({ ...f, name: e.target.value }))}
                      className="form-input w-full"
                      placeholder="e.g., Custom Auction"
                      required
                    />
                  </div>
                  <div>
                    <label className="form-label">Code</label>
                    <input
                      type="text"
                      value={auctionTypeForm.code}
                      onChange={(e) => setAuctionTypeForm(f => ({ ...f, code: e.target.value.toUpperCase() }))}
                      className="form-input w-full font-mono"
                      placeholder="e.g., CUSTOM"
                      maxLength={20}
                      required
                    />
                  </div>
                  <div>
                    <label className="form-label">Base Type (optional)</label>
                    <select
                      value={auctionTypeForm.parent_id || ''}
                      onChange={(e) => setAuctionTypeForm(f => ({ ...f, parent_id: e.target.value || null }))}
                      className="form-select w-full"
                    >
                      <option value="">None (standalone)</option>
                      {auctionTypes.filter(at => at.is_base).map((at) => (
                        <option key={at.id} value={at.id}>Inherit from {at.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="form-label">Description</label>
                    <textarea
                      value={auctionTypeForm.description}
                      onChange={(e) => setAuctionTypeForm(f => ({ ...f, description: e.target.value }))}
                      className="form-input w-full"
                      rows={2}
                      placeholder="Optional description..."
                    />
                  </div>
                  <div className="flex space-x-2">
                    <button type="submit" className="btn btn-primary flex-1">Create</button>
                    <button type="button" onClick={() => setShowAuctionTypeForm(false)} className="btn btn-secondary">Cancel</button>
                  </div>
                </form>
              </div>
            )}
          </div>

          {/* Field Mapping Configuration Panel */}
          <div className={editingAuctionType ? 'lg:col-span-2' : 'lg:col-span-1'}>
            {editingAuctionType ? (
              <div className="card">
                <div className="card-header flex items-center justify-between">
                  <div>
                    <h2 className="font-semibold">Field Mappings: {editingAuctionType.name}</h2>
                    <p className="text-sm text-gray-500">Configure which fields are extracted and mapped to Central Dispatch</p>
                  </div>
                  <button
                    onClick={() => setEditingAuctionType(null)}
                    className="text-gray-500 hover:text-gray-700"
                  >
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <div className="card-body p-0">
                  {loadingFields ? (
                    <div className="p-8 text-center">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
                    </div>
                  ) : (
                    <>
                      <div className="max-h-[500px] overflow-y-auto">
                        <table className="table table-sm">
                          <thead className="sticky top-0 bg-white">
                            <tr>
                              <th className="w-8">Active</th>
                              <th>CD API Field</th>
                              <th>Display Name</th>
                              <th>Source</th>
                              <th>Required</th>
                              <th>Default Value</th>
                              <th className="w-10"></th>
                            </tr>
                          </thead>
                          <tbody>
                            {(fieldMappings.length > 0 ? fieldMappings : CD_FIELDS.map((f, idx) => ({
                              id: null,
                              field_key: f.key,
                              display_name: f.label,
                              field_type: f.type,
                              is_required: f.required,
                              description: f.description,
                              sort_order: idx,
                              is_active: true,
                              value_source: 'extracted', // 'extracted' or 'constant'
                              default_value: '',
                            }))).map((field, idx) => (
                              <tr key={field.field_key || idx} className={`hover:bg-gray-50 ${field.value_source === 'constant' ? 'bg-blue-50' : ''}`}>
                                <td>
                                  <input
                                    type="checkbox"
                                    checked={field.is_active !== false}
                                    onChange={(e) => {
                                      const updated = [...fieldMappings]
                                      if (updated[idx]) {
                                        updated[idx] = { ...updated[idx], is_active: e.target.checked }
                                        setFieldMappings(updated)
                                      }
                                    }}
                                    className="form-checkbox"
                                  />
                                </td>
                                <td className="font-mono text-xs text-gray-600">{field.field_key}</td>
                                <td>
                                  <input
                                    type="text"
                                    value={field.display_name}
                                    onChange={(e) => {
                                      const updated = [...fieldMappings]
                                      if (updated[idx]) {
                                        updated[idx] = { ...updated[idx], display_name: e.target.value }
                                        setFieldMappings(updated)
                                      }
                                    }}
                                    className="form-input form-input-sm w-full"
                                  />
                                </td>
                                <td>
                                  <select
                                    value={field.value_source || 'extracted'}
                                    onChange={(e) => {
                                      const updated = [...fieldMappings]
                                      if (updated[idx]) {
                                        updated[idx] = { ...updated[idx], value_source: e.target.value }
                                        setFieldMappings(updated)
                                      }
                                    }}
                                    className="form-select form-select-sm"
                                  >
                                    <option value="extracted">Extracted</option>
                                    <option value="constant">Constant</option>
                                  </select>
                                </td>
                                <td>
                                  <input
                                    type="checkbox"
                                    checked={field.is_required}
                                    onChange={(e) => {
                                      const updated = [...fieldMappings]
                                      if (updated[idx]) {
                                        updated[idx] = { ...updated[idx], is_required: e.target.checked }
                                        setFieldMappings(updated)
                                      }
                                    }}
                                    className="form-checkbox"
                                  />
                                </td>
                                <td>
                                  {field.value_source === 'constant' ? (
                                    <input
                                      type="text"
                                      value={field.default_value || ''}
                                      onChange={(e) => {
                                        const updated = [...fieldMappings]
                                        if (updated[idx]) {
                                          updated[idx] = { ...updated[idx], default_value: e.target.value }
                                          setFieldMappings(updated)
                                        }
                                      }}
                                      className="form-input form-input-sm w-full"
                                      placeholder="Enter constant value"
                                    />
                                  ) : (
                                    <span className="text-xs text-gray-400">-</span>
                                  )}
                                </td>
                                <td>
                                  <button
                                    onClick={() => handleDeleteField(idx)}
                                    className="text-red-500 hover:text-red-700 p-1"
                                    title="Delete field"
                                  >
                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                    </svg>
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {/* Add Field Form - Uses CD API fields dropdown only */}
                      {showNewFieldForm && (
                        <div className="p-4 border-t bg-blue-50">
                          <h3 className="font-medium text-gray-900 mb-3">Add Central Dispatch Field</h3>
                          <p className="text-xs text-gray-500 mb-3">
                            Only fields from the Central Dispatch API can be added. Custom fields are not supported.
                          </p>
                          <form onSubmit={handleAddField} className="space-y-3">
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <label className="form-label text-xs">CD API Field</label>
                                <select
                                  value={newFieldForm.field_key}
                                  onChange={(e) => {
                                    const selectedField = CD_FIELDS.find(f => f.key === e.target.value)
                                    if (selectedField) {
                                      setNewFieldForm(f => ({
                                        ...f,
                                        field_key: selectedField.key,
                                        display_name: selectedField.label,
                                        field_type: selectedField.type,
                                        is_required: selectedField.required,
                                        description: selectedField.description,
                                      }))
                                    }
                                  }}
                                  className="form-select form-select-sm w-full"
                                  required
                                >
                                  <option value="">Select a field...</option>
                                  {CD_FIELDS
                                    .filter(f => !fieldMappings.some(m => m.field_key === f.key))
                                    .map(f => (
                                      <option key={f.key} value={f.key}>
                                        {f.label} ({f.key})
                                      </option>
                                    ))
                                  }
                                </select>
                              </div>
                              <div>
                                <label className="form-label text-xs">Display Name</label>
                                <input
                                  type="text"
                                  value={newFieldForm.display_name}
                                  onChange={(e) => setNewFieldForm(f => ({ ...f, display_name: e.target.value }))}
                                  className="form-input form-input-sm w-full"
                                  placeholder="Auto-filled from selection"
                                  required
                                />
                              </div>
                            </div>
                            <div className="grid grid-cols-3 gap-3">
                              <div>
                                <label className="form-label text-xs">Type</label>
                                <select
                                  value={newFieldForm.field_type}
                                  onChange={(e) => setNewFieldForm(f => ({ ...f, field_type: e.target.value }))}
                                  className="form-select form-select-sm w-full"
                                  disabled
                                >
                                  <option value="text">Text</option>
                                  <option value="number">Number</option>
                                  <option value="date">Date</option>
                                  <option value="textarea">Text Area</option>
                                  <option value="select">Select</option>
                                </select>
                                <p className="text-xs text-gray-400 mt-1">Auto-set from CD API</p>
                              </div>
                              <div className="flex items-end">
                                <label className="flex items-center space-x-2">
                                  <input
                                    type="checkbox"
                                    checked={newFieldForm.is_required}
                                    onChange={(e) => setNewFieldForm(f => ({ ...f, is_required: e.target.checked }))}
                                    className="form-checkbox"
                                  />
                                  <span className="text-sm">Required</span>
                                </label>
                              </div>
                              <div className="flex items-end justify-end space-x-2">
                                <button type="button" onClick={() => setShowNewFieldForm(false)} className="btn btn-sm btn-secondary">
                                  Cancel
                                </button>
                                <button type="submit" className="btn btn-sm btn-primary" disabled={!newFieldForm.field_key}>
                                  Add Field
                                </button>
                              </div>
                            </div>
                            {newFieldForm.description && (
                              <p className="text-xs text-gray-500 bg-white p-2 rounded border">
                                {newFieldForm.description}
                              </p>
                            )}
                          </form>
                        </div>
                      )}

                      <div className="p-4 border-t bg-gray-50">
                        <div className="flex justify-between items-center mb-3">
                          <div className="text-sm text-gray-500">
                            <span className="font-medium">{fieldMappings.filter(f => f.is_active !== false).length}</span> fields active
                            <span className="mx-2">|</span>
                            <span className="text-blue-600">{fieldMappings.filter(f => f.value_source === 'constant').length}</span> constants
                          </div>
                          <div className="flex space-x-2">
                            <button
                              onClick={() => setShowNewFieldForm(!showNewFieldForm)}
                              className="btn btn-sm btn-secondary"
                            >
                              {showNewFieldForm ? 'Cancel' : '+ Add Field'}
                            </button>
                            <button onClick={handleSaveFieldMappings} className="btn btn-primary">
                              Save Field Mappings
                            </button>
                          </div>
                        </div>
                        <div className="text-xs text-gray-500 bg-white p-2 rounded border">
                          <strong>Tip:</strong> Set fields to "Constant" when the value is always the same for this auction type
                          (e.g., vehicle condition is always "operable" for a specific auction). Extracted fields are read from each document.
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            ) : (
              <div className="card">
                <div className="card-body text-center py-8">
                  <svg className="w-12 h-12 mx-auto text-gray-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                  <p className="text-gray-500 mb-2">Select an auction type to configure field mappings</p>
                  <p className="text-xs text-gray-400">Click on any auction type in the table to configure which fields are extracted and how they map to Central Dispatch API</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Zone Templates Tab */}
      {activeTab === 'zone-templates' && (
        <ZoneTemplatesTab auctionTypes={auctionTypes} />
      )}
    </div>
  )
}

export default TestLab
