/**
 * Section 4: Delivery Location
 * Warehouse dropdown with auto-fill, manual override option.
 */
function DeliverySection({ warehouses, selectedWarehouse, handleWarehouseChange, manualOverride, setManualOverride, fields, updateField }) {
  const wh = warehouses.find(w => w.id.toString() === selectedWarehouse)

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
        Delivery Location
        <span className="ml-2 text-xs text-gray-400 font-normal">(from warehouse settings)</span>
      </h3>

      {/* Warehouse Selector */}
      {warehouses.length > 0 && (
        <div className="mb-3">
          <label className="block text-xs font-medium text-gray-600 mb-1">Warehouse</label>
          <select
            value={selectedWarehouse}
            onChange={(e) => handleWarehouseChange(e.target.value)}
            className="form-select w-full text-sm"
          >
            <option value="">-- Select Warehouse --</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} ({w.city}, {w.state})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Warehouse address readout */}
      {wh && !manualOverride && (
        <div className="p-3 bg-gray-50 rounded border border-gray-200 mb-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Delivery Address</div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-gray-500">Name: </span>
              <span className="font-medium">{wh.name}</span>
            </div>
            <div>
              <span className="text-gray-500">Phone: </span>
              <span className="font-medium">{wh.phone || '-'}</span>
            </div>
            <div className="col-span-2">
              <span className="text-gray-500">Address: </span>
              <span className="font-medium">{wh.address || '-'}</span>
            </div>
            <div>
              <span className="text-gray-500">City: </span>
              <span className="font-medium">{wh.city || '-'}</span>
            </div>
            <div>
              <span className="text-gray-500">State: </span>
              <span className="font-medium">{wh.state || '-'}</span>
            </div>
            <div>
              <span className="text-gray-500">ZIP: </span>
              <span className="font-medium">{wh.zip_code || '-'}</span>
            </div>
            <div>
              <span className="text-gray-500">Contact: </span>
              <span className="font-medium">{wh.contact_name || '-'}</span>
            </div>
            <div>
              <span className="text-gray-500">Contact Phone: </span>
              <span className="font-medium">{wh.contact_phone || '-'}</span>
            </div>
            <div>
              <span className="text-gray-500">Location Type: </span>
              <span className="font-medium">{wh.location_type || 'BUSINESS'}</span>
            </div>
          </div>
        </div>
      )}

      {/* Manual override toggle */}
      <button
        type="button"
        onClick={() => setManualOverride(!manualOverride)}
        className="text-xs text-primary-600 hover:text-primary-800 underline"
      >
        {manualOverride ? 'Use warehouse address' : 'Enter address manually'}
      </button>

      {/* Manual address fields */}
      {manualOverride && (
        <div className="mt-3 space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Delivery Name</label>
            <input type="text" value={fields.delivery_name?.corrected || ''} onChange={(e) => updateField('delivery_name', e.target.value)} className="form-input w-full text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Address <span className="text-red-500">*</span></label>
            <input type="text" value={fields.delivery_address?.corrected || ''} onChange={(e) => updateField('delivery_address', e.target.value)} className="form-input w-full text-sm" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">City <span className="text-red-500">*</span></label>
              <input type="text" value={fields.delivery_city?.corrected || ''} onChange={(e) => updateField('delivery_city', e.target.value)} className="form-input w-full text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">State <span className="text-red-500">*</span></label>
              <input type="text" value={fields.delivery_state?.corrected || ''} onChange={(e) => updateField('delivery_state', e.target.value)} className="form-input w-full text-sm" maxLength={2} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">ZIP <span className="text-red-500">*</span></label>
              <input type="text" value={fields.delivery_zip?.corrected || ''} onChange={(e) => updateField('delivery_zip', e.target.value)} className="form-input w-full text-sm" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Phone</label>
              <input type="text" value={fields.delivery_phone?.corrected || ''} onChange={(e) => updateField('delivery_phone', e.target.value)} className="form-input w-full text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Contact</label>
              <input type="text" value={fields.delivery_contact?.corrected || ''} onChange={(e) => updateField('delivery_contact', e.target.value)} className="form-input w-full text-sm" />
            </div>
          </div>
        </div>
      )}

      {!selectedWarehouse && !manualOverride && (
        <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-700">
          Please select a warehouse or enter a delivery address manually.
        </div>
      )}
    </div>
  )
}

export default DeliverySection
