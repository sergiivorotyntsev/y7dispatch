/**
 * Section 3: Pick-Up Location
 * Extracted from document: name, address, city/state/zip, phone, location type, buyer ref, contact.
 * Auto-fill phone from Auction Directory when extraction misses it.
 * Shows validation badges from directory + ZIP cross-check (verified/mismatch/unverified).
 */
import { useState } from 'react'
import api from '../../api'

function PickupSection({ fields, updateField, highlightedField, setHighlightedField, validation }) {
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
  const pFields = validation?.pickup || {}

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        Pick-Up Location
        {validation?.summary?.pickup_ok && (
          <span className={`ml-2 ${validation?.summary?.total_corrected > 0 ? 'text-amber-500' : 'text-green-500'}`}>
            <svg className="w-4 h-4 inline" fill="currentColor" viewBox="0 0 20 20">
              {validation?.summary?.total_corrected > 0 ? (
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              ) : (
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              )}
            </svg>
          </span>
        )}
      </h3>

      {/* Location Name */}
      <FieldRow field={fields.pickup_name} fieldKey="pickup_name" updateField={updateField} vInfo={pFields.pickup_name} />

      {/* Address */}
      <FieldRow field={fields.pickup_address} fieldKey="pickup_address" updateField={updateField} vInfo={pFields.pickup_address} />

      {/* City / State / ZIP */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <FieldInput field={fields.pickup_city} fieldKey="pickup_city" label="City" updateField={updateField} required vInfo={pFields.pickup_city} />
        <FieldInput field={fields.pickup_state} fieldKey="pickup_state" label="State" updateField={updateField} required maxLength={2} placeholder="XX" vInfo={pFields.pickup_state} />
        <FieldInput field={fields.pickup_zip} fieldKey="pickup_zip" label="ZIP" updateField={updateField} required maxLength={10} placeholder="12345" vInfo={pFields.pickup_zip} />
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

/** Simple field input with label and optional validation badge */
function FieldInput({ field, fieldKey, label, updateField, required, maxLength, placeholder, vInfo }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label || field?.label || fieldKey}
        {required && <span className="text-red-500 ml-0.5">*</span>}
        <InlineBadge info={vInfo} />
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
      <MismatchHint info={vInfo} fieldKey={fieldKey} updateField={updateField} />
    </div>
  )
}

/** Full-width field row with label and validation badge */
function FieldRow({ field, fieldKey, updateField, vInfo }) {
  if (!field) return null
  return (
    <div className="mb-3">
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {field.label}
        {field.required && <span className="text-red-500 ml-0.5">*</span>}
        <InlineBadge info={vInfo} />
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
      <MismatchHint info={vInfo} fieldKey={fieldKey} updateField={updateField} />
    </div>
  )
}

/** Inline badge next to label text */
function InlineBadge({ info }) {
  if (!info) return null
  const { status } = info
  if (status === 'verified') {
    return <span className="ml-1.5 text-green-600 text-xs font-normal">Verified</span>
  }
  if (status === 'corrected_by_directory') {
    return <span className="ml-1.5 text-amber-600 text-xs font-normal" title={info.original ? `Haiku extracted: ${info.original}` : undefined}>Directory Corrected</span>
  }
  if (status === 'mismatch') {
    return <span className="ml-1.5 text-red-600 text-xs font-normal">Mismatch</span>
  }
  if (status === 'unverified') {
    return <span className="ml-1.5 text-yellow-600 text-xs font-normal">Unverified</span>
  }
  return null
}

/** Clickable mismatch hint: "Use {directory value}" or directory correction info */
function MismatchHint({ info, fieldKey, updateField }) {
  if (!info) return null

  if (info.status === 'corrected_by_directory' && info.original) {
    return (
      <div className="text-xs text-amber-700 mt-0.5 bg-amber-50 rounded px-1.5 py-0.5">
        Haiku extracted: <span className="font-medium">{info.original}</span>
        {' \u2192 '}Directory replaced: <span className="font-medium">{info.directory}</span>
      </div>
    )
  }

  if (info.status !== 'mismatch') return null
  const correctValue = info.directory || info.zip_expected
  if (!correctValue) return null
  return (
    <button
      onClick={() => updateField(fieldKey, correctValue)}
      className="text-xs text-blue-600 hover:text-blue-800 mt-0.5 block"
    >
      Use "{correctValue}"
    </button>
  )
}

export default PickupSection
