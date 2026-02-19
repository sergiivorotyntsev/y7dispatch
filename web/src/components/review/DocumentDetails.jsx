import { useState } from 'react'

/**
 * Section 8: Document Details (Collapsible)
 * Internal fields not sent to CD: buyer/seller info, sale data, raw extraction.
 */
function DocumentDetails({ fields, run, document }) {
  const [expanded, setExpanded] = useState(false)

  // Parse email metadata if document came from email
  const emailMeta = (() => {
    if (!document?.email_metadata_json) return null
    try {
      return typeof document.email_metadata_json === 'string'
        ? JSON.parse(document.email_metadata_json)
        : document.email_metadata_json
    } catch { return null }
  })()

  const internalFields = [
    { key: 'buyer_id', label: 'Buyer ID' },
    { key: 'buyer_name', label: 'Buyer Name' },
    { key: 'seller_name', label: 'Seller Name' },
    { key: 'sale_date', label: 'Sale Date' },
    { key: 'total_amount', label: 'Purchase Amount' },
    { key: 'order_id', label: 'Order ID' },
    { key: 'reference_id', label: 'Reference ID' },
    { key: 'manheim_release_date', label: 'Manheim Release Date' },
    { key: 'manheim_offsite', label: 'Manheim Offsite' },
  ]

  return (
    <div className="bg-gray-50 rounded-lg shadow-sm border border-gray-200 mb-4">
      {/* Collapsible header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-100 rounded-lg transition-colors"
      >
        <span className="text-sm font-medium text-gray-600 flex items-center">
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          Document Details
          <span className="ml-2 text-xs text-gray-400">(internal reference — not sent to CD)</span>
        </span>
        <svg className={`w-4 h-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Collapsible content */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-200">
          {/* Email Origin */}
          {emailMeta && (
            <div className="mt-3 mb-3 p-3 bg-blue-50 rounded-lg border border-blue-100">
              <h5 className="text-xs font-semibold text-blue-700 mb-2 flex items-center">
                <span className="mr-1.5">&#9993;</span> Received via Email
              </h5>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-blue-600">From: </span>
                  <span className="font-medium text-gray-800">{emailMeta.sender || '-'}</span>
                </div>
                <div>
                  <span className="text-blue-600">Date: </span>
                  <span className="font-medium text-gray-800">{emailMeta.date || '-'}</span>
                </div>
                <div className="col-span-2">
                  <span className="text-blue-600">Subject: </span>
                  <span className="font-medium text-gray-800">{emailMeta.subject || '-'}</span>
                </div>
              </div>
            </div>
          )}

          {/* Source badge */}
          {document?.source && (
            <div className="mt-3 mb-2">
              <span className={`inline-flex items-center px-2 py-1 text-xs font-medium rounded-full ${
                document.source === 'email' ? 'bg-blue-100 text-blue-800' :
                document.source === 'webhook' ? 'bg-purple-100 text-purple-800' :
                'bg-gray-100 text-gray-700'
              }`}>
                Source: {document.source === 'email' ? 'Email' : document.source === 'webhook' ? 'Webhook' : 'Manual Upload'}
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 mt-3">
            {internalFields.map(({ key, label }) => {
              const val = fields[key]?.corrected || fields[key]?.predicted || ''
              if (!val) return null
              return (
                <div key={key} className="text-sm">
                  <span className="text-gray-500">{label}: </span>
                  <span className="font-medium text-gray-700">{String(val)}</span>
                </div>
              )
            })}
          </div>

          {/* Raw extraction data */}
          {run?.outputs && (
            <details className="mt-3">
              <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
                Raw extraction data
              </summary>
              <pre className="mt-2 p-3 bg-white rounded border text-xs text-gray-600 overflow-auto max-h-60">
                {JSON.stringify(run.outputs, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

export default DocumentDetails
