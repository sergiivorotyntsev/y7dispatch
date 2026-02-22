import { useState, useEffect } from 'react'
import api from '../../api'

/**
 * Section 4: Delivery Location
 * Shows warehouse options with distance/price info.
 * Falls back to simple dropdown when no run context available.
 */
function DeliverySection({ warehouses, selectedWarehouse, handleWarehouseChange, manualOverride, setManualOverride, fields, updateField, runId }) {
  const wh = warehouses.find(w => w.id.toString() === selectedWarehouse)
  const [options, setOptions] = useState(null)
  const [optionsLoading, setOptionsLoading] = useState(false)
  const [optionsError, setOptionsError] = useState(null)

  // Load distance options when runId is available
  useEffect(() => {
    if (!runId) return
    let cancelled = false

    async function loadOptions() {
      setOptionsLoading(true)
      setOptionsError(null)
      try {
        const data = await api.getWarehouseOptionsForRun(runId)
        if (!cancelled) setOptions(data)
      } catch (err) {
        if (!cancelled) {
          // 400 = no pickup ZIP, fall back to simple dropdown
          if (err.message?.includes('400') || err.message?.includes('pickup ZIP')) {
            setOptions(null)
          } else {
            setOptionsError(err.message)
          }
        }
      } finally {
        if (!cancelled) setOptionsLoading(false)
      }
    }

    loadOptions()
    return () => { cancelled = true }
  }, [runId])

  // Auto-select best value if nothing selected yet
  useEffect(() => {
    if (!options?.options?.length || selectedWarehouse) return
    const best = options.options.find(o => o.best_value)
    if (best) {
      handleWarehouseChange(best.warehouse_id.toString())
    }
  }, [options, selectedWarehouse, handleWarehouseChange])

  const hasDistanceOptions = options?.options?.length > 0
  const pickupDisplay = fields?.pickup_city?.corrected || fields?.pickup_city?.predicted || ''
  const pickupState = fields?.pickup_state?.corrected || fields?.pickup_state?.predicted || ''

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
        Delivery Warehouse
        {pickupDisplay && (
          <span className="ml-2 text-xs text-gray-400 font-normal">
            from {pickupDisplay}{pickupState ? `, ${pickupState}` : ''} (pickup)
          </span>
        )}
      </h3>

      {/* Distance-aware options */}
      {optionsLoading ? (
        <div className="p-4 text-center">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600 mx-auto mb-2"></div>
          <p className="text-xs text-gray-500">Calculating distances...</p>
        </div>
      ) : hasDistanceOptions && !manualOverride ? (
        <div className="space-y-2 mb-3">
          {options.options.map((opt, idx) => {
            const isSelected = selectedWarehouse === opt.warehouse_id.toString()
            const isApproximate = opt.distance_source === 'haversine' || opt.distance_source === 'cache'

            return (
              <label
                key={opt.warehouse_id}
                className={`block p-3 rounded border cursor-pointer transition-colors ${
                  isSelected
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300 bg-white'
                }`}
              >
                <div className="flex items-start gap-3">
                  <input
                    type="radio"
                    name="warehouse"
                    checked={isSelected}
                    onChange={() => handleWarehouseChange(opt.warehouse_id.toString())}
                    className="mt-1"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {opt.best_value && idx === 0 && (
                        <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">BEST VALUE</span>
                      )}
                      <span className="text-sm font-medium text-gray-900">{opt.warehouse_name}</span>
                      <span className="text-xs text-gray-400">({opt.city}, {opt.state})</span>
                      {opt.is_default && (
                        <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">Default</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                      {opt.distance_miles != null ? (
                        <>
                          <span>{opt.distance_text || `${Math.round(opt.distance_miles).toLocaleString()} mi`}</span>
                          {opt.duration_text && <span>{opt.duration_text}</span>}
                          {isApproximate && opt.distance_source === 'haversine' && (
                            <span className="text-gray-400">(approximate)</span>
                          )}
                        </>
                      ) : (
                        <span className="text-gray-400">Distance unavailable</span>
                      )}
                      {opt.transport_price != null ? (
                        <span className="font-medium text-gray-700">${opt.transport_price.toLocaleString()}</span>
                      ) : (
                        <span className="text-gray-400">Price: CD subscription required</span>
                      )}
                    </div>
                  </div>
                  {isSelected && (
                    <span className="text-xs text-primary-600 font-medium whitespace-nowrap">Selected</span>
                  )}
                </div>
              </label>
            )
          })}

          {/* Status notes */}
          {!options.google_maps_available && (
            <p className="text-xs text-gray-400 mt-1">
              Distances are approximate. Configure Google Maps API key in Settings for road distances.
            </p>
          )}
        </div>
      ) : !manualOverride && warehouses.length > 0 ? (
        /* Fallback: simple dropdown when no distance data */
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
      ) : null}

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

      {optionsError && (
        <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
          Failed to load distance options: {optionsError}
        </div>
      )}
    </div>
  )
}

export default DeliverySection
