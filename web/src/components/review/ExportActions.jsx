/**
 * Section 9: Export Actions
 * Preflight summary, export/save buttons, progress summary.
 *
 * States:
 * - Default: shows preflight + field counter + approve button
 * - isApproved: shows "Export to CD" button, hides approve
 * - isExported: shows exported summary, hides counters/buttons/helper text
 */
import PreflightBanner from '../PreflightBanner'

function ExportActions({
  runId, isTrainingMode, saving,
  handleSubmitTraining, handleSubmitProduction, handleSaveChanges,
  showExportModal, setShowExportModal,
  exportResult, exportError, exporting,
  selectedWarehouse, isApproved, isExported, runStatus,
  correctCount, totalCount, correctedCount, needsReviewCount,
}) {
  return (
    <div className="space-y-4">
      {/* Preflight Banner — hide after export, show "Exported" instead */}
      {isExported ? (
        <div className="mb-4 border rounded-lg bg-green-50 border-green-200">
          <div className="px-4 py-3 flex items-center space-x-3">
            <span className="text-green-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span className="font-medium text-sm text-green-800">Exported to Central Dispatch</span>
            {exportResult?.cd_listing_id && exportResult.cd_listing_id !== 'unknown' && (
              <span className="text-sm text-green-700">
                CD Listing ID: <span className="font-mono font-medium">{exportResult.cd_listing_id}</span>
              </span>
            )}
          </div>
        </div>
      ) : (
        <PreflightBanner
          runId={parseInt(runId)}
          mode={isTrainingMode ? 'training' : 'production'}
          warehouseId={selectedWarehouse ? parseInt(selectedWarehouse) : null}
        />
      )}

      {/* Export to CD section (production only, not yet exported) */}
      {!isTrainingMode && !isExported && (
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

      {/* Bottom Actions Bar — hidden when exported */}
      {!isExported && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex justify-between items-center">
            {/* Field counters */}
            <div className="text-sm text-gray-600">
              <span className="text-green-600 font-medium">{correctCount}</span> correct
              {correctedCount > 0 && (
                <> {' \u2022 '} <span className="text-blue-600 font-medium">{correctedCount}</span> corrected</>
              )}
              {needsReviewCount > 0 && (
                <> {' \u2022 '} <span className="text-orange-600 font-medium">{needsReviewCount}</span> need review</>
              )}
            </div>
            {/* Action buttons */}
            {isTrainingMode ? (
              <button onClick={handleSubmitTraining} className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving...' : 'Save & Train'}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                {/* Save Changes — all non-exported, non-archived */}
                {!isExported && runStatus !== 'archived' && handleSaveChanges && (
                  <button
                    onClick={handleSaveChanges}
                    className="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-300 rounded-md hover:bg-blue-100"
                    disabled={saving}
                  >
                    {saving ? 'Saving...' : 'Save Changes'}
                  </button>
                )}
                {isApproved ? (
                  <span className="px-4 py-2 rounded-md text-sm font-medium bg-green-100 text-green-800 border border-green-300">
                    Approved
                  </span>
                ) : !isExported ? (
                  <button
                    onClick={handleSubmitProduction}
                    className={`btn btn-primary ${selectedWarehouse ? 'bg-green-600 hover:bg-green-700' : 'bg-gray-300 text-gray-500 cursor-not-allowed'}`}
                    disabled={saving || !selectedWarehouse}
                    title={!selectedWarehouse ? 'Select a delivery warehouse first' : ''}
                  >
                    {saving ? 'Approving...' : 'Approve for Export'}
                  </button>
                ) : null}
              </div>
            )}
          </div>
          {/* Warehouse required warning */}
          {!isTrainingMode && !isApproved && !selectedWarehouse && (
            <p className="text-xs text-amber-600 mt-2 font-medium">
              Select a delivery warehouse before approving for export.
            </p>
          )}
          {/* Helper text — hidden when approved */}
          {!isApproved && selectedWarehouse && (
            <p className="text-xs text-gray-500 mt-3">
              {isTrainingMode
                ? 'Your corrections help train the system to extract similar documents more accurately.'
                : 'After approval, this listing will be ready for export to Central Dispatch.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default ExportActions
