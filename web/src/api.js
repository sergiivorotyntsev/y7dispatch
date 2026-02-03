// API client for the FastAPI backend

const API_BASE = '/api'

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`

  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  }

  // Don't set Content-Type for FormData
  if (options.body instanceof FormData) {
    delete config.headers['Content-Type']
  }

  const response = await fetch(url, config)

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  // Handle empty responses
  const text = await response.text()
  return text ? JSON.parse(text) : null
}

// Health & Status
export const api = {
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
  getClickUpConfig: () => request('/settings/clickup'),
  updateClickUpConfig: (config) => request('/settings/clickup', {
    method: 'PUT',
    body: JSON.stringify(config),
  }),
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
  deleteDocument: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  clearTestLabDocuments: () => request('/documents/test-lab/clear-all', { method: 'DELETE' }),
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
  getRunPreflight: (runId) => request(`/review/${runId}/preflight`),

  // Get latest extraction run for a document
  getDocumentExtractions: (documentId) => request(`/extractions/?document_id=${documentId}&limit=1`),

  // Auction Types
  listAuctionTypes: () => request('/auction-types/'),
  getAuctionType: (id) => request(`/auction-types/${id}`),

  // Integration Management
  getAllSettings: async () => {
    const [email, clickup, sheets, cd, warehouses, exportTargets] = await Promise.all([
      request('/settings/email').catch(() => ({})),
      request('/settings/clickup').catch(() => ({})),
      request('/settings/sheets').catch(() => ({})),
      request('/settings/cd').catch(() => ({})),
      request('/settings/warehouses').catch(() => ({ warehouses: [] })),
      request('/settings/export-targets').catch(() => ({ targets: [] })),
    ])
    return { email, clickup, sheets, cd, warehouses: warehouses.warehouses || [], exportTargets: exportTargets.targets || [] }
  },

  // Integration Testing
  testClickUpConnection: () => request('/integrations/clickup/test', { method: 'POST' }),
  getClickUpCustomFields: (listId) => request(`/integrations/clickup/custom-fields/${listId}`),
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
  pollEmailNow: () => request('/email/poll', { method: 'POST' }),
  startEmailWorker: () => request('/email/worker/start', { method: 'POST' }),
  stopEmailWorker: () => request('/email/worker/stop', { method: 'POST' }),

  // Exports
  exportToCD: (runIds, dryRun = true, sandbox = true, force = false) => request(`/exports/central-dispatch?force=${force}`, {
    method: 'POST',
    body: JSON.stringify({ run_ids: runIds, dry_run: dryRun, sandbox }),
  }),
  previewCDPayload: (runId) => request(`/exports/central-dispatch/preview/${runId}`),
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
  getBlockingIssues: (runId) => request(`/exports/field-registry/blocking-issues/${runId}`),

  // CD Listing Info (ETag tracking)
  getCDListingInfo: (runId) => request(`/exports/cd-listing/${runId}`),

  // Batch Posting
  batchPostPreflight: (runIds) => request('/exports/batch-post/preflight', {
    method: 'POST',
    body: JSON.stringify(runIds),
  }),
  batchPost: (runIds, postOnlyReady = true, sandbox = true) => request('/exports/batch-post', {
    method: 'POST',
    body: JSON.stringify({ run_ids: runIds, post_only_ready: postOnlyReady, sandbox }),
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
}

export default api
