import { useState } from 'react'
import api from '../api'

/**
 * Modal dialog that shows the CD API v2 JSON payload for a document.
 *
 * Props:
 *   documentId   - numeric document ID
 *   warehouseCode - optional warehouse code for delivery stop
 *   onClose       - callback when modal is dismissed
 */
export default function CDPayloadPreview({ documentId, warehouseCode, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [pushing, setPushing] = useState(false)
  const [pushResult, setPushResult] = useState(null)

  const fetchPayload = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.getCDPayload(documentId, warehouseCode)
      setData(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Fetch on mount
  if (!data && !loading && !error) {
    fetchPayload()
  }

  const handlePush = async (dryRun) => {
    setPushing(true)
    setPushResult(null)
    try {
      const res = await api.pushCDListing(documentId, {
        warehouseCode,
        sandbox: true,
        dryRun,
      })
      setPushResult(res)
    } catch (err) {
      setPushResult({ success: false, message: err.message })
    } finally {
      setPushing(false)
    }
  }

  const copyToClipboard = () => {
    if (data?.payload) {
      navigator.clipboard.writeText(JSON.stringify(data.payload, null, 2))
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">
            CD API v2 Payload Preview
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto px-6 py-4">
          {loading && <p className="text-gray-500">Loading payload...</p>}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-red-700">
              {error}
            </div>
          )}

          {data && (
            <>
              {/* Validation status */}
              {data.validation_errors?.length > 0 ? (
                <div className="bg-yellow-50 border border-yellow-200 rounded p-3 mb-4">
                  <p className="font-medium text-yellow-800 mb-1">
                    Validation errors ({data.validation_errors.length})
                  </p>
                  <ul className="list-disc list-inside text-sm text-yellow-700">
                    {data.validation_errors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              ) : (
                <div className="bg-green-50 border border-green-200 rounded p-3 mb-4 text-green-700">
                  Payload is valid and ready to send.
                </div>
              )}

              {/* JSON */}
              <pre className="bg-gray-50 border rounded p-4 text-xs font-mono overflow-auto max-h-[50vh] whitespace-pre-wrap">
                {JSON.stringify(data.payload, null, 2)}
              </pre>
            </>
          )}

          {/* Push result */}
          {pushResult && (
            <div className={`mt-4 p-3 rounded border ${pushResult.success ? 'bg-green-50 border-green-200 text-green-700' : 'bg-red-50 border-red-200 text-red-700'}`}>
              <p className="font-medium">{pushResult.success ? 'Success' : 'Failed'}</p>
              <p className="text-sm">{pushResult.message}</p>
              {pushResult.listing_id && (
                <p className="text-sm mt-1">Listing ID: <code>{pushResult.listing_id}</code></p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t bg-gray-50 gap-3">
          <button
            onClick={copyToClipboard}
            disabled={!data?.payload}
            className="px-4 py-2 text-sm border rounded hover:bg-gray-100 disabled:opacity-50"
          >
            Copy JSON
          </button>
          <div className="flex gap-3">
            <button
              onClick={() => handlePush(true)}
              disabled={pushing || !data?.is_valid}
              className="px-4 py-2 text-sm bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:opacity-50"
            >
              {pushing ? 'Validating...' : 'Dry Run'}
            </button>
            <button
              onClick={() => handlePush(false)}
              disabled={pushing || !data?.is_valid}
              className="px-4 py-2 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
            >
              {pushing ? 'Pushing...' : 'Push to Central Dispatch'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
