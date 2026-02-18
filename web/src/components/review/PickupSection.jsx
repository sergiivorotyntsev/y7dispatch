/**
 * Section 3: Pick-Up Location
 * Extracted from document: name, address, city/state/zip, phone, location type, buyer ref, contact.
 * Auto-fill phone from Auction Directory when extraction misses it.
 */
import { useState } from 'react'
import api from '../../api'

function PickupSection({ fields, updateField, highlightedField, setHighlightedField }) {
  const [phoneLookupStatus, setPhoneLookupStatus] = useState(null) // null | 'loading' | 'found' | 'not_found'

  const handlePhoneLookup = async () => {
    const pickupName = fields.pickup_name?.corrected
    if (!pickupName) return

    setPhoneLookupStatus('loading')
    try {
      const result = await api.lookupAuctionLocation(pickupName)
      if (result.found && result.location?.phone) {
        updateField('pickup_phone', result.location.phone)
        // Also fill address fields if empty
        if (!fields.pickup_city?.corrected && result.location.city)
          updateField('pickup_city', result.location.city)
        if (!fields.pickup_state?.corrected && result.location.state)
          updateField('pickup_state', result.location.state)
        if (!fields.pickup_zip?.corrected && result.location.zip)
          updateField('pickup_zip', result.location.zip)
        if (!fields.pickup_address?.corrected && result.location.address)
          updateField('pickup_address', result.location.address)
        setPhoneLookupStatus('found')
      } else {
        setPhoneLookupStatus('not_found')
      }
    } catch {
      setPhoneLookupStatus('not_found')
    }
    // Clear status after 3 seconds
    setTimeout(() => setPhoneLookupStatus(null), 3000)
  }

  const showLookupButton = fields.pickup_name?.corrected && !fields.pickup_phone?.corrected

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        Pick-Up Location
      </h3>

      {/* Location Name */}
      <FieldRow field={fields.pickup_name} fieldKey="pickup_name" updateField={updateField} />

      {/* Address */}
      <FieldRow field={fields.pickup_address} fieldKey="pickup_address" updateField={updateField} />

      {/* City / State / ZIP */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <FieldInput field={fields.pickup_city} fieldKey="pickup_city" label="City" updateField={updateField} required />
        <FieldInput field={fields.pickup_state} fieldKey="pickup_state" label="State" updateField={updateField} required maxLength={2} placeholder="XX" />
        <FieldInput field={fields.pickup_zip} fieldKey="pickup_zip" label="ZIP" updateField={updateField} required maxLength={10} placeholder="12345" />
      </div>

      {/* Phone / Location Type */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Phone</label>
          <div className="flex gap-1">
            <input
              type="text"
              value={fields.pickup_phone?.corrected || ''}
              onChange={(e) => updateField('pickup_phone', e.target.value)}
              className={`form-input w-full text-sm ${
                fields.pickup_phone?.status === 'review' && !fields.pickup_phone?.corrected ? 'border-orange-300 bg-orange-50' : ''
              }`}
              placeholder="(xxx) xxx-xxxx"
            />
            {showLookupButton && (
              <button
                onClick={handlePhoneLookup}
                disabled={phoneLookupStatus === 'loading'}
                className="px-2 py-1 text-xs bg-blue-50 text-blue-600 border border-blue-200 rounded hover:bg-blue-100 whitespace-nowrap"
                title="Lookup phone from auction directory"
              >
                {phoneLookupStatus === 'loading' ? '...' : 'Lookup'}
              </button>
            )}
            {phoneLookupStatus === 'found' && (
              <span className="self-center text-xs text-green-600 whitespace-nowrap">Found</span>
            )}
            {phoneLookupStatus === 'not_found' && (
              <span className="self-center text-xs text-gray-400 whitespace-nowrap">Not found</span>
            )}
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Location Type</label>
          <select
            value={fields.pickup_location_type?.corrected || 'AUCTION'}
            onChange={(e) => updateField('pickup_location_type', e.target.value)}
            className="form-select w-full text-sm"
          >
            <option value="AUCTION">Auction</option>
            <option value="DEALERSHIP">Dealership</option>
            <option value="RESIDENCE">Residence</option>
            <option value="BUSINESS">Business</option>
          </select>
        </div>
      </div>

      {/* Buyer Reference / Contact */}
      <div className="grid grid-cols-2 gap-3">
        <FieldInput field={fields.buyer_id} fieldKey="buyer_id" label="Buyer Reference #" updateField={updateField} />
        <FieldInput field={fields.pickup_contact} fieldKey="pickup_contact" label="Contact Name" updateField={updateField} placeholder="Optional" />
      </div>
    </div>
  )
}

/** Simple field input with label */
function FieldInput({ field, fieldKey, label, updateField, required, maxLength, placeholder }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label || field?.label || fieldKey}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type="text"
        value={field?.corrected || ''}
        onChange={(e) => updateField(fieldKey, e.target.value)}
        className={`form-input w-full text-sm ${
          field?.status === 'review' && !field?.corrected ? 'border-orange-300 bg-orange-50' : ''
        }`}
        placeholder={placeholder || label || fieldKey}
        maxLength={maxLength}
      />
    </div>
  )
}

/** Full-width field row with label and confidence indicator */
function FieldRow({ field, fieldKey, updateField }) {
  if (!field) return null
  return (
    <div className="mb-3">
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {field.label}
        {field.required && <span className="text-red-500 ml-0.5">*</span>}
        {field.confidence != null && field.confidence < 0.6 && (
          <span className="ml-2 text-orange-500 text-xs">Low confidence ({(field.confidence * 100).toFixed(0)}%)</span>
        )}
      </label>
      <input
        type="text"
        value={field.corrected || ''}
        onChange={(e) => updateField(fieldKey, e.target.value)}
        className={`form-input w-full text-sm ${
          field.status === 'review' && !field.corrected ? 'border-orange-300 bg-orange-50' : ''
        }`}
        placeholder={field.label}
      />
    </div>
  )
}

export default PickupSection
