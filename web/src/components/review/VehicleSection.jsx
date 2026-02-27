/**
 * Section 2: Vehicle Information
 * VIN (readonly), Year/Make/Model/Color, Lot, Type dropdown, Inoperable toggle, Trailer Type.
 * Shows validation badges from NHTSA VIN decode (verified/mismatch/unverified).
 */
function VehicleSection({ fields, updateField, trailerType, setTrailerType, validation, validating, onValidate }) {
  const isInoperable = fields.vehicle_is_inoperable?.corrected === 'true' || fields.vehicle_is_inoperable?.corrected === true

  // Map field keys to validation result keys
  const vFields = validation?.vehicle || {}
  const summary = validation?.summary

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-900 flex items-center">
          <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h1m8-1a1 1 0 01-1 1H9m4-1V8a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a1 1 0 01-1 1h-1m-6-1a1 1 0 001 1h1M5 17a2 2 0 104 0m-4 0a2 2 0 114 0m6 0a2 2 0 104 0m-4 0a2 2 0 114 0" />
          </svg>
          Vehicle Information
        </h3>
        <button
          onClick={onValidate}
          disabled={validating}
          className="px-3 py-1 text-xs font-medium rounded border transition-colors bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 disabled:opacity-50"
        >
          {validating ? 'Validating...' : validation ? 'Re-validate' : 'Validate'}
        </button>
      </div>

      {/* Validation summary */}
      {summary && <ValidationSummary summary={summary} section="vehicle" />}

      {/* VIN */}
      {fields.vehicle_vin && (
        <div className="mb-3">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            VIN <span className="text-red-500">*</span>
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={fields.vehicle_vin.corrected || ''}
              onChange={(e) => updateField('vehicle_vin', e.target.value)}
              className="form-input flex-1 text-sm font-mono bg-gray-50"
              maxLength={17}
            />
            <FieldBadge info={vFields.vin} />
          </div>
          {vFields.vin?.status === 'mismatch' && vFields.vin?.message && (
            <p className="text-xs text-red-600 mt-1">{vFields.vin.message}</p>
          )}
        </div>
      )}

      {/* Year / Make / Model / Color in grid */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        {['vehicle_year', 'vehicle_make', 'vehicle_model', 'vehicle_color'].map((key) => {
          const f = fields[key]
          if (!f) return null
          // Map field key to validation key (vehicle_year -> year, vehicle_make -> make, etc.)
          const vKey = key.replace('vehicle_', '')
          const vInfo = vFields[vKey]
          return (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                {f.label}
                {f.required && <span className="text-red-500 ml-0.5">*</span>}
              </label>
              <div className="flex items-center gap-2">
                <input
                  type={key === 'vehicle_year' ? 'number' : 'text'}
                  value={f.corrected || ''}
                  onChange={(e) => updateField(key, e.target.value)}
                  className={`form-input w-full text-sm ${
                    f.status === 'review' && !f.corrected ? 'border-orange-300 bg-orange-50' : ''
                  }`}
                  placeholder={f.label}
                />
                <FieldBadge info={vInfo} />
              </div>
              {vInfo?.status === 'mismatch' && vInfo?.decoded && (
                <button
                  onClick={() => updateField(key, vInfo.decoded)}
                  className="text-xs text-blue-600 hover:text-blue-800 mt-0.5"
                >
                  Use "{vInfo.decoded}"
                </button>
              )}
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
            value={fields.vehicle_type?.corrected || 'SEDAN'}
            onChange={(e) => updateField('vehicle_type', e.target.value)}
            className="form-select w-full text-sm"
          >
            <option value="SEDAN">Sedan</option>
            <option value="SUV">SUV</option>
            <option value="COUPE">Coupe</option>
            <option value="CONVERTIBLE">Convertible</option>
            <option value="WAGON">Wagon</option>
            <option value="TRUCK">Truck</option>
            <option value="VAN">Van</option>
            <option value="MOTORCYCLE">Motorcycle</option>
            <option value="OTHER">Other</option>
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

/** Validation badge: checkmark (verified), warning (unverified), X (mismatch) */
function FieldBadge({ info }) {
  if (!info) return null
  const { status } = info
  if (status === 'verified') {
    return (
      <span className="text-green-500 flex-shrink-0" title="Verified">
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
      </span>
    )
  }
  if (status === 'mismatch') {
    return (
      <span className="text-red-500 flex-shrink-0" title="Mismatch">
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
        </svg>
      </span>
    )
  }
  if (status === 'unverified') {
    return (
      <span className="text-yellow-500 flex-shrink-0" title="Could not verify">
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
      </span>
    )
  }
  return null
}

/** Summary badge for a section */
function ValidationSummary({ summary, section }) {
  if (!summary) return null

  const isOk = section === 'vehicle' ? summary.vehicle_ok : summary.pickup_ok
  const { total_mismatch, total_unverified } = summary

  if (isOk && total_mismatch === 0) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1 mb-3">
        <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
        All fields verified
      </div>
    )
  }

  const issues = total_mismatch + total_unverified
  return (
    <div className="flex items-center gap-1.5 text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded px-2 py-1 mb-3">
      <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
        <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
      </svg>
      {total_mismatch > 0 ? `${total_mismatch} mismatch${total_mismatch > 1 ? 'es' : ''}` : ''}
      {total_mismatch > 0 && total_unverified > 0 ? ', ' : ''}
      {total_unverified > 0 ? `${total_unverified} unverified` : ''}
      {issues === 0 ? 'Needs attention' : ''}
    </div>
  )
}

export default VehicleSection
