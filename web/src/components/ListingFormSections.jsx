import { useState, useEffect, useMemo } from 'react'
import api from '../api'

/**
 * Sectioned listing form for CD API v2 payload.
 *
 * Sections: General · Stops · Vehicles · Price · SLA · Marketplaces · Tags · Notes
 *
 * Props:
 *   documentId   - numeric document ID
 *   warehouseCode - optional warehouse code (for delivery stop)
 *   onPushSuccess - callback after successful push
 */
export default function ListingFormSections({ documentId, warehouseCode, onPushSuccess }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [payload, setPayload] = useState(null)
  const [validationErrors, setValidationErrors] = useState([])
  const [activeSection, setActiveSection] = useState('general')
  const [pushing, setPushing] = useState(false)
  const [pushResult, setPushResult] = useState(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.getCDPayload(documentId, warehouseCode)
        setPayload(res.payload || {})
        setValidationErrors(res.validation_errors || [])
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [documentId, warehouseCode])

  const sections = [
    { id: 'general', label: 'General' },
    { id: 'stops', label: 'Stops' },
    { id: 'vehicles', label: 'Vehicles' },
    { id: 'price', label: 'Price' },
    { id: 'sla', label: 'SLA' },
    { id: 'marketplaces', label: 'Marketplaces' },
    { id: 'tags', label: 'Tags' },
    { id: 'notes', label: 'Notes' },
  ]

  // Group validation errors by section
  const errorsBySection = useMemo(() => {
    const groups = {}
    for (const err of validationErrors) {
      const lower = err.toLowerCase()
      if (lower.includes('stop') || lower.includes('address') || lower.includes('city') || lower.includes('state') || lower.includes('postal')) {
        groups.stops = (groups.stops || []).concat(err)
      } else if (lower.includes('vehicle') || lower.includes('vin') || lower.includes('make') || lower.includes('model') || lower.includes('year')) {
        groups.vehicles = (groups.vehicles || []).concat(err)
      } else if (lower.includes('price') || lower.includes('cod') || lower.includes('payment') || lower.includes('total')) {
        groups.price = (groups.price || []).concat(err)
      } else if (lower.includes('sla') || lower.includes('deliver') || lower.includes('pickup')) {
        groups.sla = (groups.sla || []).concat(err)
      } else if (lower.includes('marketplace')) {
        groups.marketplaces = (groups.marketplaces || []).concat(err)
      } else {
        groups.general = (groups.general || []).concat(err)
      }
    }
    return groups
  }, [validationErrors])

  function updateField(path, value) {
    setPayload(prev => {
      const next = JSON.parse(JSON.stringify(prev))
      const keys = path.split('.')
      let obj = next
      for (let i = 0; i < keys.length - 1; i++) {
        const k = isNaN(keys[i]) ? keys[i] : Number(keys[i])
        obj = obj[k]
      }
      const lastKey = isNaN(keys.at(-1)) ? keys.at(-1) : Number(keys.at(-1))
      obj[lastKey] = value
      return next
    })
  }

  async function handleDryRun() {
    setPushing(true)
    setPushResult(null)
    try {
      const res = await api.pushCDListing(documentId, { warehouseCode, sandbox: true, dryRun: true })
      setPushResult(res)
      if (res.validation_errors?.length) {
        setValidationErrors(res.validation_errors)
      } else {
        setValidationErrors([])
      }
    } catch (err) {
      setPushResult({ success: false, message: err.message })
    } finally {
      setPushing(false)
    }
  }

  async function handlePush() {
    setPushing(true)
    setPushResult(null)
    try {
      const res = await api.pushCDListing(documentId, { warehouseCode, sandbox: true, dryRun: false })
      setPushResult(res)
      if (res.success && onPushSuccess) onPushSuccess(res)
    } catch (err) {
      setPushResult({ success: false, message: err.message })
    } finally {
      setPushing(false)
    }
  }

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-10 bg-gray-200 rounded w-full" />
          <div className="h-64 bg-gray-200 rounded" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800 font-medium">Failed to load payload</p>
          <p className="text-red-600 text-sm mt-1">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      {/* Section tabs */}
      <div className="border-b border-gray-200 px-4 flex gap-1 overflow-x-auto">
        {sections.map(s => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            className={`px-3 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeSection === s.id
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {s.label}
            {errorsBySection[s.id] && (
              <span className="ml-1.5 inline-flex items-center justify-center w-5 h-5 text-xs bg-red-100 text-red-700 rounded-full">
                {errorsBySection[s.id].length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Section-level errors */}
      {errorsBySection[activeSection] && (
        <div className="mx-4 mt-4 bg-yellow-50 border border-yellow-200 rounded p-3">
          <ul className="list-disc list-inside text-sm text-yellow-700">
            {errorsBySection[activeSection].map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}

      {/* Section content */}
      <div className="p-4">
        {activeSection === 'general' && (
          <GeneralSection payload={payload} onChange={updateField} />
        )}
        {activeSection === 'stops' && (
          <StopsSection stops={payload.stops || []} onChange={updateField} />
        )}
        {activeSection === 'vehicles' && (
          <VehiclesSection vehicles={payload.vehicles || []} onChange={updateField} />
        )}
        {activeSection === 'price' && (
          <PriceSection price={payload.price || {}} onChange={updateField} />
        )}
        {activeSection === 'sla' && (
          <SLASection sla={payload.sla || {}} onChange={updateField} />
        )}
        {activeSection === 'marketplaces' && (
          <MarketplacesSection marketplaces={payload.marketplaces || []} onChange={updateField} />
        )}
        {activeSection === 'tags' && (
          <TagsSection tags={payload.tags || []} onChange={updateField} />
        )}
        {activeSection === 'notes' && (
          <NotesSection payload={payload} onChange={updateField} />
        )}
      </div>

      {/* Push result */}
      {pushResult && (
        <div className={`mx-4 mb-4 p-3 rounded border ${pushResult.success ? 'bg-green-50 border-green-200 text-green-700' : 'bg-red-50 border-red-200 text-red-700'}`}>
          <p className="font-medium">{pushResult.success ? 'Success' : 'Failed'}</p>
          <p className="text-sm">{pushResult.message}</p>
          {pushResult.listing_id && (
            <p className="text-sm mt-1">Listing ID: <code className="bg-gray-100 px-1 rounded">{pushResult.listing_id}</code></p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between px-4 py-3 border-t bg-gray-50 gap-3">
        <div className="text-sm text-gray-500">
          {validationErrors.length === 0
            ? 'Payload is valid'
            : `${validationErrors.length} validation error(s)`}
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleDryRun}
            disabled={pushing}
            className="px-4 py-2 text-sm bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:opacity-50"
          >
            {pushing ? 'Validating...' : 'Dry Run'}
          </button>
          <button
            onClick={handlePush}
            disabled={pushing || validationErrors.length > 0}
            className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
          >
            {pushing ? 'Pushing...' : 'Push to Central Dispatch'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ===== Sub-section components ===== */

function InputField({ label, value, onChange, type = 'text', required, placeholder, maxLength, className = '' }) {
  return (
    <div className={className}>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type={type}
        value={value ?? ''}
        onChange={e => onChange(type === 'number' ? Number(e.target.value) : e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        className="form-input w-full text-sm"
      />
    </div>
  )
}

function SelectField({ label, value, onChange, options, required, className = '' }) {
  return (
    <div className={className}>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <select
        value={value ?? ''}
        onChange={e => onChange(e.target.value)}
        className="form-select w-full text-sm"
      >
        <option value="">-- Select --</option>
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

function CheckboxField({ label, checked, onChange, className = '' }) {
  return (
    <label className={`flex items-center gap-2 text-sm text-gray-700 ${className}`}>
      <input
        type="checkbox"
        checked={checked ?? false}
        onChange={e => onChange(e.target.checked)}
        className="form-checkbox"
      />
      {label}
    </label>
  )
}

const TRAILER_TYPES = [
  { value: 'OPEN', label: 'Open' },
  { value: 'ENCLOSED', label: 'Enclosed' },
  { value: 'DRIVEAWAY', label: 'Driveaway' },
]

const VEHICLE_TYPES = [
  { value: 'AUTO', label: 'Auto' },
  { value: 'SUV', label: 'SUV' },
  { value: 'PICKUP', label: 'Pickup' },
  { value: 'VAN', label: 'Van' },
  { value: 'MOTORCYCLE', label: 'Motorcycle' },
  { value: 'BOAT', label: 'Boat' },
  { value: 'RV', label: 'RV' },
  { value: 'HEAVY_EQUIPMENT', label: 'Heavy Equipment' },
  { value: 'OTHER', label: 'Other' },
]

const LOCATION_TYPES = [
  { value: 'BUSINESS', label: 'Business' },
  { value: 'AUCTION', label: 'Auction' },
  { value: 'RESIDENCE', label: 'Residence' },
  { value: 'PORT', label: 'Port' },
  { value: 'OTHER', label: 'Other' },
]

const PAYMENT_METHODS = [
  { value: 'CASH_CERTIFIED_FUNDS', label: 'Cash / Certified Funds' },
  { value: 'CHECK', label: 'Check' },
  { value: 'ACH', label: 'ACH' },
  { value: 'COMCHECK', label: 'Comcheck' },
  { value: 'CREDIT_CARD', label: 'Credit Card' },
]

const PAYMENT_LOCATIONS = [
  { value: 'DELIVERY', label: 'Delivery' },
  { value: 'PICKUP', label: 'Pickup' },
  { value: 'COD', label: 'COD' },
]

const SLA_TYPES = [
  { value: 'STANDARD', label: 'Standard' },
  { value: 'EXPEDITED', label: 'Expedited' },
  { value: 'GUARANTEED', label: 'Guaranteed' },
]

/* ----- General ----- */
function GeneralSection({ payload, onChange }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <InputField
          label="External ID"
          value={payload.externalId}
          onChange={v => onChange('externalId', v)}
          required
          maxLength={50}
        />
        <InputField
          label="Partner Reference ID"
          value={payload.partnerReferenceId}
          onChange={v => onChange('partnerReferenceId', v)}
          maxLength={50}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <InputField
          label="Shipper Order ID"
          value={payload.shipperOrderId}
          onChange={v => onChange('shipperOrderId', v)}
        />
        <SelectField
          label="Trailer Type"
          value={payload.trailerType}
          onChange={v => onChange('trailerType', v)}
          options={TRAILER_TYPES}
          required
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <InputField
          label="Available Date"
          type="date"
          value={payload.availableDate}
          onChange={v => onChange('availableDate', v)}
          required
        />
        <InputField
          label="Expiration Date"
          type="date"
          value={payload.expirationDate}
          onChange={v => onChange('expirationDate', v)}
        />
      </div>
      <CheckboxField
        label="Has inoperable vehicle"
        checked={payload.hasInOpVehicle}
        onChange={v => onChange('hasInOpVehicle', v)}
      />
    </div>
  )
}

/* ----- Stops ----- */
function StopsSection({ stops, onChange }) {
  const labels = ['Pickup (Stop 1)', 'Delivery (Stop 2)']
  return (
    <div className="space-y-6">
      {stops.map((stop, idx) => (
        <div key={idx} className="border rounded-lg p-4">
          <h3 className="font-medium text-gray-900 mb-3">{labels[idx] || `Stop ${idx + 1}`}</h3>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <SelectField
                label="Location Type"
                value={stop.locationType}
                onChange={v => onChange(`stops.${idx}.locationType`, v)}
                options={LOCATION_TYPES}
              />
              <InputField
                label="Location Name"
                value={stop.locationName}
                onChange={v => onChange(`stops.${idx}.locationName`, v)}
                placeholder="e.g. Copart Dallas"
              />
            </div>
            <InputField
              label="Address"
              value={stop.address}
              onChange={v => onChange(`stops.${idx}.address`, v)}
              required
            />
            <div className="grid grid-cols-3 gap-4">
              <InputField
                label="City"
                value={stop.city}
                onChange={v => onChange(`stops.${idx}.city`, v)}
                required
              />
              <InputField
                label="State"
                value={stop.state}
                onChange={v => onChange(`stops.${idx}.state`, v)}
                required
                maxLength={2}
                placeholder="TX"
              />
              <InputField
                label="Postal Code"
                value={stop.postalCode}
                onChange={v => onChange(`stops.${idx}.postalCode`, v)}
                required
                placeholder="75001"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <InputField
                label="Contact Name"
                value={stop.contactName}
                onChange={v => onChange(`stops.${idx}.contactName`, v)}
              />
              <InputField
                label="Phone"
                value={stop.phone}
                onChange={v => onChange(`stops.${idx}.phone`, v)}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ----- Vehicles ----- */
function VehiclesSection({ vehicles, onChange }) {
  return (
    <div className="space-y-4">
      {vehicles.map((v, idx) => (
        <div key={idx} className="border rounded-lg p-4">
          <h3 className="font-medium text-gray-900 mb-3">Vehicle {idx + 1}</h3>
          <div className="space-y-3">
            <div className="grid grid-cols-4 gap-4">
              <InputField
                label="VIN"
                value={v.vin}
                onChange={val => onChange(`vehicles.${idx}.vin`, val)}
                required
                maxLength={17}
                className="col-span-2"
              />
              <InputField
                label="Year"
                type="number"
                value={v.year}
                onChange={val => onChange(`vehicles.${idx}.year`, val)}
                required
              />
              <SelectField
                label="Vehicle Type"
                value={v.vehicleType}
                onChange={val => onChange(`vehicles.${idx}.vehicleType`, val)}
                options={VEHICLE_TYPES}
              />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <InputField
                label="Make"
                value={v.make}
                onChange={val => onChange(`vehicles.${idx}.make`, val)}
                required
              />
              <InputField
                label="Model"
                value={v.model}
                onChange={val => onChange(`vehicles.${idx}.model`, val)}
                required
              />
              <InputField
                label="Color"
                value={v.color}
                onChange={val => onChange(`vehicles.${idx}.color`, val)}
              />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <InputField
                label="Lot Number"
                value={v.lotNumber}
                onChange={val => onChange(`vehicles.${idx}.lotNumber`, val)}
              />
              <CheckboxField
                label="Inoperable"
                checked={v.isInoperable}
                onChange={val => onChange(`vehicles.${idx}.isInoperable`, val)}
                className="pt-6"
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ----- Price ----- */
function PriceSection({ price, onChange }) {
  const cod = price.cod || {}
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <InputField
          label="Total Price"
          type="number"
          value={price.total}
          onChange={v => onChange('price.total', v)}
          required
        />
        <InputField
          label="Balance"
          type="number"
          value={price.balance}
          onChange={v => onChange('price.balance', v)}
        />
      </div>

      <div className="border rounded-lg p-4 mt-2">
        <h3 className="font-medium text-gray-900 mb-3">COD (Cash on Delivery)</h3>
        <div className="grid grid-cols-3 gap-4">
          <InputField
            label="Amount"
            type="number"
            value={cod.amount}
            onChange={v => onChange('price.cod.amount', v)}
            required
          />
          <SelectField
            label="Payment Method"
            value={cod.paymentMethod}
            onChange={v => onChange('price.cod.paymentMethod', v)}
            options={PAYMENT_METHODS}
          />
          <SelectField
            label="Payment Location"
            value={cod.paymentLocation}
            onChange={v => onChange('price.cod.paymentLocation', v)}
            options={PAYMENT_LOCATIONS}
          />
        </div>
      </div>
    </div>
  )
}

/* ----- SLA ----- */
function SLASection({ sla, onChange }) {
  return (
    <div className="space-y-4">
      <SelectField
        label="SLA Type"
        value={sla.type}
        onChange={v => onChange('sla.type', v)}
        options={SLA_TYPES}
      />
      <div className="grid grid-cols-2 gap-4">
        <InputField
          label="Pickup By Date"
          type="date"
          value={sla.pickupByDate}
          onChange={v => onChange('sla.pickupByDate', v)}
        />
        <InputField
          label="Deliver By Date"
          type="date"
          value={sla.deliverByDate}
          onChange={v => onChange('sla.deliverByDate', v)}
        />
      </div>
    </div>
  )
}

/* ----- Marketplaces ----- */
function MarketplacesSection({ marketplaces, onChange }) {
  return (
    <div className="space-y-4">
      {marketplaces.map((mp, idx) => (
        <div key={idx} className="border rounded-lg p-4">
          <h3 className="font-medium text-gray-900 mb-3">Marketplace {idx + 1}</h3>
          <div className="grid grid-cols-2 gap-4">
            <InputField
              label="Marketplace ID"
              type="number"
              value={mp.marketplaceId}
              onChange={v => onChange(`marketplaces.${idx}.marketplaceId`, v)}
            />
          </div>
          <div className="flex gap-6 mt-3">
            <CheckboxField
              label="Searchable"
              checked={mp.searchable}
              onChange={v => onChange(`marketplaces.${idx}.searchable`, v)}
            />
            <CheckboxField
              label="Digital Offers"
              checked={mp.digitalOffersEnabled}
              onChange={v => onChange(`marketplaces.${idx}.digitalOffersEnabled`, v)}
            />
            <CheckboxField
              label="Make Offers"
              checked={mp.makeOffersEnabled}
              onChange={v => onChange(`marketplaces.${idx}.makeOffersEnabled`, v)}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

/* ----- Tags ----- */
function TagsSection({ tags, onChange }) {
  return (
    <div className="space-y-4">
      {tags.length === 0 && (
        <p className="text-sm text-gray-500 italic">No tags configured.</p>
      )}
      {tags.map((tag, idx) => (
        <div key={idx} className="grid grid-cols-2 gap-4">
          <InputField
            label="Name"
            value={tag.name}
            onChange={v => onChange(`tags.${idx}.name`, v)}
          />
          <InputField
            label="Value"
            value={tag.value}
            onChange={v => onChange(`tags.${idx}.value`, v)}
          />
        </div>
      ))}
    </div>
  )
}

/* ----- Notes ----- */
function NotesSection({ payload, onChange }) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Transportation Release Notes
        </label>
        <textarea
          value={payload.transportationReleaseNotes ?? ''}
          onChange={e => onChange('transportationReleaseNotes', e.target.value)}
          rows={4}
          className="form-input w-full text-sm"
          placeholder="Special instructions for the carrier..."
        />
      </div>
    </div>
  )
}
