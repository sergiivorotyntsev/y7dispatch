/**
 * DocumentsModals — Upload, Hold, Batch Hold, Batch Post modals
 */

export function UploadModal({
  show, auctionTypes,
  selectedAuctionType, onAuctionTypeChange,
  uploadFile, onFileChange,
  uploading, uploadResult,
  onUpload, onClose, onNavigate,
}) {
  if (!show) return null
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-lg w-full mx-4">
        <h2 className="text-xl font-bold mb-4">Upload Document</h2>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">Auction Type</label>
          <select
            value={selectedAuctionType}
            onChange={(e) => onAuctionTypeChange(e.target.value)}
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
            onChange={(e) => onFileChange(e.target.files[0])}
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
                  {uploadResult.vinDuplicate ? 'Upload successful - Duplicate VIN detected!' : 'Upload successful!'}
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
                      onClick={() => onNavigate(`/review/${uploadResult.vinDuplicate.run_id}`)}
                      className="mt-2 text-orange-700 underline hover:text-orange-900"
                    >
                      View existing listing &rarr;
                    </button>
                  </div>
                )}
                {uploadResult.runId && !uploadResult.vinDuplicate && (
                  <button
                    onClick={() => onNavigate(`/review/${uploadResult.runId}`)}
                    className="mt-2 text-green-700 underline hover:text-green-900"
                  >
                    Review extracted data &rarr;
                  </button>
                )}
              </div>
            ) : (
              <p className="text-red-800">{uploadResult.error}</p>
            )}
          </div>
        )}

        <div className="flex justify-end space-x-3">
          <button onClick={onClose} className="btn btn-secondary" disabled={uploading}>
            {uploadResult?.success ? 'Close' : 'Cancel'}
          </button>
          {!uploadResult?.success && (
            <button
              onClick={onUpload}
              className="btn btn-primary"
              disabled={!uploadFile || uploading}
            >
              {uploading ? 'Uploading...' : 'Upload'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function HoldModal({
  holdModal, holdReason, holdNote,
  onReasonChange, onNoteChange,
  onConfirm, onCancel,
}) {
  if (!holdModal) return null
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
        <h2 className="text-lg font-bold mb-4">Put Document on Hold</h2>
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
          <select value={holdReason} onChange={(e) => onReasonChange(e.target.value)} className="form-select w-full">
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
            onChange={(e) => onNoteChange(e.target.value)}
            placeholder="Additional details..."
            className="form-input w-full text-sm"
          />
        </div>
        <div className="flex justify-end space-x-3">
          <button onClick={onCancel} className="btn btn-secondary">Cancel</button>
          <button onClick={() => onConfirm(holdModal.docId)} className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700">
            Set Hold
          </button>
        </div>
      </div>
    </div>
  )
}

export function BatchHoldModal({
  show, holdCount,
  batchHoldReason, batchHoldNote,
  batchOperating,
  onReasonChange, onNoteChange,
  onConfirm, onCancel,
}) {
  if (!show) return null
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
        <h2 className="text-lg font-bold mb-4">Batch Hold &mdash; {holdCount} Document(s)</h2>
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
          <select value={batchHoldReason} onChange={(e) => onReasonChange(e.target.value)} className="form-select w-full">
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
            onChange={(e) => onNoteChange(e.target.value)}
            placeholder="Additional details..."
            className="form-input w-full text-sm"
          />
        </div>
        <div className="flex justify-end space-x-3">
          <button onClick={onCancel} className="btn btn-secondary">Cancel</button>
          <button
            onClick={onConfirm}
            disabled={batchOperating}
            className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
          >
            {batchOperating ? 'Processing...' : `Set Hold (${holdCount})`}
          </button>
        </div>
      </div>
    </div>
  )
}

export function BatchPostModal({
  show, batchPosting, batchPreflight, batchResult,
  onPost, onClose,
}) {
  if (!show) return null
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">Batch Post to Central Dispatch</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
        </div>

        {batchResult ? (
          <div>
            <div className={`p-4 rounded-lg mb-4 ${
              batchResult.failed === 0 ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'
            }`}>
              <h3 className={`font-medium ${batchResult.failed === 0 ? 'text-green-800' : 'text-yellow-800'}`}>
                Batch Post Complete
              </h3>
              <div className="mt-2 grid grid-cols-3 gap-4 text-sm">
                <div><span className="text-gray-600">Posted:</span><span className="ml-2 font-medium text-green-600">{batchResult.posted}</span></div>
                <div><span className="text-gray-600">Failed:</span><span className="ml-2 font-medium text-red-600">{batchResult.failed}</span></div>
                <div><span className="text-gray-600">Skipped:</span><span className="ml-2 font-medium text-gray-600">{batchResult.skipped}</span></div>
              </div>
            </div>
            <div className="space-y-2 max-h-60 overflow-auto">
              {batchResult.results?.map((result, i) => (
                <div key={i} className={`p-3 rounded text-sm ${
                  result.status === 'success' ? 'bg-green-50' :
                  result.status === 'failed' ? 'bg-red-50' :
                  result.status === 'blocked' ? 'bg-orange-50' : 'bg-gray-50'
                }`}>
                  <div className="flex justify-between items-center">
                    <span className="font-medium">{result.document_filename || `Run ${result.run_id}`}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      result.status === 'success' ? 'bg-green-100 text-green-800' :
                      result.status === 'failed' ? 'bg-red-100 text-red-800' :
                      result.status === 'blocked' ? 'bg-orange-100 text-orange-800' : 'bg-gray-100 text-gray-800'
                    }`}>{result.status}</span>
                  </div>
                  <p className="text-gray-600 mt-1">{result.message}</p>
                  {result.cd_listing_id && <p className="text-green-700 mt-1">CD ID: {result.cd_listing_id}</p>}
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-end">
              <button onClick={onClose} className="btn btn-primary">Close</button>
            </div>
          </div>
        ) : batchPreflight ? (
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
                      {item.reason && <span className="text-orange-700 ml-2">&mdash; {item.reason}</span>}
                      {item.issues?.length > 0 && (
                        <ul className="mt-1 list-disc list-inside text-orange-700">
                          {item.issues.slice(0, 3).map((issue, j) => <li key={j}>{issue}</li>)}
                          {item.issues.length > 3 && <li>...and {item.issues.length - 3} more</li>}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button onClick={onClose} className="btn btn-secondary">Cancel</button>
              {batchPreflight.ready_count > 0 && (
                <button
                  onClick={() => onPost(true)}
                  disabled={batchPosting}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                >
                  {batchPosting ? 'Posting...' : `Post ${batchPreflight.ready_count} Ready Documents`}
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            <span className="ml-3 text-gray-600">Checking documents...</span>
          </div>
        )}
      </div>
    </div>
  )
}
