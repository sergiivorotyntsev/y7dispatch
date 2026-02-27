/**
 * DocumentsHeader — Title, upload button, and clickable stats cards
 *
 * Status cards (Needs Review, Ready, Exported, Failed) act as filters.
 * Active card gets a colored ring. Click again to clear the filter.
 * Emails and Transport are info-only counters (not clickable filters).
 */
export default function DocumentsHeader({ stats, activeStatus, onStatusFilter, onUploadClick }) {
  const infoCards = [
    { label: 'Emails',    value: stats.total_emails,      color: 'text-gray-900' },
    { label: 'Transport', value: stats.transport_requests, color: 'text-indigo-700' },
  ]

  const filterCards = [
    { key: 'needs_review',    label: 'Needs Review',    value: stats.needs_review,    color: 'text-yellow-600', ring: 'ring-yellow-400' },
    { key: 'ready_to_export', label: 'Ready to Export', value: stats.ready_to_export, color: 'text-blue-600',   ring: 'ring-blue-400' },
    { key: 'exported',        label: 'Exported',        value: stats.exported,        color: 'text-green-600',  ring: 'ring-green-400' },
    { key: 'failed',          label: 'Failed',          value: stats.failed,          color: 'text-red-600',    ring: 'ring-red-400' },
  ]

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

      <div className="grid grid-cols-6 gap-3 mb-6">
        {infoCards.map(card => (
          <div key={card.label} className="bg-white p-4 rounded-lg shadow">
            <p className="text-xs text-gray-500 uppercase tracking-wide">{card.label}</p>
            <p className={`text-2xl font-bold ${card.color}`}>{card.value}</p>
          </div>
        ))}

        {filterCards.map(card => {
          const isActive = activeStatus === card.key
          return (
            <div
              key={card.key}
              onClick={() => onStatusFilter(isActive ? '' : card.key)}
              className={`bg-white p-4 rounded-lg shadow cursor-pointer transition-all hover:shadow-md ${
                isActive ? `ring-2 ${card.ring}` : ''
              }`}
            >
              <p className="text-xs text-gray-500 uppercase tracking-wide">{card.label}</p>
              <p className={`text-2xl font-bold ${card.color}`}>{card.value}</p>
            </div>
          )
        })}
      </div>
    </>
  )
}
