import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../api'

/**
 * Document Detail / Export Preview Page
 *
 * Shows all extracted fields for a document with export validation.
 * Allows reviewing data before exporting to Central Dispatch.
 */
function DocumentDetail() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState(null)

  useEffect(() => {
    async function loadExportPreview() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.getDocumentExportPreview(id)
        setData(result)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    loadExportPreview()
  }, [id])

  async function handleExport() {
    if (!data?.can_export) return

    setExporting(true)
    setExportResult(null)
    try {
      // Get the extraction run ID
      const runId = data.extraction?.id
      if (!runId) throw new Error('No extraction run found')

      const result = await api.exportToCentralDispatch(runId)
      setExportResult({
        success: true,
        message: 'Successfully exported to Central Dispatch',
        orderId: result.cd_order_id || result.order_id,
      })
    } catch (err) {
      setExportResult({
        success: false,
        message: err.message || 'Export failed',
      })
    } finally {
      setExporting(false)
    }
  }

  async function handleReExtract() {
    try {
      const result = await api.runExtraction(id, true)
      // Reload the page data
      window.location.reload()
    } catch (err) {
      setError(err.message)
    }
  }

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

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-red-800 font-medium">Error loading document</h3>
          <p className="text-red-600 mt-1">{error}</p>
          <button
            onClick={() => navigate('/documents')}
            className="mt-4 text-blue-600 hover:text-blue-800"
          >
            &larr; Back to Documents
          </button>
        </div>
      </div>
    )
  }

  const { document: doc, extraction, fields, can_export, blocking_issues, order_id } = data || {}

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-2">
            <Link to="/documents" className="hover:text-blue-600">&larr; Documents</Link>
            <span>/</span>
            <span>{doc?.filename}</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">
            Document Export Preview
          </h1>
          <div className="flex items-center gap-3 mt-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${
              doc?.auction_type === 'COPART' ? 'bg-blue-100 text-blue-800' :
              doc?.auction_type === 'IAA' ? 'bg-orange-100 text-orange-800' :
              doc?.auction_type === 'MANHEIM' ? 'bg-purple-100 text-purple-800' :
              'bg-gray-100 text-gray-800'
            }`}>
              {doc?.auction_type}
            </span>
            {order_id && (
              <span className="text-sm text-gray-600">
                Order ID: <span className="font-medium">{order_id}</span>
              </span>
            )}
            {extraction?.status && (
              <span className={`px-2 py-1 rounded text-xs font-medium ${
                extraction.status === 'reviewed' || extraction.status === 'approved'
                  ? 'bg-green-100 text-green-800'
                  : extraction.status === 'needs_review'
                  ? 'bg-yellow-100 text-yellow-800'
                  : 'bg-gray-100 text-gray-800'
              }`}>
                {extraction.status}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {extraction && (
            <button
              onClick={() => navigate(`/review/${extraction.id}`)}
              className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
            >
              Edit Fields
            </button>
          )}
          <button
            onClick={handleReExtract}
            className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
          >
            Re-extract
          </button>
          <button
            onClick={handleExport}
            disabled={!can_export || exporting}
            className={`px-4 py-2 rounded-lg font-medium ${
              can_export
                ? 'bg-green-600 text-white hover:bg-green-700'
                : 'bg-gray-200 text-gray-500 cursor-not-allowed'
            }`}
          >
            {exporting ? 'Exporting...' : 'Export to CD'}
          </button>
        </div>
      </div>

      {/* Export Status */}
      {exportResult && (
        <div className={`mb-6 p-4 rounded-lg ${
          exportResult.success
            ? 'bg-green-50 border border-green-200'
            : 'bg-red-50 border border-red-200'
        }`}>
          <p className={exportResult.success ? 'text-green-800' : 'text-red-800'}>
            {exportResult.message}
            {exportResult.orderId && (
              <span className="ml-2 font-medium">
                (Order ID: {exportResult.orderId})
              </span>
            )}
          </p>
        </div>
      )}

      {/* Blocking Issues */}
      {blocking_issues && blocking_issues.length > 0 && (
        <div className="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <h3 className="text-yellow-800 font-medium mb-2">Cannot Export</h3>
          <ul className="list-disc list-inside text-yellow-700 text-sm">
            {blocking_issues.map((issue, idx) => (
              <li key={idx}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Fields Grid */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
          <h2 className="font-medium text-gray-900">Export Fields</h2>
          <p className="text-sm text-gray-500 mt-1">
            Review all fields before exporting to Central Dispatch
          </p>
        </div>

        <div className="divide-y divide-gray-100">
          {fields && fields.length > 0 ? (
            fields.filter(f => f.is_active).map((field, idx) => (
              <div
                key={idx}
                className={`px-4 py-3 flex items-start gap-4 ${
                  !field.value && field.is_required ? 'bg-red-50' : ''
                }`}
              >
                <div className="w-48 flex-shrink-0">
                  <div className="font-medium text-gray-900 text-sm">
                    {field.display_name || field.cd_field}
                  </div>
                  <div className="text-xs text-gray-500">{field.cd_field}</div>
                  {field.is_required && (
                    <span className="text-xs text-red-600">Required</span>
                  )}
                </div>

                <div className="flex-1">
                  {field.value ? (
                    <div className="text-gray-900">{field.value}</div>
                  ) : field.default_value ? (
                    <div className="text-gray-500 italic">
                      Default: {field.default_value}
                    </div>
                  ) : (
                    <div className="text-gray-400 italic">Empty</div>
                  )}
                </div>

                <div className="flex-shrink-0 flex items-center gap-2">
                  {field.confidence !== undefined && field.confidence !== null && (
                    <span className={`text-xs px-2 py-1 rounded ${
                      field.confidence >= 0.8 ? 'bg-green-100 text-green-700' :
                      field.confidence >= 0.5 ? 'bg-yellow-100 text-yellow-700' :
                      'bg-red-100 text-red-700'
                    }`}>
                      {Math.round(field.confidence * 100)}%
                    </span>
                  )}
                  <span className={`text-xs px-2 py-1 rounded ${
                    field.source === 'constant' ? 'bg-purple-100 text-purple-700' :
                    'bg-blue-100 text-blue-700'
                  }`}>
                    {field.source}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="p-8 text-center text-gray-500">
              No fields configured for this auction type.
              <Link
                to="/test-lab"
                className="block mt-2 text-blue-600 hover:text-blue-800"
              >
                Configure Field Mappings
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Extraction Info */}
      {extraction && (
        <div className="mt-6 bg-gray-50 rounded-lg p-4">
          <h3 className="font-medium text-gray-900 mb-2">Extraction Details</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-gray-500">Run ID</div>
              <div className="font-medium">{extraction.id}</div>
            </div>
            <div>
              <div className="text-gray-500">Status</div>
              <div className="font-medium">{extraction.status}</div>
            </div>
            <div>
              <div className="text-gray-500">Confidence</div>
              <div className="font-medium">
                {extraction.confidence_score
                  ? `${Math.round(extraction.confidence_score * 100)}%`
                  : 'N/A'}
              </div>
            </div>
            <div>
              <div className="text-gray-500">Created</div>
              <div className="font-medium">
                {new Date(extraction.created_at).toLocaleString()}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default DocumentDetail
