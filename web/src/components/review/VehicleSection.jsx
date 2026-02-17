/**
 * Section 2: Vehicle Information
 * VIN (readonly), Year/Make/Model/Color, Lot, Type dropdown, Inoperable toggle, Trailer Type.
 */
function VehicleSection({ fields, updateField, trailerType, setTrailerType, highlightedField, setHighlightedField }) {
  const vehicleFields = ['vehicle_vin', 'vehicle_year', 'vehicle_make', 'vehicle_model', 'vehicle_color', 'vehicle_lot']

  const isInoperable = fields.vehicle_is_inoperable?.corrected === 'true' || fields.vehicle_is_inoperable?.corrected === true

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h1m8-1a1 1 0 01-1 1H9m4-1V8a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a1 1 0 01-1 1h-1m-6-1a1 1 0 001 1h1M5 17a2 2 0 104 0m-4 0a2 2 0 114 0m6 0a2 2 0 104 0m-4 0a2 2 0 114 0" />
        </svg>
        Vehicle Information
      </h3>

      {/* VIN - readonly with visual lock */}
      {fields.vehicle_vin && (
        <div className="mb-3">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            VIN <span className="text-red-500">*</span>
            <span className="ml-1 text-gray-400 font-normal">(verified from document)</span>
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={fields.vehicle_vin.corrected || ''}
              onChange={(e) => updateField('vehicle_vin', e.target.value)}
              className="form-input flex-1 text-sm font-mono bg-gray-50"
              maxLength={17}
            />
            {fields.vehicle_vin.confidence >= 0.9 && (
              <span className="text-green-500" title="High confidence">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Year / Make / Model / Color in grid */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        {['vehicle_year', 'vehicle_make', 'vehicle_model', 'vehicle_color'].map((key) => {
          const f = fields[key]
          if (!f) return null
          return (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                {f.label}
                {f.required && <span className="text-red-500 ml-0.5">*</span>}
              </label>
              <input
                type={key === 'vehicle_year' ? 'number' : 'text'}
                value={f.corrected || ''}
                onChange={(e) => updateField(key, e.target.value)}
                className={`form-input w-full text-sm ${
                  f.status === 'review' && !f.corrected ? 'border-orange-300 bg-orange-50' : ''
                }`}
                placeholder={f.label}
              />
            </div>
          )
        })}
      </div>

      {/* Lot Number */}
      {fields.vehicle_lot && (
        <div className="mb-3">
          <label className="block text-xs font-medium text-gray-600 mb-1">Lot/Stock Number</label>
          <input
            type="text"
            value={fields.vehicle_lot.corrected || ''}
            onChange={(e) => updateField('vehicle_lot', e.target.value)}
            className="form-input w-full text-sm"
            placeholder="Lot number"
          />
        </div>
      )}

      {/* Vehicle Type + Trailer Type + Inoperable in a row */}
      <div className="grid grid-cols-3 gap-3">
        {/* Vehicle Type */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Vehicle Type
            <span className="text-gray-400 ml-1 font-normal">(CD auto-detects from VIN)</span>
          </label>
          <select
            value={fields.vehicle_type?.corrected || 'CAR'}
            onChange={(e) => updateField('vehicle_type', e.target.value)}
            className="form-select w-full text-sm"
          >
            <option value="CAR">CAR</option>
            <option value="SUV">SUV</option>
            <option value="TRUCK">TRUCK</option>
            <option value="VAN">VAN</option>
            <option value="MOTORCYCLE">MOTORCYCLE</option>
            <option value="COUPE">COUPE</option>
            <option value="CONVERTIBLE">CONVERTIBLE</option>
            <option value="WAGON">WAGON</option>
          </select>
        </div>

        {/* Trailer Type */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Trailer Type <span className="text-red-500">*</span>
          </label>
          <select
            value={trailerType}
            onChange={(e) => setTrailerType(e.target.value)}
            className="form-select w-full text-sm"
          >
            <option value="OPEN">OPEN</option>
            <option value="ENCLOSED">ENCLOSED</option>
            <option value="DRIVEAWAY">DRIVEAWAY</option>
          </select>
        </div>

        {/* Inoperable Toggle */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Inoperable?</label>
          <button
            type="button"
            onClick={() => updateField('vehicle_is_inoperable', isInoperable ? 'false' : 'true')}
            className={`w-full px-3 py-2 rounded text-sm font-medium border transition-colors ${
              isInoperable
                ? 'bg-red-100 text-red-800 border-red-300'
                : 'bg-green-50 text-green-800 border-green-300'
            }`}
          >
            {isInoperable ? 'INOPERABLE' : 'OPERABLE'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default VehicleSection
