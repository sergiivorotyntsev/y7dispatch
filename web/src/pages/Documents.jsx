import { useState, useEffect, useCallback, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import ExportPreviewModal from '../components/ExportPreviewModal'
import { parseUTCDate } from '../utils/date'
import WeatherIndicator from '../components/WeatherIndicator'

/**
 * Documents Page - Production Workflow
 *
 * Lists documents ready for Central Dispatch export.
 * Different from Test Lab which is for training.
 *
 * Key features per ТЗ:
 * - Row click → Review & Posting (not Review & Train)
 * - Batch posting with preflight check
 * - Warehouse dropdown per document
 * - Status progression tracking
 */
// Group documents by date (most recent first)
function groupByDate(docs) {
  const groups = {}
  docs.forEach(doc => {
    const date = doc.created_at
      ? parseUTCDate(doc.created_at).toLocaleDateString('en-US', {
          weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
        })
      : 'Unknown Date'
    if (!groups[date]) groups[date] = []
    groups[date].push(doc)
  })
  return Object.entries(groups)
}

function Documents() {
  const navigate = useNavigate()
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [auctionTypes, setAuctionTypes] = useState([])
  const [warehouses, setWarehouses] = useState([])

  // Track extraction runs per document
  const [docExtractions, setDocExtractions] = useState({})

  // Batch selection
  const [selectedDocs, setSelectedDocs] = useState(new Set())
  const [showBatchPost, setShowBatchPost] = useState(false)
  const [batchPreflight, setBatchPreflight] = useState(null)
  const [batchPosting, setBatchPosting] = useState(false)
  const [batchResult, setBatchResult] = useState(null)

  // Search
  const [search, setSearch] = useState('')
  const [searchDebounced, setSearchDebounced] = useState('')

  // Filters and pagination
  const [filter, setFilter] = useState({
    auction_type_id: '',
    status: '',
    export_status: '',
  })
  const [pagination, setPagination] = useState({
    page: 1,
    limit: 25,
    total: 0,
  })
  const [sortConfig, setSortConfig] = useState({
    sortBy: 'created_at',
    sortOrder: 'desc',
  })

  // Stats
  const [stats, setStats] = useState({
    total: 0,
    needs_review: 0,
    ready_to_export: 0,
    exported: 0,
  })

  // Upload state
  const [showUpload, setShowUpload] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [selectedAuctionType, setSelectedAuctionType] = useState('auto')
  const [uploadResult, setUploadResult] = useState(null)

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setSearchDebounced(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  // Fetch documents with stale-while-revalidate caching
  const fetchDocuments = useCallback(async () => {
    const cacheKey = 'y7_documents_cache'
    // On first load with no active filter, try showing cached data instantly (no spinner)
    // Only use cache when no filter/search is active to avoid showing wrong data
    const hasFilter = filter.status || filter.auction_type_id || searchDebounced.trim()
    if (loading && documents.length === 0 && !hasFilter) {
      try {
        const cached = sessionStorage.getItem(cacheKey)
        if (cached) {
          const { docs: cachedDocs, total: cachedTotal } = JSON.parse(cached)
          if (cachedDocs?.length > 0) {
            setDocuments(cachedDocs)
            setPagination(p => ({ ...p, total: cachedTotal || cachedDocs.length }))
            setLoading(false)
          }
        }
      } catch { /* ignore parse errors */ }
    }
    // Only show spinner if no documents are currently displayed
    if (documents.length === 0) setLoading(true)
    setError(null)
    try {
      const params = {
        dataset_split: 'train',
        limit: pagination.limit,
        offset: (pagination.page - 1) * pagination.limit,
      }
      if (filter.auction_type_id) params.auction_type_id = filter.auction_type_id
      if (searchDebounced.trim()) params.search = searchDebounced.trim()
      if (filter.status === 'archived') params.include_archived = true

      const result = await api.listDocuments(params)
      // Filter out test documents
      let prodDocs = (result.items || []).filter(d => !d.is_test)

      // Client-side status filtering
      if (filter.status) {
        prodDocs = prodDocs.filter(doc => {
          if (filter.status === 'hold') return !!doc.hold_reason
          if (filter.status === 'pending') return !!doc.pending_reason && !doc.hold_reason
          if (filter.status === 'archived') return !!doc.archived_at
          // For extraction statuses, check the extraction status
          const ext = docExtractions[doc.id]
          const extStatus = doc.extraction_status || ext?.status
          return extStatus === filter.status
        })
      }

      // Sort documents client-side
      const sorted = [...prodDocs].sort((a, b) => {
        const aVal = a[sortConfig.sortBy] || ''
        const bVal = b[sortConfig.sortBy] || ''
        const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
        return sortConfig.sortOrder === 'desc' ? -cmp : cmp
      })

      setDocuments(sorted)
      setPagination(p => ({ ...p, total: result.total || prodDocs.length }))

      // Save to sessionStorage only when showing unfiltered data
      // so cache always has the full document list
      if (!hasFilter) {
        try {
          sessionStorage.setItem(cacheKey, JSON.stringify({
            docs: sorted, total: result.total || prodDocs.length,
          }))
        } catch { /* storage full — ignore */ }
      }

      // Calculate stats
      setStats({
        total: result.total || prodDocs.length,
        needs_review: 0,
        ready_to_export: 0,
        exported: 0,
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [filter, pagination.page, pagination.limit, sortConfig, searchDebounced])

  // Fetch auction types and warehouses
  useEffect(() => {
    async function fetchData() {
      try {
        const [atResult, whResult] = await Promise.all([
          api.listAuctionTypes(),
          api.listWarehouses(),
        ])
        setAuctionTypes(atResult.items || [])
        setWarehouses(whResult.items || [])
      } catch (err) {
        console.error('Failed to fetch data:', err)
      }
    }
    fetchData()
  }, [])

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  // Fetch latest extraction status for each document (production only)
  const fetchDocExtractions = useCallback(async () => {
    try {
      // Only load extractions from production documents (is_test=false)
      // This ensures Documents page doesn't show Test Lab extractions
      const result = await api.listExtractions({ limit: 200, is_test: false })
      const extractionsByDoc = {}
      let needsReview = 0
      let readyToExport = 0
      let exported = 0

      // Get set of production document IDs (additional client-side filter)
      const prodDocIds = new Set(documents.map(d => d.id))

      for (const run of (result.items || [])) {
        // Skip extraction runs from test/training documents
        if (!prodDocIds.has(run.document_id)) continue

        // Keep the latest extraction per document
        if (!extractionsByDoc[run.document_id] || run.id > extractionsByDoc[run.document_id].id) {
          extractionsByDoc[run.document_id] = run
        }

        // Count stats (only for production documents)
        if (run.status === 'needs_review') needsReview++
        else if (run.status === 'reviewed' || run.status === 'approved') readyToExport++
        else if (run.status === 'exported') exported++
      }

      setDocExtractions(extractionsByDoc)
      setStats(prev => ({
        ...prev,
        needs_review: needsReview,
        ready_to_export: readyToExport,
        exported: exported,
      }))
    } catch (err) {
      console.error('Failed to fetch extractions:', err)
    }
  }, [documents])

  useEffect(() => {
    fetchDocExtractions()
  }, [fetchDocExtractions, documents])

  // Handle upload
  async function handleUpload() {
    if (!uploadFile) return

    setUploading(true)
    setUploadResult(null)
    try {
      const auctionTypeId = selectedAuctionType === 'auto' ? null : parseInt(selectedAuctionType)
      // Use 'train' split for production documents (not test)
      const result = await api.uploadDocument(uploadFile, auctionTypeId, 'train')

      setUploadResult({
        success: true,
        document: result.document,
        detectedSource: result.detected_source,
        classificationScore: result.classification_score,
        isDuplicate: result.is_duplicate,
        runStatus: result.run_status,
        runId: result.run_id,
        vinDuplicate: result.vin_duplicate,
      })

      setUploadFile(null)
      fetchDocuments()
      fetchDocExtractions()
    } catch (err) {
      setError(`Upload failed: ${err.message}`)
      setUploadResult({ success: false, error: err.message })
    } finally {
      setUploading(false)
    }
  }

  // Extraction state
  const [extractingDocId, setExtractingDocId] = useState(null)

  // Inline editing state
  const [editingPrice, setEditingPrice] = useState({ docId: null, value: '' })
  const [exportingDocId, setExportingDocId] = useState(null)

  // Hold modal state
  const [holdModal, setHoldModal] = useState(null) // { docId }
  const [holdReason, setHoldReason] = useState('awaiting_gate_pass')
  const [holdNote, setHoldNote] = useState('')

  // Batch operations state
  const [batchOperating, setBatchOperating] = useState(false)
  const [batchOpResult, setBatchOpResult] = useState(null) // { action, total, succeeded, failed, results }
  const [showBatchHold, setShowBatchHold] = useState(false)
  const [batchHoldReason, setBatchHoldReason] = useState('awaiting_gate_pass')
  const [batchHoldNote, setBatchHoldNote] = useState('')

  // Date grouping
  const [collapsedDates, setCollapsedDates] = useState(new Set())

  function toggleDate(date) {
    setCollapsedDates(prev => {
      const next = new Set(prev)
      next.has(date) ? next.delete(date) : next.add(date)
      return next
    })
  }

  function collapseAll() {
    const allDates = groupByDate(documents).map(([date]) => date)
    setCollapsedDates(new Set(allDates))
  }

  function expandAll() {
    setCollapsedDates(new Set())
  }

  // Export preview modal
  const [showExportPreview, setShowExportPreview] = useState(null) // { extractionId, documentId }

  // Run extraction on document
  async function handleRunExtraction(docId, forceNew = false) {
    const existingExtraction = docExtractions[docId]
    if (existingExtraction && !forceNew) {
      if (existingExtraction.status === 'needs_review') {
        navigate(`/review/${existingExtraction.id}`)
        return
      } else if (['reviewed', 'approved'].includes(existingExtraction.status)) {
        if (!confirm('Document already processed. Run extraction again?')) return
      }
    }

    setExtractingDocId(docId)
    try {
      const result = await api.runExtraction(docId)
      // Navigate to review page after extraction
      if (result?.run_id) {
        navigate(`/review/${result.run_id}`)
      } else {
        fetchDocuments()
        fetchDocExtractions()
      }
    } catch (err) {
      setError(`Extraction failed: ${err.message}`)
    } finally {
      setExtractingDocId(null)
    }
  }

  // Update warehouse for document - also populates delivery fields
  async function handleWarehouseChange(docId, warehouseId, e) {
    e.stopPropagation()
    const extraction = docExtractions[docId]
    if (!extraction) return

    try {
      const whId = warehouseId ? parseInt(warehouseId, 10) : null
      const currentOutputs = extraction.outputs || {}

      if (whId) {
        // Find selected warehouse to get delivery info
        const selectedWarehouse = warehouses.find(w => w.id === whId)

        // Update extraction with warehouse AND delivery fields from warehouse
        const updateData = {
          warehouse_id: whId,
          outputs_json: {
            ...currentOutputs,
            warehouse_id: whId,
            delivery_name: selectedWarehouse?.name || '',
            delivery_address: selectedWarehouse?.address || '',
            delivery_city: selectedWarehouse?.city || '',
            delivery_state: selectedWarehouse?.state || '',
            delivery_zip: selectedWarehouse?.zip_code || '',
          }
        }

        await api.updateExtraction(extraction.id, updateData)
      } else {
        // Clear warehouse selection
        const cleared = { ...currentOutputs }
        delete cleared.warehouse_id
        delete cleared.delivery_name
        delete cleared.delivery_address
        delete cleared.delivery_city
        delete cleared.delivery_state
        delete cleared.delivery_zip
        await api.updateExtraction(extraction.id, { outputs_json: cleared })
      }
      // Optimistic local state update — no full refetch needed
      const selectedWarehouse = whId ? warehouses.find(w => w.id === whId) : null
      setDocExtractions(prev => {
        const ext = prev[docId]
        if (!ext) return prev
        const updatedOutputs = whId ? {
          ...ext.outputs,
          warehouse_id: whId,
          delivery_name: selectedWarehouse?.name || '',
          delivery_address: selectedWarehouse?.address || '',
          delivery_city: selectedWarehouse?.city || '',
          delivery_state: selectedWarehouse?.state || '',
          delivery_zip: selectedWarehouse?.zip_code || '',
        } : (() => {
          const c = { ...ext.outputs }
          delete c.warehouse_id
          delete c.delivery_name
          delete c.delivery_address
          delete c.delivery_city
          delete c.delivery_state
          delete c.delivery_zip
          return c
        })()
        return { ...prev, [docId]: { ...ext, outputs: updatedOutputs } }
      })
      setDocuments(prev => prev.map(d =>
        d.id === docId
          ? { ...d, warehouse_id: whId, warehouse_name: selectedWarehouse?.name || null }
          : d
      ))
    } catch (err) {
      console.error('Failed to update warehouse:', err)
      setError(`Failed to update warehouse: ${err.message}`)
      // Revert on error — refetch to get true state
      fetchDocuments()
      fetchDocExtractions()
    }
  }

  // Delete document
  async function handleDelete(docId, e) {
    e.stopPropagation()
    if (!confirm('Delete this document and all related data?')) return
    try {
      await api.deleteDocument(docId)
      fetchDocuments()
    } catch (err) {
      setError(`Delete failed: ${err.message}`)
    }
  }

  // Hold document
  async function handleSetHold(docId) {
    try {
      await api.setHold(docId, holdReason, holdNote || null)
      setHoldModal(null)
      setHoldReason('awaiting_gate_pass')
      setHoldNote('')
      fetchDocuments()
    } catch (err) {
      setError(`Hold failed: ${err.message}`)
    }
  }

  // Release hold
  async function handleReleaseHold(docId, e) {
    e.stopPropagation()
    try {
      await api.releaseHold(docId)
      fetchDocuments()
    } catch (err) {
      setError(`Release hold failed: ${err.message}`)
    }
  }

  // Archive document (soft delete for exported)
  async function handleArchive(docId, e) {
    e.stopPropagation()
    if (!confirm('Archive this document? It will be hidden from the main list.')) return
    try {
      await api.archiveDocument(docId)
      fetchDocuments()
    } catch (err) {
      setError(`Archive failed: ${err.message}`)
    }
  }

  // Handle inline price editing
  async function handlePriceUpdate(docId, e) {
    e.stopPropagation()
    const extraction = docExtractions[docId]
    if (!extraction) return

    const newPrice = parseFloat(editingPrice.value)
    if (isNaN(newPrice) || newPrice < 0) {
      setEditingPrice({ docId: null, value: '' })
      return
    }

    try {
      // Price must be inside outputs_json
      await api.updateExtraction(extraction.id, { outputs_json: { price_total: newPrice } })
      fetchDocExtractions()
    } catch (err) {
      setError(`Price update failed: ${err.message}`)
    } finally {
      setEditingPrice({ docId: null, value: '' })
    }
  }

  // Handle direct export to CD
  async function handleExportToCD(docId, e) {
    e.stopPropagation()
    const extraction = docExtractions[docId]
    if (!extraction) return

    setExportingDocId(docId)
    try {
      // Use exportToCD with dry_run=false, sandbox=true (safe default)
      await api.exportToCD([extraction.id], false, true)
      fetchDocExtractions()
    } catch (err) {
      setError(`Export failed: ${err.message}`)
    } finally {
      setExportingDocId(null)
    }
  }

  // Batch selection handlers
  function toggleSelectDoc(docId, e) {
    e.stopPropagation()
    setSelectedDocs(prev => {
      const newSet = new Set(prev)
      if (newSet.has(docId)) {
        newSet.delete(docId)
      } else {
        newSet.add(docId)
      }
      return newSet
    })
  }

  function toggleSelectAll() {
    if (selectedDocs.size === documents.length) {
      setSelectedDocs(new Set())
    } else {
      setSelectedDocs(new Set(documents.map(d => d.id)))
    }
  }

  // Get selected run IDs
  function getSelectedRunIds() {
    return Array.from(selectedDocs)
      .map(docId => docExtractions[docId]?.id)
      .filter(Boolean)
  }

  // Batch posting preflight
  async function handleBatchPostPreflight() {
    const runIds = getSelectedRunIds()
    if (runIds.length === 0) {
      setError('No documents with extractions selected')
      return
    }

    setBatchPosting(true)
    setBatchPreflight(null)
    setBatchResult(null)

    try {
      const result = await api.batchPostPreflight(runIds)
      setBatchPreflight(result)
      setShowBatchPost(true)
    } catch (err) {
      setError(`Preflight check failed: ${err.message}`)
    } finally {
      setBatchPosting(false)
    }
  }

  // Execute batch posting
  async function handleBatchPost(postOnlyReady = true) {
    const runIds = getSelectedRunIds()
    setBatchPosting(true)

    try {
      const result = await api.batchPost(runIds, postOnlyReady, true)
      setBatchResult(result)

      // Refresh data
      fetchDocuments()
      fetchDocExtractions()
    } catch (err) {
      setError(`Batch post failed: ${err.message}`)
    } finally {
      setBatchPosting(false)
    }
  }

  function closeBatchPostModal() {
    setShowBatchPost(false)
    setBatchPreflight(null)
    setBatchResult(null)
    setSelectedDocs(new Set())
  }

  // Batch eligibility: compute counts for each action from selected docs
  function getBatchEligibility() {
    const approveRunIds = []
    const exportRunIds = []
    const holdDocIds = []
    const archiveDocIds = []

    for (const docId of selectedDocs) {
      const doc = documents.find(d => d.id === docId)
      if (!doc) continue
      const extraction = docExtractions[docId]
      const extStatus = doc.extraction_status || extraction?.status
      const isExported = extStatus === 'exported'
      const isOnHold = !!doc.hold_reason
      const isArchived = !!doc.archived_at
      const runId = doc.extraction_run_id || extraction?.id

      // Approve: needs_review status with a run_id
      if (runId && extStatus === 'needs_review') {
        approveRunIds.push(runId)
      }
      // Export: approved/reviewed status
      if (runId && (extStatus === 'reviewed' || extStatus === 'approved')) {
        exportRunIds.push(runId)
      }
      // Hold: not exported, not archived
      if (!isExported && !isArchived && !isOnHold) {
        holdDocIds.push(docId)
      }
      // Archive: exported docs
      if (isExported && !isArchived) {
        archiveDocIds.push(docId)
      }
    }
    return { approveRunIds, exportRunIds, holdDocIds, archiveDocIds }
  }

  // Batch approve
  async function handleBatchApprove() {
    const { approveRunIds } = getBatchEligibility()
    if (approveRunIds.length === 0) return

    setBatchOperating(true)
    setBatchOpResult(null)
    try {
      const result = await api.batchApprove(approveRunIds)
      setBatchOpResult({ action: 'approve', ...result })
      fetchDocuments()
      fetchDocExtractions()
      setSelectedDocs(new Set())
    } catch (err) {
      setError(`Batch approve failed: ${err.message}`)
    } finally {
      setBatchOperating(false)
    }
  }

  // Batch hold (opens modal first)
  async function handleBatchHoldConfirm() {
    const { holdDocIds } = getBatchEligibility()
    if (holdDocIds.length === 0) return

    setBatchOperating(true)
    setBatchOpResult(null)
    try {
      const result = await api.batchHold(holdDocIds, batchHoldReason, batchHoldNote || null)
      setBatchOpResult({ action: 'hold', ...result })
      setShowBatchHold(false)
      setBatchHoldReason('awaiting_gate_pass')
      setBatchHoldNote('')
      fetchDocuments()
      setSelectedDocs(new Set())
    } catch (err) {
      setError(`Batch hold failed: ${err.message}`)
    } finally {
      setBatchOperating(false)
    }
  }

  // Batch archive
  async function handleBatchArchive() {
    const { archiveDocIds } = getBatchEligibility()
    if (archiveDocIds.length === 0) return
    if (!confirm(`Archive ${archiveDocIds.length} document(s)? They will be hidden from the main list.`)) return

    setBatchOperating(true)
    setBatchOpResult(null)
    try {
      const result = await api.batchArchive(archiveDocIds)
      setBatchOpResult({ action: 'archive', ...result })
      fetchDocuments()
      setSelectedDocs(new Set())
    } catch (err) {
      setError(`Batch archive failed: ${err.message}`)
    } finally {
      setBatchOperating(false)
    }
  }

  // Get source display
  function getSourceDisplay(doc) {
    if (doc.source === 'email') {
      return { label: 'Email', color: 'bg-blue-100 text-blue-800' }
    } else if (doc.source === 'webhook') {
      return { label: 'Webhook', color: 'bg-purple-100 text-purple-800' }
    } else if (doc.source === 'test_lab') {
      return { label: 'Test Lab', color: 'bg-yellow-100 text-yellow-800' }
    }
    return { label: 'Manual', color: 'bg-gray-100 text-gray-800' }
  }

  // Get export status
  function getExportStatus(extraction) {
    if (!extraction) return { label: 'No Data', color: 'bg-gray-100 text-gray-500' }

    if (extraction.status === 'exported') {
      return { label: 'Exported', color: 'bg-green-100 text-green-800' }
    } else if (extraction.status === 'reviewed' || extraction.status === 'approved') {
      return { label: 'Ready', color: 'bg-blue-100 text-blue-800' }
    } else if (extraction.status === 'needs_review') {
      return { label: 'Pending', color: 'bg-yellow-100 text-yellow-800' }
    } else if (extraction.status === 'failed') {
      return { label: 'Failed', color: 'bg-red-100 text-red-800' }
    }
    return { label: extraction.status, color: 'bg-gray-100 text-gray-600' }
  }

  // Navigate to listing review page or run extraction
  function handleRowClick(doc) {
    const extraction = docExtractions[doc.id]
    if (extraction) {
      navigate(`/review/${extraction.id}`)
    } else {
      // No extraction yet - run extraction first
      handleRunExtraction(doc.id)
    }
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="text-sm text-gray-500 mt-1">
            Production documents for Central Dispatch export
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowUpload(true)}
            className="btn btn-primary"
          >
            Upload Document
          </button>
        </div>
      </div>

      {/* Batch Action Toolbar — appears when documents are selected */}
      {selectedDocs.size > 0 && (() => {
        const elig = getBatchEligibility()
        return (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-3 flex-wrap sticky top-0 z-10">
            <span className="text-sm font-medium text-blue-800">
              {selectedDocs.size} selected
            </span>
            <div className="h-5 w-px bg-blue-300" />
            {elig.approveRunIds.length > 0 && (
              <button
                onClick={handleBatchApprove}
                disabled={batchOperating}
                className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
              >
                {batchOperating ? '...' : `Approve (${elig.approveRunIds.length})`}
              </button>
            )}
            {elig.exportRunIds.length > 0 && (
              <button
                onClick={handleBatchPostPreflight}
                disabled={batchPosting}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {batchPosting ? '...' : `Export (${elig.exportRunIds.length})`}
              </button>
            )}
            {elig.holdDocIds.length > 0 && (
              <button
                onClick={() => setShowBatchHold(true)}
                disabled={batchOperating}
                className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
              >
                Hold ({elig.holdDocIds.length})
              </button>
            )}
            {elig.archiveDocIds.length > 0 && (
              <button
                onClick={handleBatchArchive}
                disabled={batchOperating}
                className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
              >
                Archive ({elig.archiveDocIds.length})
              </button>
            )}
            <button
              onClick={() => setSelectedDocs(new Set())}
              className="ml-auto text-sm text-blue-600 hover:text-blue-800"
            >
              Clear Selection
            </button>
          </div>
        )
      })()}

      {/* Batch Operation Result Banner */}
      {batchOpResult && (
        <div className={`mb-4 p-3 rounded-lg border ${
          batchOpResult.failed === 0
            ? 'bg-green-50 border-green-200'
            : 'bg-yellow-50 border-yellow-200'
        }`}>
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <span className="font-medium">
                Batch {batchOpResult.action}: {batchOpResult.succeeded}/{batchOpResult.total} succeeded
              </span>
              {batchOpResult.failed > 0 && (
                <span className="text-red-600 ml-2">({batchOpResult.failed} failed)</span>
              )}
            </div>
            <button
              onClick={() => setBatchOpResult(null)}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Dismiss
            </button>
          </div>
          {batchOpResult.results?.some(r => !r.success) && (
            <div className="mt-2 space-y-1">
              {batchOpResult.results.filter(r => !r.success).map((r, i) => (
                <div key={i} className="text-xs text-red-700">
                  ID {r.id}: {r.error}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {error}
          <button onClick={() => setError(null)} className="ml-4 text-sm underline">Dismiss</button>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Total</p>
          <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Needs Review</p>
          <p className="text-2xl font-bold text-yellow-600">{stats.needs_review}</p>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Ready to Export</p>
          <p className="text-2xl font-bold text-blue-600">{stats.ready_to_export}</p>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Exported</p>
          <p className="text-2xl font-bold text-green-600">{stats.exported}</p>
        </div>
      </div>

      {/* Search + Filters */}
      <div className="bg-white p-4 rounded-lg shadow mb-6">
        <div className="mb-3">
          <input
            type="text"
            placeholder="Search by VIN, make, model, lot, or gate pass..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPagination(p => ({ ...p, page: 1 })) }}
            className="form-input w-full text-sm"
          />
        </div>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Auction Type</label>
            <select
              value={filter.auction_type_id}
              onChange={(e) => { setFilter({ ...filter, auction_type_id: e.target.value }); setPagination(p => ({ ...p, page: 1 })) }}
              className="form-select"
            >
              <option value="">All Types</option>
              {auctionTypes.map((at) => (
                <option key={at.id} value={at.id}>{at.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <select
              value={filter.status}
              onChange={(e) => { setFilter({ ...filter, status: e.target.value }); setPagination(p => ({ ...p, page: 1 })) }}
              className="form-select"
            >
              <option value="">All Status</option>
              <option value="needs_review">Needs Review</option>
              <option value="reviewed">Ready to Export</option>
              <option value="exported">Exported</option>
              <option value="manual_required">OCR Required</option>
              <option value="pending">Pending</option>
              <option value="hold">On Hold</option>
              <option value="failed">Failed</option>
              <option value="archived">Archived</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Sort By</label>
            <select
              value={`${sortConfig.sortBy}-${sortConfig.sortOrder}`}
              onChange={(e) => {
                const [sortBy, sortOrder] = e.target.value.split('-')
                setSortConfig({ sortBy, sortOrder })
              }}
              className="form-select"
            >
              <option value="created_at-desc">Newest First</option>
              <option value="created_at-asc">Oldest First</option>
              <option value="filename-asc">Filename A-Z</option>
              <option value="filename-desc">Filename Z-A</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Per Page</label>
            <select
              value={pagination.limit}
              onChange={(e) => setPagination(p => ({ ...p, limit: parseInt(e.target.value), page: 1 }))}
              className="form-select"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
          <button onClick={fetchDocuments} className="btn btn-secondary">
            Refresh
          </button>
          <button onClick={expandAll} className="btn btn-secondary text-xs" title="Expand all date groups">
            Expand All
          </button>
          <button onClick={collapseAll} className="btn btn-secondary text-xs" title="Collapse all date groups">
            Collapse All
          </button>
        </div>
      </div>

      {/* Upload Modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-lg w-full mx-4">
            <h2 className="text-xl font-bold mb-4">Upload Document</h2>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Auction Type</label>
              <select
                value={selectedAuctionType}
                onChange={(e) => setSelectedAuctionType(e.target.value)}
                className="form-select w-full"
              >
                <option value="auto">Auto-detect (Recommended)</option>
                {auctionTypes.map((at) => (
                  <option key={at.id} value={at.id}>{at.name}</option>
                ))}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">PDF File</label>
              <input
                type="file"
                accept=".pdf"
                onChange={(e) => {
                  setUploadFile(e.target.files[0])
                  setUploadResult(null)
                }}
                className="form-input w-full"
              />
            </div>

            {uploadResult && (
              <div className={`mb-4 p-3 rounded-lg ${
                uploadResult.vinDuplicate ? 'bg-orange-50 border border-orange-200' :
                uploadResult.success ? 'bg-green-50 border border-green-200' :
                'bg-red-50 border border-red-200'
              }`}>
                {uploadResult.success ? (
                  <div>
                    <p className={`font-medium ${uploadResult.vinDuplicate ? 'text-orange-800' : 'text-green-800'}`}>
                      {uploadResult.vinDuplicate ? '⚠️ Upload successful - Duplicate VIN detected!' : 'Upload successful!'}
                    </p>
                    {uploadResult.detectedSource && (
                      <p className="text-sm text-green-700 mt-1">
                        Detected: <strong>{uploadResult.detectedSource}</strong>
                      </p>
                    )}
                    {uploadResult.vinDuplicate && (
                      <div className="mt-2 p-2 bg-orange-100 rounded text-sm text-orange-800">
                        <p className="font-medium">This VIN already exists in another document:</p>
                        <p className="mt-1">
                          VIN: <code className="font-mono bg-orange-200 px-1 rounded">{uploadResult.vinDuplicate.vin}</code>
                        </p>
                        <p>
                          Vehicle: {uploadResult.vinDuplicate.vehicle_year} {uploadResult.vinDuplicate.vehicle_make} {uploadResult.vinDuplicate.vehicle_model}
                        </p>
                        <p>File: {uploadResult.vinDuplicate.document_filename}</p>
                        <button
                          onClick={() => {
                            setShowUpload(false)
                            navigate(`/review/${uploadResult.vinDuplicate.run_id}`)
                          }}
                          className="mt-2 text-orange-700 underline hover:text-orange-900"
                        >
                          View existing listing →
                        </button>
                      </div>
                    )}
                    {uploadResult.runId && !uploadResult.vinDuplicate && (
                      <button
                        onClick={() => {
                          setShowUpload(false)
                          navigate(`/review/${uploadResult.runId}`)
                        }}
                        className="mt-2 text-green-700 underline hover:text-green-900"
                      >
                        Review extracted data →
                      </button>
                    )}
                  </div>
                ) : (
                  <p className="text-red-800">{uploadResult.error}</p>
                )}
              </div>
            )}

            <div className="flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowUpload(false)
                  setUploadFile(null)
                  setUploadResult(null)
                }}
                className="btn btn-secondary"
                disabled={uploading}
              >
                {uploadResult?.success ? 'Close' : 'Cancel'}
              </button>
              {!uploadResult?.success && (
                <button
                  onClick={handleUpload}
                  className="btn btn-primary"
                  disabled={!uploadFile || uploading}
                >
                  {uploading ? 'Uploading...' : 'Upload'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Documents Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
          <span className="ml-3 text-gray-600">Loading documents...</span>
        </div>
      ) : documents.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <p className="text-gray-500 mb-4">No documents found</p>
          <button onClick={() => setShowUpload(true)} className="btn btn-primary">
            Upload First Document
          </button>
        </div>
      ) : (
        <>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-3">
                  <input
                    type="checkbox"
                    checked={selectedDocs.size === documents.length && documents.length > 0}
                    onChange={toggleSelectAll}
                    className="form-checkbox h-4 w-4 text-primary-600"
                  />
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Load ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  VIN
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Vehicle
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Auction
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Pickup
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Warehouse
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Auction Cost
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Transport
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  $/mile
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Source
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Created
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {groupByDate(documents).map(([date, dateDocs]) => {
                const isCollapsed = collapsedDates.has(date)
                return (
                  <Fragment key={date}>
                    {/* Date group header */}
                    <tr
                      className="bg-gray-100 cursor-pointer hover:bg-gray-200"
                      onClick={() => toggleDate(date)}
                    >
                      <td colSpan={13} className="px-4 py-2">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold text-gray-700">
                            {date} <span className="font-normal text-gray-500">({dateDocs.length} {dateDocs.length === 1 ? 'load' : 'loads'})</span>
                          </span>
                          <span className="text-gray-400 text-xs">{isCollapsed ? '\u25B6' : '\u25BC'}</span>
                        </div>
                      </td>
                    </tr>
                    {/* Document rows */}
                    {!isCollapsed && dateDocs.map((doc) => {
                const extraction = docExtractions[doc.id]
                const isPending = !!doc.pending_reason
                const isOnHold = !!doc.hold_reason
                // Use enriched data from API, fall back to extraction outputs
                const rawOutputs = extraction?.outputs || extraction?.outputs_json
                const outputs = rawOutputs ? (
                  typeof rawOutputs === 'string'
                    ? JSON.parse(rawOutputs)
                    : rawOutputs
                ) : {}

                const loadId = doc.load_id || outputs.load_id || ''
                const vin = doc.vin || outputs.vehicle_vin || ''
                const vehicleYear = doc.vehicle_year || outputs.vehicle_year || ''
                const vehicleMake = doc.vehicle_make || outputs.vehicle_make || ''
                const vehicleModel = doc.vehicle_model || outputs.vehicle_model || ''
                const vehicleDesc = vehicleYear || vehicleMake || vehicleModel
                  ? `${vehicleYear} ${vehicleMake} ${vehicleModel}`.trim()
                  : '-'
                const lotNumber = doc.vehicle_lot || outputs.vehicle_lot || ''
                const gatePass = doc.gate_pass || outputs.gate_pass || ''

                const pickupCity = doc.pickup_city || outputs.pickup_city || ''
                const pickupState = doc.pickup_state || outputs.pickup_state || ''
                const pickupName = doc.pickup_name || outputs.pickup_name || ''
                const pickupLocation = pickupCity && pickupState
                  ? `${pickupCity}, ${pickupState}`
                  : pickupName || pickupState || '-'
                // Transport price (canonical: transport_price from API, fallback to outputs)
                const priceTotal = doc.transport_price != null ? doc.transport_price
                  : doc.price_total != null ? doc.price_total
                  : outputs.price_total != null ? outputs.price_total
                  : null

                // Auction cost (vehicle purchase price) — display only, not editable
                const auctionCost = doc.auction_cost != null ? doc.auction_cost
                  : outputs.total_amount != null ? parseFloat(outputs.total_amount)
                  : null

                // Distance and rate per mile (prefer API-computed, fallback to local)
                const distanceMiles = doc.distance_miles != null ? doc.distance_miles
                  : outputs.distance_miles != null ? parseFloat(outputs.distance_miles)
                  : null
                const ratePerMile = doc.rate_per_mile != null ? doc.rate_per_mile
                  : (priceTotal != null && distanceMiles > 0) ? (priceTotal / distanceMiles).toFixed(2)
                  : null

                // Warehouse/Delivery info — prefer enriched doc.warehouse_name, fall back to lookup
                const warehouseId = doc.warehouse_id || outputs.warehouse_id
                const warehouseName = doc.warehouse_name || (warehouseId ? (warehouses.find(w => w.id === parseInt(warehouseId))?.name || '') : '')

                const sourceDisplay = getSourceDisplay(doc)
                // Use enriched extraction_status or fall back to extraction object
                const extStatus = doc.extraction_status || extraction?.status
                const extRunId = doc.extraction_run_id || extraction?.id
                const isExported = extStatus === 'exported'
                const isReady = extStatus && ['reviewed', 'approved'].includes(extStatus)

                return (
                  <tr
                    key={doc.id}
                    className={`hover:bg-gray-50 cursor-pointer ${selectedDocs.has(doc.id) ? 'bg-blue-50' : ''}`}
                    onClick={() => handleRowClick(doc)}
                  >
                    <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedDocs.has(doc.id)}
                        onChange={(e) => toggleSelectDoc(doc.id, e)}
                        className="form-checkbox h-4 w-4 text-primary-600"
                      />
                    </td>
                    <td className="px-3 py-3">
                      <span className="font-mono text-xs font-medium text-primary-700">
                        {loadId || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-gray-900" title={vin}>
                        {vin || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col">
                        <span className="text-sm font-medium text-gray-900">{vehicleDesc}</span>
                        {lotNumber && (
                          <span className="text-xs text-gray-500">Lot: {lotNumber}</span>
                        )}
                        {gatePass && (
                          <span className="text-xs text-gray-500">GP: {gatePass}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 text-xs font-medium rounded ${
                        doc.auction_type_code === 'COPART' ? 'bg-blue-100 text-blue-800' :
                        doc.auction_type_code === 'IAA' ? 'bg-purple-100 text-purple-800' :
                        doc.auction_type_code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {doc.auction_type_code || '?'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm text-gray-700">{pickupLocation}</span>
                    </td>
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <select
                        value={warehouseId || ''}
                        onChange={(e) => handleWarehouseChange(doc.id, e.target.value, e)}
                        disabled={isExported || !extraction}
                        className={`form-select form-select-sm text-xs ${
                          isExported ? 'bg-gray-100 cursor-not-allowed' : ''
                        } ${!warehouseId ? 'border-orange-300' : ''}`}
                      >
                        <option value="">{warehouseName || 'Select...'}</option>
                        {warehouses.map((wh) => (
                          <option key={wh.id} value={wh.id}>
                            {wh.state} - {wh.name} ({wh.city})
                          </option>
                        ))}
                      </select>
                      {warehouseId && warehouseName && (() => {
                        const wh = warehouses.find(w => w.id === parseInt(warehouseId))
                        return wh ? (
                          <div className="text-xs text-gray-400 mt-0.5 flex items-center">
                            <span>{wh.city || ''}{wh.state ? `, ${wh.state}` : ''}</span>
                            <WeatherIndicator runId={extRunId} warehouseId={warehouseId} />
                          </div>
                        ) : null
                      })()}
                    </td>
                    {/* Auction Cost — read-only display */}
                    <td className="px-4 py-3 text-right text-sm text-gray-500">
                      {auctionCost != null ? `$${parseFloat(auctionCost).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : '\u2014'}
                    </td>
                    {/* Transport — editable price */}
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      {editingPrice.docId === doc.id ? (
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={editingPrice.value}
                          onChange={(e) => setEditingPrice({ docId: doc.id, value: e.target.value })}
                          onBlur={(e) => handlePriceUpdate(doc.id, e)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handlePriceUpdate(doc.id, e)
                            if (e.key === 'Escape') setEditingPrice({ docId: null, value: '' })
                          }}
                          autoFocus
                          className="form-input w-24 text-sm px-2 py-1 border-primary-500"
                          placeholder="0.00"
                        />
                      ) : (
                        <button
                          className={`text-sm ${priceTotal != null ? 'font-medium text-gray-900' : 'text-gray-400'} ${
                            !isExported && extraction ? 'hover:text-primary-600 cursor-pointer' : ''
                          }`}
                          onClick={(e) => {
                            if (!isExported && extraction) {
                              e.stopPropagation()
                              setEditingPrice({ docId: doc.id, value: priceTotal != null ? priceTotal : '' })
                            }
                          }}
                          disabled={isExported || !extraction}
                        >
                          {priceTotal != null ? `$${parseFloat(priceTotal).toFixed(0)}` : '\u2014'}
                        </button>
                      )}
                    </td>
                    {/* $/mile — computed */}
                    <td className="px-4 py-3 text-right text-sm text-gray-500">
                      {ratePerMile != null ? `$${ratePerMile}` : '\u2014'}
                    </td>
                    <td className="px-4 py-3">
                      {isOnHold && (
                        <span className="px-2 py-1 text-xs font-medium rounded bg-red-100 text-red-800 mr-1" title={`${doc.hold_reason}${doc.hold_note ? ': ' + doc.hold_note : ''}`}>
                          HOLD
                        </span>
                      )}
                      {isPending && !isOnHold && (
                        <span className="px-2 py-1 text-xs font-medium rounded bg-amber-100 text-amber-800 mr-1" title={doc.pending_reason}>
                          Pending
                        </span>
                      )}
                      <span className={`px-2 py-1 text-xs font-medium rounded ${
                        extStatus === 'needs_review' ? 'bg-yellow-100 text-yellow-800' :
                        extStatus === 'reviewed' || extStatus === 'approved' ? 'bg-green-100 text-green-800' :
                        extStatus === 'exported' ? 'bg-blue-100 text-blue-800' :
                        extStatus === 'manual_required' ? 'bg-orange-100 text-orange-800' :
                        extStatus === 'failed' ? 'bg-red-100 text-red-800' :
                        'bg-gray-100 text-gray-600'
                      }`}>
                        {extStatus === 'needs_review' ? 'Needs Review' :
                         extStatus === 'reviewed' || extStatus === 'approved' ? 'Reviewed' :
                         extStatus === 'exported' ? 'Exported' :
                         extStatus === 'manual_required' ? 'OCR Required' :
                         extStatus === 'failed' ? 'Failed' :
                         extStatus || 'No Data'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 text-xs font-medium rounded ${sourceDisplay.color}`}>
                        {sourceDisplay.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {doc.created_at ? (
                        <span title={parseUTCDate(doc.created_at).toLocaleString()}>
                          {parseUTCDate(doc.created_at).toLocaleString('en-US', {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      ) : '-'}
                    </td>
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex justify-end items-center space-x-2">
                        {extRunId ? (
                          <>
                            <button
                              onClick={() => navigate(`/review/${extRunId}`)}
                              className="text-sm text-blue-600 hover:text-blue-800"
                            >
                              {extStatus === 'needs_review' || extStatus === 'manual_required' ? 'Review' : 'View'}
                            </button>
                            {isReady && !isExported && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setShowExportPreview({ extractionId: extRunId, documentId: doc.id })
                                }}
                                className="text-sm text-green-600 hover:text-green-800 font-medium"
                              >
                                Export
                              </button>
                            )}
                            {!isExported && (
                              <button
                                onClick={() => handleRunExtraction(doc.id, true)}
                                disabled={extractingDocId === doc.id}
                                className="text-sm text-orange-600 hover:text-orange-800"
                              >
                                {extractingDocId === doc.id ? '...' : 'Re-run'}
                              </button>
                            )}
                          </>
                        ) : (
                          <button
                            onClick={() => handleRunExtraction(doc.id)}
                            disabled={extractingDocId === doc.id}
                            className="text-sm text-blue-600 hover:text-blue-800"
                          >
                            {extractingDocId === doc.id ? 'Processing...' : 'Extract'}
                          </button>
                        )}
                        {/* Hold / Release Hold */}
                        {isOnHold ? (
                          <button
                            onClick={(e) => handleReleaseHold(doc.id, e)}
                            className="text-sm text-amber-600 hover:text-amber-800"
                          >
                            Unhold
                          </button>
                        ) : !isExported ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); setHoldModal({ docId: doc.id }) }}
                            className="text-sm text-gray-500 hover:text-gray-700"
                          >
                            Hold
                          </button>
                        ) : null}
                        {/* Archive (exported) or Delete (not exported) */}
                        {isExported ? (
                          <button
                            onClick={(e) => handleArchive(doc.id, e)}
                            className="text-sm text-gray-500 hover:text-gray-700"
                          >
                            Archive
                          </button>
                        ) : (
                          <button
                            onClick={(e) => handleDelete(doc.id, e)}
                            className="text-sm text-red-600 hover:text-red-800"
                          >
                            Del
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pagination.total > pagination.limit && (
          <div className="flex items-center justify-between mt-4 px-4 py-3 bg-gray-50 rounded-lg">
            <div className="text-sm text-gray-600">
              Showing {((pagination.page - 1) * pagination.limit) + 1} to {Math.min(pagination.page * pagination.limit, pagination.total)} of {pagination.total} documents
            </div>
            <div className="flex space-x-2">
              <button
                onClick={() => setPagination(p => ({ ...p, page: Math.max(1, p.page - 1) }))}
                disabled={pagination.page === 1}
                className="btn btn-sm btn-secondary disabled:opacity-50"
              >
                Previous
              </button>
              <span className="px-3 py-1 bg-white border rounded text-sm">
                Page {pagination.page} of {Math.ceil(pagination.total / pagination.limit)}
              </span>
              <button
                onClick={() => setPagination(p => ({ ...p, page: Math.min(Math.ceil(p.total / p.limit), p.page + 1) }))}
                disabled={pagination.page >= Math.ceil(pagination.total / pagination.limit)}
                className="btn btn-sm btn-secondary disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
        </>
      )}

      {/* Export Preview Modal */}
      {showExportPreview && (
        <ExportPreviewModal
          extractionId={showExportPreview.extractionId}
          documentId={showExportPreview.documentId}
          onClose={() => setShowExportPreview(null)}
          onExport={(result) => {
            fetchDocExtractions()
            if (result.posted > 0) {
              setShowExportPreview(null)
            }
          }}
        />
      )}

      {/* Hold Modal */}
      {holdModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <h2 className="text-lg font-bold mb-4">Put Document on Hold</h2>
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
              <select
                value={holdReason}
                onChange={(e) => setHoldReason(e.target.value)}
                className="form-select w-full"
              >
                <option value="awaiting_gate_pass">Awaiting Gate Pass</option>
                <option value="awaiting_payment">Awaiting Payment</option>
                <option value="awaiting_title">Awaiting Title</option>
                <option value="awaiting_release">Awaiting Vehicle Release</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Note (optional)</label>
              <input
                type="text"
                value={holdNote}
                onChange={(e) => setHoldNote(e.target.value)}
                placeholder="Additional details..."
                className="form-input w-full text-sm"
              />
            </div>
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => { setHoldModal(null); setHoldReason('awaiting_gate_pass'); setHoldNote('') }}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={() => handleSetHold(holdModal.docId)}
                className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700"
              >
                Set Hold
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Batch Hold Modal */}
      {showBatchHold && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <h2 className="text-lg font-bold mb-4">Batch Hold — {getBatchEligibility().holdDocIds.length} Document(s)</h2>
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
              <select
                value={batchHoldReason}
                onChange={(e) => setBatchHoldReason(e.target.value)}
                className="form-select w-full"
              >
                <option value="awaiting_gate_pass">Awaiting Gate Pass</option>
                <option value="awaiting_payment">Awaiting Payment</option>
                <option value="awaiting_title">Awaiting Title</option>
                <option value="awaiting_release">Awaiting Vehicle Release</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Note (optional)</label>
              <input
                type="text"
                value={batchHoldNote}
                onChange={(e) => setBatchHoldNote(e.target.value)}
                placeholder="Additional details..."
                className="form-input w-full text-sm"
              />
            </div>
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => { setShowBatchHold(false); setBatchHoldReason('awaiting_gate_pass'); setBatchHoldNote('') }}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={handleBatchHoldConfirm}
                disabled={batchOperating}
                className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
              >
                {batchOperating ? 'Processing...' : `Set Hold (${getBatchEligibility().holdDocIds.length})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Batch Post Modal */}
      {showBatchPost && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-auto">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold">Batch Post to Central Dispatch</h2>
              <button
                onClick={closeBatchPostModal}
                className="text-gray-500 hover:text-gray-700 text-2xl"
              >
                &times;
              </button>
            </div>

            {batchResult ? (
              // Results view
              <div>
                <div className={`p-4 rounded-lg mb-4 ${
                  batchResult.failed === 0 ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'
                }`}>
                  <h3 className={`font-medium ${batchResult.failed === 0 ? 'text-green-800' : 'text-yellow-800'}`}>
                    Batch Post Complete
                  </h3>
                  <div className="mt-2 grid grid-cols-3 gap-4 text-sm">
                    <div>
                      <span className="text-gray-600">Posted:</span>
                      <span className="ml-2 font-medium text-green-600">{batchResult.posted}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Failed:</span>
                      <span className="ml-2 font-medium text-red-600">{batchResult.failed}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Skipped:</span>
                      <span className="ml-2 font-medium text-gray-600">{batchResult.skipped}</span>
                    </div>
                  </div>
                </div>

                {/* Individual results */}
                <div className="space-y-2 max-h-60 overflow-auto">
                  {batchResult.results?.map((result, i) => (
                    <div
                      key={i}
                      className={`p-3 rounded text-sm ${
                        result.status === 'success' ? 'bg-green-50' :
                        result.status === 'failed' ? 'bg-red-50' :
                        result.status === 'blocked' ? 'bg-orange-50' :
                        'bg-gray-50'
                      }`}
                    >
                      <div className="flex justify-between items-center">
                        <span className="font-medium">{result.document_filename || `Run ${result.run_id}`}</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          result.status === 'success' ? 'bg-green-100 text-green-800' :
                          result.status === 'failed' ? 'bg-red-100 text-red-800' :
                          result.status === 'blocked' ? 'bg-orange-100 text-orange-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {result.status}
                        </span>
                      </div>
                      <p className="text-gray-600 mt-1">{result.message}</p>
                      {result.cd_listing_id && (
                        <p className="text-green-700 mt-1">CD ID: {result.cd_listing_id}</p>
                      )}
                    </div>
                  ))}
                </div>

                <div className="mt-4 flex justify-end">
                  <button onClick={closeBatchPostModal} className="btn btn-primary">
                    Close
                  </button>
                </div>
              </div>
            ) : batchPreflight ? (
              // Preflight view
              <div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
                    <p className="text-sm text-green-700">Ready to Post</p>
                    <p className="text-2xl font-bold text-green-800">{batchPreflight.ready_count}</p>
                  </div>
                  <div className="p-4 bg-orange-50 border border-orange-200 rounded-lg">
                    <p className="text-sm text-orange-700">Not Ready</p>
                    <p className="text-2xl font-bold text-orange-800">{batchPreflight.not_ready_count}</p>
                  </div>
                </div>

                {batchPreflight.not_ready?.length > 0 && (
                  <div className="mb-4">
                    <h3 className="font-medium text-gray-800 mb-2">Issues Preventing Posting:</h3>
                    <div className="space-y-2 max-h-40 overflow-auto">
                      {batchPreflight.not_ready.map((item, i) => (
                        <div key={i} className="p-2 bg-orange-50 rounded text-sm">
                          <span className="font-medium">{item.document_filename || `Run ${item.run_id}`}</span>
                          {item.reason && <span className="text-orange-700 ml-2">— {item.reason}</span>}
                          {item.issues?.length > 0 && (
                            <ul className="mt-1 list-disc list-inside text-orange-700">
                              {item.issues.slice(0, 3).map((issue, j) => (
                                <li key={j}>{issue}</li>
                              ))}
                              {item.issues.length > 3 && <li>...and {item.issues.length - 3} more</li>}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex justify-end gap-3">
                  <button onClick={closeBatchPostModal} className="btn btn-secondary">
                    Cancel
                  </button>
                  {batchPreflight.ready_count > 0 && (
                    <button
                      onClick={() => handleBatchPost(true)}
                      disabled={batchPosting}
                      className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                    >
                      {batchPosting ? 'Posting...' : `Post ${batchPreflight.ready_count} Ready Documents`}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              // Loading
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                <span className="ml-3 text-gray-600">Checking documents...</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Documents
