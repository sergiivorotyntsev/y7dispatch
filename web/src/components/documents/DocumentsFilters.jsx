/**
 * DocumentsFilters — Search, auction type, status, sort, per page
 */
export default function DocumentsFilters({
  search, onSearchChange,
  filter, onFilterChange,
  auctionTypes,
  sortConfig, onSortChange,
  pagination, onLimitChange,
  onRefresh, onExpandAll, onCollapseAll,
}) {
  return (
    <div className="bg-white p-4 rounded-lg shadow mb-6">
      <div className="mb-3">
        <input
          type="text"
          placeholder="Search by VIN, make, model, lot, or gate pass..."
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          className="form-input w-full text-sm"
        />
      </div>
      <div className="flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Auction Type</label>
          <select
            value={filter.auction_type_id}
            onChange={(e) => onFilterChange({ ...filter, auction_type_id: e.target.value })}
            className="form-select"
          >
            <option value="">All Types</option>
            {auctionTypes.map((at) => (
              <option key={at.id} value={at.id}>{at.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
          <select
            value={filter.status}
            onChange={(e) => onFilterChange({ ...filter, status: e.target.value })}
            className="form-select"
          >
            <option value="">All Status</option>
            <option value="needs_review">Needs Review</option>
            <option value="reviewed">Ready to Export</option>
            <option value="exported">Exported</option>
            <option value="manual_required">OCR Required</option>
            <option value="pending">Pending</option>
            <option value="hold">On Hold</option>
            <option value="failed">Failed</option>
            <option value="archived">Archived</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Sort By</label>
          <select
            value={`${sortConfig.sortBy}-${sortConfig.sortOrder}`}
            onChange={(e) => {
              const [sortBy, sortOrder] = e.target.value.split('-')
              onSortChange({ sortBy, sortOrder })
            }}
            className="form-select"
          >
            <option value="created_at-desc">Newest First</option>
            <option value="created_at-asc">Oldest First</option>
            <option value="filename-asc">Filename A-Z</option>
            <option value="filename-desc">Filename Z-A</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Per Page</label>
          <select
            value={pagination.limit}
            onChange={(e) => onLimitChange(parseInt(e.target.value))}
            className="form-select"
          >
            <option value={10}>10</option>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
        <button onClick={onRefresh} className="btn btn-secondary">Refresh</button>
        <button onClick={onExpandAll} className="btn btn-secondary text-xs" title="Expand all date groups">Expand All</button>
        <button onClick={onCollapseAll} className="btn btn-secondary text-xs" title="Collapse all date groups">Collapse All</button>
      </div>
    </div>
  )
}
