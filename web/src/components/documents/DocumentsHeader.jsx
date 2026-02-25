/**
 * DocumentsHeader — Title, upload button, and stats cards
 */
export default function DocumentsHeader({ stats, onUploadClick }) {
  return (
    <>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="text-sm text-gray-500 mt-1">
            Production documents for Central Dispatch export
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={onUploadClick} className="btn btn-primary">
            Upload Document
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Total</p>
          <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Needs Review</p>
          <p className="text-2xl font-bold text-yellow-600">{stats.needs_review}</p>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Ready to Export</p>
          <p className="text-2xl font-bold text-blue-600">{stats.ready_to_export}</p>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-sm text-gray-500">Exported</p>
          <p className="text-2xl font-bold text-green-600">{stats.exported}</p>
        </div>
      </div>
    </>
  )
}
