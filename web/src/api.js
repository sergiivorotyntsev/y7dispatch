// API client for the FastAPI backend

const API_BASE = '/api'

// In-flight request dedup: if a GET request to the same URL is already in progress,
// return the same promise instead of making a duplicate network call.
const _inflight = new Map()

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`
  const method = (options.method || 'GET').toUpperCase()

  // Dedup only GET requests (safe, idempotent)
  const dedupKey = method === 'GET' ? url : null
  if (dedupKey && _inflight.has(dedupKey)) {
    return _inflight.get(dedupKey)
  }

  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    credentials: 'include', // Send httpOnly auth cookie with every request
    ...options,
  }

  // Don't set Content-Type for FormData
  if (options.body instanceof FormData) {
    delete config.headers['Content-Type']
  }

  const promise = fetch(url, config).then(async (response) => {
    // Global 401 handler — redirect to login on token expiry
    if (response.status === 401 && !url.includes('/auth/')) {
      window.location.reload() // App.jsx auth check will show login
      throw new Error('Session expired')
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      // Handle Pydantic validation errors (detail is array of objects)
      let errorMsg = `HTTP ${response.status}`
      if (error.detail) {
        if (Array.isArray(error.detail)) {
          // Pydantic validation error format
          errorMsg = error.detail.map(e => {
            const loc = e.loc ? e.loc.join(' → ') : ''
            return `${loc}: ${e.msg}`
          }).join('; ')
        } else if (typeof error.detail === 'string') {
          errorMsg = error.detail
        } else {
          errorMsg = JSON.stringify(error.detail)
        }
      }
      throw new Error(errorMsg)
    }

    // Handle empty responses
    const text = await response.text()
    return text ? JSON.parse(text) : null
  }).finally(() => {
    if (dedupKey) _inflight.delete(dedupKey)
  })

  if (dedupKey) _inflight.set(dedupKey, promise)
  return promise
}

// Health & Status
export const api = {
  // Auth
  login: (username, password) => request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  getAuthMe: () => request('/auth/me'),

  // Health
  getHealth: () => request('/health'),
  getReady: () => request('/ready'),

  // Settings
  getSettingsStatus: () => request('/settings/status'),
  getExportTargets: () => request('/settings/export-targets'),
  updateExportTargets: (targets) => request('/settings/export-targets', {
    method: 'PUT',
    body: JSON.stringify({ targets }),
  }),
  getSheetsConfig: () => request('/settings/sheets'),
  updateSheetsConfig: (config) => request('/settings/sheets', {
    method: 'PUT',
    body: JSON.stringify(config),
  }),
  testSheets: () => request('/settings/test-sheets', { method: 'POST' }),
  getCDConfig: () => request('/settings/cd'),
  updateCDConfig: (config) => request('/settings/cd', {
    method: 'PUT',
    body: JSON.stringify(config),
  }),
  getEmailConfig: () => request('/settings/email'),
  updateEmailConfig: (config) => request('/settings/email', {
    method: 'PUT',
    body: JSON.stringify(config),
  }),
  getWarehouses: () => request('/settings/warehouses'),
  updateWarehouses: (warehouses) => request('/settings/warehouses', {
    method: 'PUT',
    body: JSON.stringify({ warehouses }),
  }),

  // Test/Sandbox
  uploadPdf: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return request('/test/upload', {
      method: 'POST',
      body: formData,
    })
  },
  classifyPdf: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return request('/test/classify', {
      method: 'POST',
      body: formData,
    })
  },
  previewCD: (data) => request('/test/preview-cd', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  previewSheetsRow: (data) => request('/test/preview-sheets-row', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  dryRun: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return request('/test/dry-run', {
      method: 'POST',
      body: formData,
    })
  },

  // Runs
  listRuns: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/runs/${query ? `?${query}` : ''}`)
  },
  getRun: (runId) => request(`/runs/${runId}`),
  getRunLogs: (runId) => request(`/runs/${runId}/logs`),
  getRunStats: () => request('/runs/stats'),
  deleteRun: (runId) => request(`/runs/${runId}`, { method: 'DELETE' }),
  retryRun: (runId) => request(`/runs/retry/${runId}`, { method: 'POST' }),
  exportRunsCsv: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return `${API_BASE}/runs/export/csv${query ? `?${query}` : ''}`
  },
  searchLogs: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/runs/logs/search${query ? `?${query}` : ''}`)
  },

  // Documents
  listDocuments: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/documents/${query ? `?${query}` : ''}`)
  },
  getDocument: (id) => request(`/documents/${id}`),
  getDocumentText: (id) => request(`/documents/${id}/text`),
  getDocumentExportPreview: (id) => request(`/documents/${id}/export-preview`),
  getDocumentFileUrl: (id) => `${API_BASE}/documents/${id}/file`,
  getDocumentPageImageUrl: (id, pageNum = 1, dpi = 150) => `${API_BASE}/documents/${id}/page/${pageNum}/image?dpi=${dpi}`,
  deleteDocument: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  clearTestLabDocuments: () => request('/documents/test-lab/clear-all', { method: 'DELETE' }),
  listTrainingDocuments: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/documents/training/list${query ? `?${query}` : ''}`)
  },
  uploadDocument: async (file, auctionTypeId, datasetSplit = 'train') => {
    const formData = new FormData()
    formData.append('file', file)
    // Only add auction_type_id if provided (null means auto-detect)
    if (auctionTypeId !== null && auctionTypeId !== undefined) {
      formData.append('auction_type_id', auctionTypeId)
    }
    formData.append('dataset_split', datasetSplit)
    formData.append('auto_classify', 'true')  // Enable auto-classification
    return request('/documents/upload', {
      method: 'POST',
      body: formData,
    })
  },
  uploadTrainingDocument: async (file, auctionTypeId = null) => {
    const formData = new FormData()
    formData.append('file', file)
    if (auctionTypeId !== null && auctionTypeId !== undefined) {
      formData.append('auction_type_id', auctionTypeId)
    }
    formData.append('dataset_split', 'train')
    formData.append('source', 'test_lab')  // Mark as training document
    formData.append('auto_classify', 'true')
    return request('/documents/upload', {
      method: 'POST',
      body: formData,
    })
  },
  getDocumentStats: () => request('/documents/stats/by-auction-type'),

  // Extractions
  listExtractions: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/extractions/${query ? `?${query}` : ''}`)
  },
  getExtraction: (id) => request(`/extractions/${id}`),
  getExtractionStats: () => request('/extractions/stats'),
  runExtraction: (documentId, forceMl = false) => request('/extractions/run', {
    method: 'POST',
    body: JSON.stringify({ document_id: documentId, force_ml: forceMl }),
  }),
  updateExtraction: (id, data) => request(`/extractions/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  listNeedsReview: (limit = 50) => request(`/extractions/needs-review?limit=${limit}`),

  // Central Dispatch Export
  getCDPayloadPreview: (runId) => request(`/exports/central-dispatch/preview/${runId}`),
  exportToCentralDispatch: (runId, sandbox = true) => request('/exports/central-dispatch', {
    method: 'POST',
    body: JSON.stringify({ run_ids: [runId], dry_run: false, sandbox }),
  }),

  // Reviews (endpoint is /api/review, not /api/reviews)
  getReviewItems: async (runId) => {
    // Backend returns { items: [...], run_id, ... } at /api/review/{run_id}
    const response = await request(`/review/${runId}`)
    return response  // Contains items array
  },
  submitReview: (data) => request('/review/submit', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Review Evidence (M3.P2) - Get field evidence with bbox for highlighting
  getRunEvidence: (runId) => request(`/review/${runId}/evidence`),

  // Review Preflight (M3.P2) - Get validation status before export
  // mode: "training" skips export-only fields, "export" checks all
  // warehouseId: optional warehouse ID to validate delivery fields
  getRunPreflight: (runId, mode = 'training', warehouseId = null) => {
    let url = `/review/${runId}/preflight?mode=${mode}`
    if (warehouseId) {
      url += `&warehouse_id=${warehouseId}`
    }
    return request(url)
  },

  // Get latest extraction run for a document
  getDocumentExtractions: (documentId) => request(`/extractions/?document_id=${documentId}&limit=1`),

  // Auction Types
  listAuctionTypes: () => request('/auction-types/'),
  getAuctionType: (id) => request(`/auction-types/${id}`),
  updateAuctionType: (id, data) => request(`/auction-types/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),

  // Integration Management
  getAllSettings: async () => {
    const [email, sheets, cd, warehouses, exportTargets] = await Promise.all([
      request('/settings/email').catch(() => ({})),
      request('/settings/sheets').catch(() => ({})),
      request('/settings/cd').catch(() => ({})),
      request('/settings/warehouses').catch(() => ({ warehouses: [] })),
      request('/settings/export-targets').catch(() => ({ targets: [] })),
    ])
    return { email, sheets, cd, warehouses: warehouses.warehouses || [], exportTargets: exportTargets.targets || [] }
  },

  // Integration Testing
  testSheetsConnection: () => request('/integrations/sheets/test', { method: 'POST' }),
  testCDConnection: () => request('/integrations/cd/test', { method: 'POST' }),
  cdDryRun: (runId) => request('/integrations/cd/dry-run', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId }),
  }),
  cdExport: (runId) => request('/integrations/cd/export', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId }),
  }),
  testEmailConnection: () => request('/integrations/email/test', { method: 'POST' }),

  // Email Rules
  getEmailRules: () => request('/integrations/email/rules'),
  updateEmailRules: (rules) => request('/integrations/email/rules', {
    method: 'PUT',
    body: JSON.stringify({ rules }),
  }),

  // Email Activity Log
  getEmailActivity: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/integrations/email/activity${query ? `?${query}` : ''}`)
  },

  // Integration Audit Log
  getIntegrationAuditLog: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/integrations/audit-log${query ? `?${query}` : ''}`)
  },

  // Warehouse Management
  addWarehouse: (warehouse) => request('/integrations/warehouses', {
    method: 'POST',
    body: JSON.stringify(warehouse),
  }),
  deleteWarehouse: (code) => request(`/integrations/warehouses/${code}`, { method: 'DELETE' }),

  // CSV Export
  exportExtractionsCsv: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return `${API_BASE}/integrations/extractions/export/csv${query ? `?${query}` : ''}`
  },

  // Full Warehouse API (with hours, timezone, appointments)
  listWarehouses: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/warehouses/${query ? `?${query}` : ''}`)
  },
  getWarehouse: (id) => request(`/warehouses/${id}`),
  getWarehouseByCode: (code) => request(`/warehouses/code/${code}`),
  createWarehouse: (data) => request('/warehouses/', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateWarehouse: (id, data) => request(`/warehouses/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  deleteWarehouseFull: (id, hard = false) => request(`/warehouses/${id}?hard=${hard}`, {
    method: 'DELETE',
  }),
  getWarehouseStates: () => request('/warehouses/states/list'),
  syncWarehousesFromYaml: () => request('/warehouses/sync-yaml', { method: 'POST' }),

  // Templates / Field Mappings
  listTemplates: () => request('/templates/'),
  getTemplate: (auctionTypeId) => request(`/templates/${auctionTypeId}`),
  createTemplateVersion: (auctionTypeId, data) => request(`/templates/${auctionTypeId}/versions`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  activateTemplateVersion: (auctionTypeId, versionTag) => request(`/templates/${auctionTypeId}/versions/${versionTag}/activate`, {
    method: 'PUT',
  }),
  listFields: (auctionTypeId, includeInactive = false) => request(`/templates/${auctionTypeId}/fields?include_inactive=${includeInactive}`),
  createField: (auctionTypeId, data) => request(`/templates/${auctionTypeId}/fields`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateField: (auctionTypeId, fieldId, data) => request(`/templates/${auctionTypeId}/fields/${fieldId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  deleteField: (auctionTypeId, fieldId, hard = false) => request(`/templates/${auctionTypeId}/fields/${fieldId}?hard=${hard}`, {
    method: 'DELETE',
  }),
  reorderFields: (auctionTypeId, fieldIds) => request(`/templates/${auctionTypeId}/fields/reorder`, {
    method: 'PUT',
    body: JSON.stringify(fieldIds),
  }),

  // Email Worker
  pollEmailNow: (sinceDays = 0, sinceDate = null) => {
    const params = new URLSearchParams()
    if (sinceDate) {
      params.set('since_date', sinceDate)
    } else {
      params.set('since_days', sinceDays)
    }
    return request(`/email/poll?${params}`, { method: 'POST' })
  },
  startEmailWorker: () => request('/email/worker/start', { method: 'POST' }),
  stopEmailWorker: () => request('/email/worker/stop', { method: 'POST' }),
  recoverEmails: (sinceDays = 7) => request(`/email/recover?since_days=${sinceDays}`, { method: 'POST' }),
  resetEmailData: () => request('/email/reset', { method: 'POST' }),

  // Email Log
  getEmailLog: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/email-log${query ? `?${query}` : ''}`)
  },
  processEmail: (emailId) => request(`/email-log/${emailId}/process`, { method: 'POST' }),
  skipEmail: (emailId) => request(`/email-log/${emailId}/skip`, { method: 'POST' }),
  reprocessEmail: (emailId) => request(`/email-log/${emailId}/reprocess`, { method: 'POST' }),
  getEmailStats: () => request('/email-log/stats'),

  // Attachments
  listAttachments: (runId) => request(`/documents/${runId}/attachments`),
  getAttachmentUrl: (runId, filename) => `${BASE_URL}/documents/${runId}/attachments/${encodeURIComponent(filename)}`,

  // Exports
  exportToCD: (runIds, dryRun = true, sandbox = true, force = false, overrides = null) => request(`/exports/central-dispatch?force=${force}`, {
    method: 'POST',
    body: JSON.stringify({ run_ids: runIds, dry_run: dryRun, sandbox, overrides }),
  }),
  previewCDPayload: (runId, overrides = null) => {
    if (overrides) {
      return request(`/exports/central-dispatch/preview/${runId}`, {
        method: 'POST',
        body: JSON.stringify(overrides),
      })
    }
    return request(`/exports/central-dispatch/preview/${runId}`)
  },
  listExportJobs: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/exports/jobs${query ? `?${query}` : ''}`)
  },
  getExportJob: (jobId) => request(`/exports/jobs/${jobId}`),
  retryExportJob: (jobId, sandbox = true) => request(`/exports/jobs/${jobId}/retry?sandbox=${sandbox}`, {
    method: 'POST',
  }),

  // Field Registry (single source of truth for CD fields)
  getFieldRegistry: () => request('/exports/field-registry'),
  getBlockingIssues: (runId, mode = 'export') => request(`/exports/field-registry/blocking-issues/${runId}?mode=${mode}`),

  // Field Taxonomy Settings (Option C implementation)
  getFieldSchema: () => request('/settings/fields/schema'),
  getFieldTaxonomy: () => request('/settings/fields/taxonomy'),
  getFieldsByCategory: (category) => request(`/settings/fields/by-category/${category}`),
  getFieldsBySource: (sourceType) => request(`/settings/fields/by-source/${sourceType}`),
  getFieldsForMode: (mode) => request(`/settings/fields/for-mode/${mode}`),
  getExtractedFields: () => request('/settings/fields/extracted'),

  // Field Configuration Persistence
  getFieldConfigs: () => request('/settings/fields/configs'),
  updateFieldConfigs: (updates) => request('/settings/fields/configs', {
    method: 'PUT',
    body: JSON.stringify({ updates }),
  }),
  updateSingleFieldConfig: (fieldKey, data) => request(`/settings/fields/configs/${fieldKey}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  deleteFieldConfig: (fieldKey) => request(`/settings/fields/configs/${fieldKey}`, {
    method: 'DELETE',
  }),

  // CD Listing Info (ETag tracking)
  getCDListingInfo: (runId) => request(`/exports/cd-listing/${runId}`),

  // Market Intelligence Pricing
  getPricingRecommendation: (runId) => request(`/exports/pricing/${runId}`),
  getFullPricing: (runId, urgency = 'STANDARD') => request(`/pricing/recommend/${runId}?urgency=${urgency}`),
  getCDMarketPrice: (runId, warehouseId) => {
    const qs = warehouseId ? `?warehouse_id=${warehouseId}` : ''
    return request(`/pricing/cd-market-intelligence/${runId}${qs}`)
  },

  // Load ID Generation
  generateLoadId: (make, model) => request(`/listings/generate-load-id?make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}`),
  recalculateLoadId: (runId) => request(`/listings/recalculate-load-id/${runId}`, { method: 'POST' }),

  // Email Scan + Process (2-step flow)
  scanEmails: (sinceDate, untilDate = null) => {
    const body = { since_date: sinceDate }
    if (untilDate) body.until_date = untilDate
    return request('/email/scan', { method: 'POST', body: JSON.stringify(body) })
  },
  processSelectedEmails: (messageIds) => request('/email/process-selected', {
    method: 'POST',
    body: JSON.stringify({ message_ids: messageIds }),
  }),

  // Email Auto-Polling
  getPollStatus: () => request('/email/poll-status'),
  updatePollSettings: ({ enabled, interval_minutes, since_days } = {}) => {
    const params = new URLSearchParams()
    if (enabled !== undefined) params.set('enabled', enabled)
    if (interval_minutes !== undefined) params.set('interval_minutes', interval_minutes)
    if (since_days !== undefined) params.set('since_days', since_days)
    return request(`/email/poll-settings?${params}`, { method: 'POST' })
  },

  // Hold Status
  setHold: (docId, reason, note = null) => request(`/documents/${docId}/set-hold`, {
    method: 'POST',
    body: JSON.stringify({ reason, note }),
  }),
  releaseHold: (docId) => request(`/documents/${docId}/release-hold`, {
    method: 'POST',
  }),

  // Archive
  archiveDocument: (docId) => request(`/documents/${docId}/archive`, { method: 'POST' }),
  unarchiveDocument: (docId) => request(`/documents/${docId}/unarchive`, { method: 'POST' }),
  autoAssignWarehouse: (docIds = []) => request('/documents/auto-assign-warehouse', {
    method: 'POST',
    body: JSON.stringify({ document_ids: docIds }),
  }),

  // Auction Directory Lookup
  lookupAuctionLocation: (name) => request(`/auction-directory/lookup?name=${encodeURIComponent(name)}`),

  // CD Listings API v2 — Preview & Push
  getCDPayload: (docId, warehouseCode = null) => {
    const qs = warehouseCode ? `?warehouse_code=${warehouseCode}` : ''
    return request(`/documents/${docId}/cd-payload${qs}`)
  },
  pushCDListing: (docId, { warehouseCode = null, sandbox = true, dryRun = false } = {}) =>
    request('/central-dispatch/listings', {
      method: 'POST',
      body: JSON.stringify({ document_id: docId, warehouse_code: warehouseCode, sandbox, dry_run: dryRun }),
    }),

  // Batch Posting
  batchPostPreflight: (runIds) => request('/exports/batch-post/preflight', {
    method: 'POST',
    body: JSON.stringify(runIds),
  }),
  batchPost: (runIds, postOnlyReady = true, sandbox = true) => request('/exports/batch-post', {
    method: 'POST',
    body: JSON.stringify({ run_ids: runIds, post_only_ready: postOnlyReady, sandbox }),
  }),

  // Batch Operations (approve, hold, archive)
  batchApprove: (runIds) => request('/batch/approve', {
    method: 'POST',
    body: JSON.stringify({ run_ids: runIds }),
  }),
  batchHold: (documentIds, reason, note = null) => request('/batch/hold', {
    method: 'POST',
    body: JSON.stringify({ document_ids: documentIds, reason, note }),
  }),
  batchArchive: (documentIds) => request('/batch/archive', {
    method: 'POST',
    body: JSON.stringify({ document_ids: documentIds }),
  }),

  // Production Corrections → Training
  submitProductionCorrections: (data) => request('/exports/production-corrections', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  listProductionCorrections: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/exports/production-corrections${query ? `?${query}` : ''}`)
  },
  applyProductionCorrectionsToTraining: (correctionIds = null, applyAllPending = false) => request('/exports/production-corrections/apply-to-training', {
    method: 'POST',
    body: JSON.stringify({
      correction_ids: correctionIds,
      apply_all_pending: applyAllPending,
    }),
  }),

  // ==========================================================================
  // Zone-Based Extraction Templates
  // ==========================================================================
  listZoneTemplates: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/templates${query ? `?${query}` : ''}`)
  },
  getZoneTemplate: (templateId) => request(`/templates/${templateId}`),
  createZoneTemplate: (data) => request('/templates', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateZoneTemplate: (templateId, data) => request(`/templates/${templateId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  deleteZoneTemplate: (templateId) => request(`/templates/${templateId}`, {
    method: 'DELETE',
  }),
  extractWithZones: (data) => request('/templates/extract', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  previewZones: (templateId, documentId) => request(`/templates/${templateId}/zones/preview?document_id=${documentId}`),
  // Live preview with unsaved zones (for edit mode)
  livePreviewZones: (documentId, zones) => request('/templates/zones/live-preview', {
    method: 'POST',
    body: JSON.stringify({ document_id: documentId, zones }),
  }),
  submitTemplateFeedback: (data) => request('/templates/feedback', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // ==========================================================================
  // Credential Management
  // ==========================================================================
  getCredentials: () => request('/credentials/'),
  getCredential: (service) => request(`/credentials/${service}`),
  saveCredential: (service, config, enabled = false) => request(`/credentials/${service}`, {
    method: 'PUT',
    body: JSON.stringify({ config, enabled }),
  }),
  deleteCredential: (service) => request(`/credentials/${service}`, {
    method: 'DELETE',
  }),
  testCredential: (service) => request(`/credentials/${service}/test`, {
    method: 'POST',
  }),

  // ==========================================================================
  // Email Log
  // ==========================================================================
  getEmailLog: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/email-log${query ? `?${query}` : ''}`)
  },
  getEmailStats: () => request('/email-log/stats'),
  processEmail: (emailId) => request(`/email-log/${emailId}/process`, { method: 'POST' }),
  skipEmail: (emailId) => request(`/email-log/${emailId}/skip`, { method: 'POST' }),
  reprocessEmail: (emailId) => request(`/email-log/${emailId}/reprocess`, { method: 'POST' }),
  pollEmails: (sinceDays = 0) => request(`/email/poll?since_days=${sinceDays}`, { method: 'POST' }),

  // Email Context + Vision Extract (Review page)
  getEmailContext: (runId) => request(`/extractions/${runId}/email-context`),
  visionExtract: (runId) => request(`/extractions/${runId}/vision-extract`, { method: 'POST' }),

  // Warehouse Distance & Options
  getWarehouseOptions: (pickupZip, pickupCity = '', pickupState = '') => {
    const params = new URLSearchParams({ pickup_zip: pickupZip })
    if (pickupCity) params.set('pickup_city', pickupCity)
    if (pickupState) params.set('pickup_state', pickupState)
    return request(`/warehouses/options?${params}`)
  },
  getWarehouseOptionsForRun: (runId) => request(`/warehouses/options-for-run/${runId}`),

  // Weather Alerts
  getRouteAlerts: (pickupZip, warehouseId) => {
    const params = new URLSearchParams({ origin_zip: pickupZip, warehouse_id: warehouseId })
    return request(`/weather/route-alerts?${params}`)
  },
  getRouteAlertsForRun: (runId, warehouseId) => {
    const whParam = warehouseId ? `?warehouse_id=${warehouseId}` : ''
    return request(`/weather/route-alerts-for-run/${runId}${whParam}`)
  },
}

export default api
