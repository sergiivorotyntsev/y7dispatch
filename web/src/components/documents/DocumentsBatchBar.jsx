/**
 * DocumentsBatchBar — Batch action toolbar + operation result banner
 */
export default function DocumentsBatchBar({
  selectedCount,
  eligibility,
  batchOperating, batchPosting,
  batchOpResult,
  onApprove, onExportPreflight, onHold, onArchive,
  onClearSelection, onDismissResult,
}) {
  return (
    <>
      {/* Batch Action Toolbar */}
      {selectedCount > 0 && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-3 flex-wrap sticky top-0 z-10">
          <span className="text-sm font-medium text-blue-800">
            {selectedCount} selected
          </span>
          <div className="h-5 w-px bg-blue-300" />
          {eligibility.approveRunIds.length > 0 && (
            <button
              onClick={onApprove}
              disabled={batchOperating}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              {batchOperating ? '...' : `Approve (${eligibility.approveRunIds.length})`}
            </button>
          )}
          {eligibility.exportRunIds.length > 0 && (
            <button
              onClick={onExportPreflight}
              disabled={batchPosting}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {batchPosting ? '...' : `Export (${eligibility.exportRunIds.length})`}
            </button>
          )}
          {eligibility.holdDocIds.length > 0 && (
            <button
              onClick={onHold}
              disabled={batchOperating}
              className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
            >
              Hold ({eligibility.holdDocIds.length})
            </button>
          )}
          {eligibility.archiveDocIds.length > 0 && (
            <button
              onClick={onArchive}
              disabled={batchOperating}
              className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
            >
              Archive ({eligibility.archiveDocIds.length})
            </button>
          )}
          <button
            onClick={onClearSelection}
            className="ml-auto text-sm text-blue-600 hover:text-blue-800"
          >
            Clear Selection
          </button>
        </div>
      )}

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
              onClick={onDismissResult}
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
    </>
  )
}
