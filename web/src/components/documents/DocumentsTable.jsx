import { Fragment } from 'react'
import { parseUTCDate } from '../../utils/date'
import WeatherIndicator from '../WeatherIndicator'
import { groupByDate } from '../../hooks/useDocuments'
import CopyableCell from './CopyableCell'

/**
 * DocumentsTable — Table with date groups, document rows, pagination
 */
export default function DocumentsTable({
  loading, documents, docExtractions, warehouses,
  selectedDocs, collapsedDates, editingPrice,
  extractingDocId, exportingDocId,
  pagination,
  onRowClick, onToggleSelect, onToggleSelectAll,
  onToggleDate, onWarehouseChange,
  onEditPrice, onSetEditingPrice,
  onRunExtraction, onExportPreview,
  onReleaseHold, onHold, onArchive, onDelete,
  onPageChange, onUploadClick,
  getSourceDisplay, navigate,
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        <span className="ml-3 text-gray-600">Loading documents...</span>
      </div>
    )
  }

  if (documents.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-8 text-center">
        <p className="text-gray-500 mb-4">No documents found</p>
        <button onClick={onUploadClick} className="btn btn-primary">Upload First Document</button>
      </div>
    )
  }

  return (
    <>
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-3">
                <input
                  type="checkbox"
                  checked={selectedDocs.size === documents.length && documents.length > 0}
                  onChange={onToggleSelectAll}
                  className="form-checkbox h-4 w-4 text-primary-600"
                />
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Load ID</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">VIN</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Auction</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pickup</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Warehouse</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Auction Cost</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Transport</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">$/mile</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Received</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {groupByDate(documents).map(([date, dateDocs]) => {
              const isCollapsed = collapsedDates.has(date)
              return (
                <Fragment key={date}>
                  <tr
                    className="bg-gray-100 cursor-pointer hover:bg-gray-200"
                    onClick={() => onToggleDate(date)}
                  >
                    <td colSpan={13} className="px-4 py-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold text-gray-700">
                          {date} <span className="font-normal text-gray-500">({dateDocs.length} {dateDocs.length === 1 ? 'load' : 'loads'})</span>
                        </span>
                        <span className="text-gray-400 text-xs">{isCollapsed ? '\u25B6' : '\u25BC'}</span>
                      </div>
                    </td>
                  </tr>
                  {!isCollapsed && dateDocs.map((doc) => (
                    <DocumentRow
                      key={doc.id}
                      doc={doc}
                      extraction={docExtractions[doc.id]}
                      warehouses={warehouses}
                      isSelected={selectedDocs.has(doc.id)}
                      editingPrice={editingPrice}
                      extractingDocId={extractingDocId}
                      exportingDocId={exportingDocId}
                      onRowClick={onRowClick}
                      onToggleSelect={onToggleSelect}
                      onWarehouseChange={onWarehouseChange}
                      onEditPrice={onEditPrice}
                      onSetEditingPrice={onSetEditingPrice}
                      onRunExtraction={onRunExtraction}
                      onExportPreview={onExportPreview}
                      onReleaseHold={onReleaseHold}
                      onHold={onHold}
                      onArchive={onArchive}
                      onDelete={onDelete}
                      getSourceDisplay={getSourceDisplay}
                      navigate={navigate}
                    />
                  ))}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pagination.total > pagination.limit && (
        <div className="flex items-center justify-between mt-4 px-4 py-3 bg-gray-50 rounded-lg">
          <div className="text-sm text-gray-600">
            Showing {((pagination.page - 1) * pagination.limit) + 1} to {Math.min(pagination.page * pagination.limit, pagination.total)} of {pagination.total} documents
          </div>
          <div className="flex space-x-2">
            <button
              onClick={() => onPageChange(Math.max(1, pagination.page - 1))}
              disabled={pagination.page === 1}
              className="btn btn-sm btn-secondary disabled:opacity-50"
            >
              Previous
            </button>
            <span className="px-3 py-1 bg-white border rounded text-sm">
              Page {pagination.page} of {Math.ceil(pagination.total / pagination.limit)}
            </span>
            <button
              onClick={() => onPageChange(Math.min(Math.ceil(pagination.total / pagination.limit), pagination.page + 1))}
              disabled={pagination.page >= Math.ceil(pagination.total / pagination.limit)}
              className="btn btn-sm btn-secondary disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </>
  )
}

/** Single document row */
function DocumentRow({
  doc, extraction, warehouses,
  isSelected, editingPrice, extractingDocId, exportingDocId,
  onRowClick, onToggleSelect, onWarehouseChange,
  onEditPrice, onSetEditingPrice,
  onRunExtraction, onExportPreview,
  onReleaseHold, onHold, onArchive, onDelete,
  getSourceDisplay, navigate,
}) {
  const isPending = !!doc.pending_reason
  const isOnHold = !!doc.hold_reason
  const rawOutputs = extraction?.outputs || extraction?.outputs_json
  const outputs = rawOutputs
    ? (typeof rawOutputs === 'string' ? JSON.parse(rawOutputs) : rawOutputs)
    : {}

  const loadId = doc.load_id || outputs.load_id || ''
  const vin = doc.vin || outputs.vehicle_vin || ''
  const vehicleYear = doc.vehicle_year || outputs.vehicle_year || ''
  const vehicleMake = doc.vehicle_make || outputs.vehicle_make || ''
  const vehicleModel = doc.vehicle_model || outputs.vehicle_model || ''
  const vehicleDesc = vehicleYear || vehicleMake || vehicleModel
    ? `${vehicleYear} ${vehicleMake} ${vehicleModel}`.trim()
    : '-'
  const lotNumber = doc.vehicle_lot || outputs.vehicle_lot || ''
  const gatePass = doc.gate_pass || outputs.gate_pass || ''

  const pickupCity = doc.pickup_city || outputs.pickup_city || ''
  const pickupState = doc.pickup_state || outputs.pickup_state || ''
  const pickupName = doc.pickup_name || outputs.pickup_name || ''
  const pickupLocation = pickupCity && pickupState
    ? `${pickupCity}, ${pickupState}`
    : pickupName || pickupState || '-'

  const priceTotal = doc.transport_price != null ? doc.transport_price
    : doc.price_total != null ? doc.price_total
    : outputs.price_total != null ? outputs.price_total
    : null

  const auctionCost = doc.auction_cost != null ? doc.auction_cost
    : outputs.total_amount != null ? parseFloat(outputs.total_amount)
    : null

  const distanceMiles = doc.distance_miles != null ? doc.distance_miles
    : outputs.distance_miles != null ? parseFloat(outputs.distance_miles)
    : null
  const ratePerMile = doc.rate_per_mile != null ? doc.rate_per_mile
    : (priceTotal != null && distanceMiles > 0) ? (priceTotal / distanceMiles).toFixed(2)
    : null

  const warehouseId = doc.warehouse_id || outputs.warehouse_id
  const warehouseName = doc.warehouse_name || (warehouseId ? (warehouses.find(w => w.id === parseInt(warehouseId))?.name || '') : '')

  const sourceDisplay = getSourceDisplay(doc)
  const extStatus = doc.extraction_status || extraction?.status
  const extRunId = doc.extraction_run_id || extraction?.id
  const isExported = extStatus === 'exported'
  const isReady = extStatus && ['reviewed', 'approved'].includes(extStatus)

  return (
    <tr
      className={`hover:bg-gray-50 cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}
      onClick={() => onRowClick(doc)}
    >
      <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={(e) => onToggleSelect(doc.id, e)}
          className="form-checkbox h-4 w-4 text-primary-600"
        />
      </td>
      <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
        <CopyableCell value={loadId} mono />
      </td>
      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
        <CopyableCell value={vin} mono />
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-col">
          <span className="text-sm font-medium text-gray-900">{vehicleDesc}</span>
          {lotNumber && <span className="text-xs text-gray-500">Lot: {lotNumber}</span>}
          {gatePass && (
            <span className="text-xs text-gray-500" onClick={(e) => e.stopPropagation()}>
              GP: <CopyableCell value={gatePass} mono />
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3">
        <span className={`px-2 py-1 text-xs font-medium rounded ${
          doc.auction_type_code === 'COPART' ? 'bg-blue-100 text-blue-800' :
          doc.auction_type_code === 'IAA' ? 'bg-purple-100 text-purple-800' :
          doc.auction_type_code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
          'bg-gray-100 text-gray-800'
        }`}>
          {doc.auction_type_code || '?'}
        </span>
      </td>
      <td className="px-4 py-3">
        <span className="text-sm text-gray-700">{pickupLocation}</span>
      </td>
      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
        <select
          value={warehouseId || ''}
          onChange={(e) => onWarehouseChange(doc.id, e.target.value, e)}
          disabled={isExported || !extraction}
          className={`form-select form-select-sm text-xs ${
            isExported ? 'bg-gray-100 cursor-not-allowed' : ''
          } ${!warehouseId ? 'border-orange-300' : ''}`}
        >
          <option value="">{warehouseName || 'Select...'}</option>
          {warehouses.map((wh) => (
            <option key={wh.id} value={wh.id}>{wh.state} - {wh.name} ({wh.city})</option>
          ))}
        </select>
        {warehouseId && warehouseName && (() => {
          const wh = warehouses.find(w => w.id === parseInt(warehouseId))
          return wh ? (
            <div className="text-xs text-gray-400 mt-0.5 flex items-center">
              <span>{wh.city || ''}{wh.state ? `, ${wh.state}` : ''}</span>
              <WeatherIndicator runId={extRunId} warehouseId={warehouseId} />
            </div>
          ) : null
        })()}
      </td>
      <td className="px-4 py-3 text-right text-sm text-gray-500">
        {auctionCost != null ? `$${parseFloat(auctionCost).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : '\u2014'}
      </td>
      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
        {editingPrice.docId === doc.id ? (
          <input
            type="number"
            min="0"
            step="0.01"
            value={editingPrice.value}
            onChange={(e) => onSetEditingPrice({ docId: doc.id, value: e.target.value })}
            onBlur={(e) => onEditPrice(doc.id, e)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onEditPrice(doc.id, e)
              if (e.key === 'Escape') onSetEditingPrice({ docId: null, value: '' })
            }}
            autoFocus
            className="form-input w-24 text-sm px-2 py-1 border-primary-500"
            placeholder="0.00"
          />
        ) : (
          <button
            className={`text-sm ${priceTotal != null ? 'font-medium text-gray-900' : 'text-gray-400'} ${
              !isExported && extraction ? 'hover:text-primary-600 cursor-pointer' : ''
            }`}
            onClick={(e) => {
              if (!isExported && extraction) {
                e.stopPropagation()
                onSetEditingPrice({ docId: doc.id, value: priceTotal != null ? priceTotal : '' })
              }
            }}
            disabled={isExported || !extraction}
          >
            {priceTotal != null ? `$${parseFloat(priceTotal).toFixed(0)}` : '\u2014'}
          </button>
        )}
      </td>
      <td className="px-4 py-3 text-right text-sm text-gray-500">
        {ratePerMile != null ? `$${ratePerMile}` : '\u2014'}
      </td>
      <td className="px-4 py-3">
        {isOnHold && (
          <span className="px-2 py-1 text-xs font-medium rounded bg-red-100 text-red-800 mr-1" title={`${doc.hold_reason}${doc.hold_note ? ': ' + doc.hold_note : ''}`}>
            HOLD
          </span>
        )}
        {isPending && !isOnHold && (
          <span className="px-2 py-1 text-xs font-medium rounded bg-amber-100 text-amber-800 mr-1" title={doc.pending_reason}>
            Pending
          </span>
        )}
        <span className={`px-2 py-1 text-xs font-medium rounded ${
          extStatus === 'needs_review' ? 'bg-yellow-100 text-yellow-800' :
          extStatus === 'reviewed' || extStatus === 'approved' ? 'bg-green-100 text-green-800' :
          extStatus === 'exported' ? 'bg-blue-100 text-blue-800' :
          extStatus === 'manual_required' ? 'bg-orange-100 text-orange-800' :
          extStatus === 'failed' ? 'bg-red-100 text-red-800' :
          'bg-gray-100 text-gray-600'
        }`}>
          {extStatus === 'needs_review' ? 'Needs Review' :
           extStatus === 'reviewed' || extStatus === 'approved' ? 'Reviewed' :
           extStatus === 'exported' ? 'Exported' :
           extStatus === 'manual_required' ? 'OCR Required' :
           extStatus === 'failed' ? 'Failed' :
           extStatus || 'No Data'}
        </span>
      </td>
      <td className="px-4 py-3">
        <span className={`px-2 py-1 text-xs font-medium rounded ${sourceDisplay.color}`}>
          {sourceDisplay.label}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {(() => {
          const dateStr = doc.email_received_date || doc.created_at
          if (!dateStr) return '-'
          const d = parseUTCDate(dateStr)
          if (!d || isNaN(d.getTime())) return '-'
          return (
            <span title={d.toLocaleString()}>
              {d.toLocaleString('en-US', {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
              })}
            </span>
          )
        })()}
      </td>
      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-end items-center space-x-2">
          {extRunId ? (
            <>
              <button
                onClick={() => navigate(`/review/${extRunId}`)}
                className="text-sm text-blue-600 hover:text-blue-800"
              >
                {extStatus === 'needs_review' || extStatus === 'manual_required' ? 'Review' : 'View'}
              </button>
              {isReady && !isExported && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onExportPreview({ extractionId: extRunId, documentId: doc.id })
                  }}
                  className="text-sm text-green-600 hover:text-green-800 font-medium"
                >
                  Export
                </button>
              )}
              {!isExported && (
                <button
                  onClick={() => onRunExtraction(doc.id, true)}
                  disabled={extractingDocId === doc.id}
                  className="text-sm text-orange-600 hover:text-orange-800"
                >
                  {extractingDocId === doc.id ? '...' : 'Re-run'}
                </button>
              )}
            </>
          ) : (
            <button
              onClick={() => onRunExtraction(doc.id)}
              disabled={extractingDocId === doc.id}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              {extractingDocId === doc.id ? 'Processing...' : 'Extract'}
            </button>
          )}
          {isOnHold ? (
            <button onClick={(e) => onReleaseHold(doc.id, e)} className="text-sm text-amber-600 hover:text-amber-800">Unhold</button>
          ) : !isExported ? (
            <button onClick={(e) => { e.stopPropagation(); onHold({ docId: doc.id }) }} className="text-sm text-gray-500 hover:text-gray-700">Hold</button>
          ) : null}
          {isExported ? (
            <button onClick={(e) => onArchive(doc.id, e)} className="text-sm text-gray-500 hover:text-gray-700">Archive</button>
          ) : (
            <button onClick={(e) => onDelete(doc.id, e)} className="text-sm text-red-600 hover:text-red-800">Del</button>
          )}
        </div>
      </td>
    </tr>
  )
}
