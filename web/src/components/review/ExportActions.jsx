/**
 * Section 9: Export Actions
 * Preflight summary, export/save buttons, progress summary.
 */
import PreflightBanner from '../PreflightBanner'

function ExportActions({
  runId, isTrainingMode, saving,
  handleSubmitTraining, handleSubmitProduction,
  showExportModal, setShowExportModal,
  exportResult, exportError, exporting,
  selectedWarehouse,
  correctCount, totalCount, correctedCount, needsReviewCount,
}) {
  return (
    <div className="space-y-4">
      {/* Preflight Banner */}
      <PreflightBanner
        runId={parseInt(runId)}
        mode={isTrainingMode ? 'training' : 'production'}
        warehouseId={selectedWarehouse ? parseInt(selectedWarehouse) : null}
      />

      {/* Export to CD section (production only) */}
      {!isTrainingMode && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          {exportResult ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-100 text-purple-800">
                  Exported
                </span>
                <span className="text-sm text-gray-600">
                  CD Listing ID: <span className="font-mono font-medium">{exportResult.cd_listing_id}</span>
                </span>
              </div>
            </div>
          ) : (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-3">Export to Central Dispatch</h3>
              {exportError && (
                <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                  <p className="font-medium">Export failed</p>
                  <p>{exportError}</p>
                </div>
              )}
              <button
                onClick={() => setShowExportModal(true)}
                disabled={exporting}
                className="btn btn-primary bg-green-600 hover:bg-green-700"
              >
                {exporting ? 'Exporting...' : 'Export to CD'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Bottom Actions Bar */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <div className="flex justify-between items-center">
          <div className="text-sm text-gray-600">
            <span className="text-green-600 font-medium">{correctCount}</span> correct
            {correctedCount > 0 && (
              <> {' \u2022 '} <span className="text-blue-600 font-medium">{correctedCount}</span> corrected</>
            )}
            {needsReviewCount > 0 && (
              <> {' \u2022 '} <span className="text-orange-600 font-medium">{needsReviewCount}</span> need review</>
            )}
          </div>
          {isTrainingMode ? (
            <button onClick={handleSubmitTraining} className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving...' : 'Save & Train'}
            </button>
          ) : (
            <button onClick={handleSubmitProduction} className="btn btn-primary bg-green-600 hover:bg-green-700" disabled={saving}>
              {saving ? 'Approving...' : 'Approve for Export'}
            </button>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-3">
          {isTrainingMode
            ? 'Your corrections help train the system to extract similar documents more accurately.'
            : 'After approval, this listing will be ready for export to Central Dispatch.'}
        </p>
      </div>
    </div>
  )
}

export default ExportActions
