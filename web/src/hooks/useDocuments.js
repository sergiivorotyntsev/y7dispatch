import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { parseUTCDate } from '../utils/date'

/** Group documents by date (most recent first) */
export function groupByDate(docs) {
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

export default function useDocuments() {
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

  // Extraction state
  const [extractingDocId, setExtractingDocId] = useState(null)

  // Inline editing state
  const [editingPrice, setEditingPrice] = useState({ docId: null, value: '' })
  const [exportingDocId, setExportingDocId] = useState(null)

  // Hold modal state
  const [holdModal, setHoldModal] = useState(null)
  const [holdReason, setHoldReason] = useState('awaiting_gate_pass')
  const [holdNote, setHoldNote] = useState('')

  // Batch operations state
  const [batchOperating, setBatchOperating] = useState(false)
  const [batchOpResult, setBatchOpResult] = useState(null)
  const [showBatchHold, setShowBatchHold] = useState(false)
  const [batchHoldReason, setBatchHoldReason] = useState('awaiting_gate_pass')
  const [batchHoldNote, setBatchHoldNote] = useState('')

  // Date grouping
  const [collapsedDates, setCollapsedDates] = useState(new Set())

  // Export preview modal
  const [showExportPreview, setShowExportPreview] = useState(null)

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setSearchDebounced(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  // Fetch documents with stale-while-revalidate caching
  const fetchDocuments = useCallback(async () => {
    const cacheKey = 'y7_documents_cache'
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
      let prodDocs = (result.items || []).filter(d => !d.is_test)

      if (filter.status) {
        prodDocs = prodDocs.filter(doc => {
          if (filter.status === 'hold') return !!doc.hold_reason
          if (filter.status === 'pending') return !!doc.pending_reason && !doc.hold_reason
          if (filter.status === 'archived') return !!doc.archived_at
          const ext = docExtractions[doc.id]
          const extStatus = doc.extraction_status || ext?.status
          return extStatus === filter.status
        })
      }

      const sorted = [...prodDocs].sort((a, b) => {
        const aVal = a[sortConfig.sortBy] || ''
        const bVal = b[sortConfig.sortBy] || ''
        const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
        return sortConfig.sortOrder === 'desc' ? -cmp : cmp
      })

      setDocuments(sorted)
      setPagination(p => ({ ...p, total: result.total || prodDocs.length }))

      if (!hasFilter) {
        try {
          sessionStorage.setItem(cacheKey, JSON.stringify({
            docs: sorted, total: result.total || prodDocs.length,
          }))
        } catch { /* storage full */ }
      }

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

  // Fetch latest extraction status for each document
  const fetchDocExtractions = useCallback(async () => {
    try {
      const result = await api.listExtractions({ limit: 200, is_test: false })
      const extractionsByDoc = {}
      let needsReview = 0
      let readyToExport = 0
      let exported = 0

      const prodDocIds = new Set(documents.map(d => d.id))

      for (const run of (result.items || [])) {
        if (!prodDocIds.has(run.document_id)) continue
        if (!extractionsByDoc[run.document_id] || run.id > extractionsByDoc[run.document_id].id) {
          extractionsByDoc[run.document_id] = run
        }
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
  }, [fetchDocExtractions])

  // Upload handler
  async function handleUpload() {
    if (!uploadFile) return
    setUploading(true)
    setUploadResult(null)
    try {
      const auctionTypeId = selectedAuctionType === 'auto' ? null : parseInt(selectedAuctionType)
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

  async function handleWarehouseChange(docId, warehouseId, e) {
    e.stopPropagation()
    const extraction = docExtractions[docId]
    if (!extraction) return
    try {
      const whId = warehouseId ? parseInt(warehouseId, 10) : null
      const currentOutputs = extraction.outputs || {}
      if (whId) {
        const selectedWarehouse = warehouses.find(w => w.id === whId)
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
        const cleared = { ...currentOutputs }
        delete cleared.warehouse_id
        delete cleared.delivery_name
        delete cleared.delivery_address
        delete cleared.delivery_city
        delete cleared.delivery_state
        delete cleared.delivery_zip
        await api.updateExtraction(extraction.id, { outputs_json: cleared })
      }
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
      fetchDocuments()
      fetchDocExtractions()
    }
  }

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

  async function handleReleaseHold(docId, e) {
    e.stopPropagation()
    try {
      await api.releaseHold(docId)
      fetchDocuments()
    } catch (err) {
      setError(`Release hold failed: ${err.message}`)
    }
  }

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
      await api.updateExtraction(extraction.id, { outputs_json: { price_total: newPrice } })
      fetchDocExtractions()
    } catch (err) {
      setError(`Price update failed: ${err.message}`)
    } finally {
      setEditingPrice({ docId: null, value: '' })
    }
  }

  async function handleExportToCD(docId, e) {
    e.stopPropagation()
    const extraction = docExtractions[docId]
    if (!extraction) return
    setExportingDocId(docId)
    try {
      await api.exportToCD([extraction.id], false, true)
      fetchDocExtractions()
    } catch (err) {
      setError(`Export failed: ${err.message}`)
    } finally {
      setExportingDocId(null)
    }
  }

  function toggleSelectDoc(docId, e) {
    e.stopPropagation()
    setSelectedDocs(prev => {
      const newSet = new Set(prev)
      if (newSet.has(docId)) newSet.delete(docId)
      else newSet.add(docId)
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

  function getSelectedRunIds() {
    return Array.from(selectedDocs)
      .map(docId => docExtractions[docId]?.id)
      .filter(Boolean)
  }

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

  async function handleBatchPost(postOnlyReady = true) {
    const runIds = getSelectedRunIds()
    setBatchPosting(true)
    try {
      const result = await api.batchPost(runIds, postOnlyReady, true)
      setBatchResult(result)
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
      if (runId && extStatus === 'needs_review') approveRunIds.push(runId)
      if (runId && (extStatus === 'reviewed' || extStatus === 'approved')) exportRunIds.push(runId)
      if (!isExported && !isArchived && !isOnHold) holdDocIds.push(docId)
      if (isExported && !isArchived) archiveDocIds.push(docId)
    }
    return { approveRunIds, exportRunIds, holdDocIds, archiveDocIds }
  }

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

  function getSourceDisplay(doc) {
    if (doc.source === 'email') return { label: 'Email', color: 'bg-blue-100 text-blue-800' }
    if (doc.source === 'webhook') return { label: 'Webhook', color: 'bg-purple-100 text-purple-800' }
    if (doc.source === 'test_lab') return { label: 'Test Lab', color: 'bg-yellow-100 text-yellow-800' }
    return { label: 'Manual', color: 'bg-gray-100 text-gray-800' }
  }

  function getExportStatus(extraction) {
    if (!extraction) return { label: 'No Data', color: 'bg-gray-100 text-gray-500' }
    if (extraction.status === 'exported') return { label: 'Exported', color: 'bg-green-100 text-green-800' }
    if (extraction.status === 'reviewed' || extraction.status === 'approved') return { label: 'Ready', color: 'bg-blue-100 text-blue-800' }
    if (extraction.status === 'needs_review') return { label: 'Pending', color: 'bg-yellow-100 text-yellow-800' }
    if (extraction.status === 'failed') return { label: 'Failed', color: 'bg-red-100 text-red-800' }
    return { label: extraction.status, color: 'bg-gray-100 text-gray-600' }
  }

  function handleRowClick(doc) {
    const extraction = docExtractions[doc.id]
    if (extraction) {
      navigate(`/review/${extraction.id}`)
    } else {
      handleRunExtraction(doc.id)
    }
  }

  return {
    // State
    documents, loading, error, setError,
    auctionTypes, warehouses, docExtractions,
    selectedDocs, setSelectedDocs,
    showBatchPost, batchPreflight, batchPosting, batchResult,
    search, setSearch,
    filter, setFilter,
    pagination, setPagination,
    sortConfig, setSortConfig,
    stats,
    showUpload, setShowUpload,
    uploadFile, setUploadFile,
    uploading, selectedAuctionType, setSelectedAuctionType,
    uploadResult, setUploadResult,
    extractingDocId, editingPrice, setEditingPrice,
    exportingDocId,
    holdModal, setHoldModal,
    holdReason, setHoldReason,
    holdNote, setHoldNote,
    batchOperating, batchOpResult, setBatchOpResult,
    showBatchHold, setShowBatchHold,
    batchHoldReason, setBatchHoldReason,
    batchHoldNote, setBatchHoldNote,
    collapsedDates,
    showExportPreview, setShowExportPreview,
    navigate,
    // Handlers
    fetchDocuments, fetchDocExtractions,
    handleUpload, handleRunExtraction,
    handleWarehouseChange, handleDelete,
    handleSetHold, handleReleaseHold,
    handleArchive, handlePriceUpdate,
    handleExportToCD,
    toggleSelectDoc, toggleSelectAll,
    handleBatchPostPreflight, handleBatchPost, closeBatchPostModal,
    getBatchEligibility,
    handleBatchApprove, handleBatchHoldConfirm, handleBatchArchive,
    getSourceDisplay, getExportStatus,
    handleRowClick,
    toggleDate, collapseAll, expandAll,
  }
}
