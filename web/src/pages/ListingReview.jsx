import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../api'

/**
 * Listing Review & Posting Page - Simplified
 *
 * Features:
 * 1. Shows extracted fields from document
 * 2. Simple warehouse dropdown for delivery
 * 3. Editable price input
 * 4. Post to Central Dispatch
 */
function ListingReview() {
  const { id } = useParams() // extraction run ID
  const navigate = useNavigate()

  // Loading and error states
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  // Data
  const [extraction, setExtraction] = useState(null)
  const [document, setDocument] = useState(null)
  const [fields, setFields] = useState({})
  const [warehouses, setWarehouses] = useState([])
  const [selectedWarehouseId, setSelectedWarehouseId] = useState('')

  // Export state
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState(null)

  // Load data
  useEffect(() => {
    async function loadData() {
      setLoading(true)
      setError(null)

      try {
        // Load extraction details
        const extResult = await api.getExtraction(id)
        setExtraction(extResult)

        // Parse outputs
        let outputs = {}
        const runData = extResult.run || extResult
        if (runData.outputs) {
          outputs = typeof runData.outputs === 'string'
            ? JSON.parse(runData.outputs)
            : runData.outputs
        }
        setFields(outputs)

        // Load document
        const documentId = runData.document_id || extResult.document_id
        if (documentId) {
          try {
            const docResult = await api.getDocument(documentId)
            setDocument(docResult)
          } catch (err) {
            console.error('Failed to load document:', err)
          }
        }

        // Load warehouses
        const whResult = await api.listWarehouses()
        setWarehouses(whResult.items || [])

        // Set selected warehouse if already set
        if (outputs.warehouse_id) {
          setSelectedWarehouseId(outputs.warehouse_id.toString())
        }
      } catch (err) {
        setError(err.message || 'Failed to load document')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [id])

  // Handle field change
  function handleFieldChange(key, value) {
    setFields(prev => ({ ...prev, [key]: value }))
  }

  // Handle warehouse selection
  function handleWarehouseSelect(warehouseId) {
    setSelectedWarehouseId(warehouseId)
    const wh = warehouses.find(w => w.id === parseInt(warehouseId))
    if (wh) {
      setFields(prev => ({
        ...prev,
        warehouse_id: wh.id,
        delivery_name: wh.name || '',
        delivery_address: wh.address || '',
        delivery_city: wh.city || '',
        delivery_state: wh.state || '',
        delivery_zip: wh.zip_code || '',
      }))
    }
  }

  // Save draft
  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await api.updateExtraction(id, {
        outputs_json: fields,
        status: 'reviewed',
      })
      const extResult = await api.getExtraction(id)
      setExtraction(extResult)
    } catch (err) {
      setError(`Save failed: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Export to Central Dispatch
  async function handleExport() {
    if (!selectedWarehouseId) {
      setError('Please select a delivery warehouse')
      return
    }

    setExporting(true)
    setExportResult(null)
    try {
      await api.updateExtraction(id, {
        outputs_json: fields,
        status: 'approved',
      })
      const result = await api.exportToCentralDispatch(id)
      setExportResult({
        success: true,
        message: 'Successfully posted to Central Dispatch',
        orderId: result.cd_listing_id || result.order_id,
      })
      const extResult = await api.getExtraction(id)
      setExtraction(extResult)
    } catch (err) {
      setExportResult({
        success: false,
        message: err.message || 'Export failed',
      })
    } finally {
      setExporting(false)
    }
  }

  // Loading state
  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse">
          <div className="h-8 bg-gray-200 rounded w-1/4 mb-4"></div>
          <div className="h-64 bg-gray-200 rounded"></div>
        </div>
      </div>
    )
  }

  // Error state
  if (error && !extraction) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h3 className="text-red-800 font-medium text-lg mb-2">Error</h3>
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={() => navigate('/documents')}
            className="btn btn-secondary"
          >
            Back to Documents
          </button>
        </div>
      </div>
    )
  }

  const isExported = extraction?.status === 'exported'
  const selectedWarehouse = warehouses.find(w => w.id === parseInt(selectedWarehouseId))

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-2">
            <Link to="/documents" className="hover:text-blue-600">&larr; Documents</Link>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Review & Post</h1>
          <div className="flex items-center gap-3 mt-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${
              extraction?.auction_type_code === 'COPART' ? 'bg-blue-100 text-blue-800' :
              extraction?.auction_type_code === 'IAA' ? 'bg-purple-100 text-purple-800' :
              extraction?.auction_type_code === 'MANHEIM' ? 'bg-green-100 text-green-800' :
              'bg-gray-100 text-gray-800'
            }`}>
              {extraction?.auction_type_code || 'Unknown'}
            </span>
            {fields.vehicle_vin && (
              <span className="text-sm text-gray-600">
                VIN: <span className="font-mono">{fields.vehicle_vin}</span>
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving || isExported}
            className="btn btn-secondary disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Draft'}
          </button>
          <button
            onClick={handleExport}
            disabled={!selectedWarehouseId || exporting || isExported}
            className={`btn ${selectedWarehouseId && !isExported ? 'btn-primary' : 'btn-disabled'}`}
          >
            {exporting ? 'Posting...' : isExported ? 'Already Posted' : 'Post to CD'}
          </button>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
          <button onClick={() => setError(null)} className="ml-4 text-sm underline">Dismiss</button>
        </div>
      )}

      {exportResult && (
        <div className={`mb-6 p-4 rounded-lg ${
          exportResult.success ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800'
        }`}>
          {exportResult.message}
          {exportResult.orderId && <span className="ml-2 font-medium">(ID: {exportResult.orderId})</span>}
        </div>
      )}

      {/* Document Preview */}
      {document && (
        <div className="mb-6 bg-gray-50 border rounded-lg p-4 flex items-center justify-between">
          <div>
            <h3 className="font-medium">Source Document</h3>
            <p className="text-sm text-gray-600">{document.filename}</p>
          </div>
          <button
            onClick={() => window.open(api.getDocumentFileUrl(document.id), '_blank')}
            className="btn btn-secondary"
          >
            View PDF
          </button>
        </div>
      )}

      {/* Warehouse Selection */}
      <div className="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h3 className="font-medium text-blue-800 mb-2">Delivery Warehouse *</h3>
        <select
          value={selectedWarehouseId}
          onChange={(e) => handleWarehouseSelect(e.target.value)}
          disabled={isExported}
          className="form-select w-full max-w-md"
        >
          <option value="">Select Warehouse...</option>
          {warehouses.map((wh) => (
            <option key={wh.id} value={wh.id}>
              {wh.state} - {wh.name} {wh.city ? `(${wh.city})` : ''}
            </option>
          ))}
        </select>
        {selectedWarehouse && (
          <p className="mt-2 text-sm text-blue-700">
            {selectedWarehouse.address}, {selectedWarehouse.city}, {selectedWarehouse.state} {selectedWarehouse.zip_code}
          </p>
        )}
      </div>

      {/* Main Form */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Vehicle Info */}
        <div className="bg-white border rounded-lg">
          <div className="px-4 py-3 bg-gray-50 border-b font-medium">Vehicle Information</div>
          <div className="p-4 space-y-4">
            <div>
              <label className="form-label">VIN</label>
              <input
                type="text"
                value={fields.vehicle_vin || ''}
                onChange={(e) => handleFieldChange('vehicle_vin', e.target.value.toUpperCase())}
                disabled={isExported}
                className="form-input w-full font-mono"
                maxLength={17}
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="form-label">Year</label>
                <input
                  type="text"
                  value={fields.vehicle_year || ''}
                  onChange={(e) => handleFieldChange('vehicle_year', e.target.value)}
                  disabled={isExported}
                  className="form-input w-full"
                />
              </div>
              <div>
                <label className="form-label">Make</label>
                <input
                  type="text"
                  value={fields.vehicle_make || ''}
                  onChange={(e) => handleFieldChange('vehicle_make', e.target.value)}
                  disabled={isExported}
                  className="form-input w-full"
                />
              </div>
              <div>
                <label className="form-label">Model</label>
                <input
                  type="text"
                  value={fields.vehicle_model || ''}
                  onChange={(e) => handleFieldChange('vehicle_model', e.target.value)}
                  disabled={isExported}
                  className="form-input w-full"
                />
              </div>
            </div>
            <div>
              <label className="form-label">Lot/Stock #</label>
              <input
                type="text"
                value={fields.vehicle_lot || ''}
                onChange={(e) => handleFieldChange('vehicle_lot', e.target.value)}
                disabled={isExported}
                className="form-input w-full"
              />
            </div>
          </div>
        </div>

        {/* Pickup Info */}
        <div className="bg-white border rounded-lg">
          <div className="px-4 py-3 bg-gray-50 border-b font-medium">Pickup Location (Auction)</div>
          <div className="p-4 space-y-4">
            <div>
              <label className="form-label">Location Name</label>
              <input
                type="text"
                value={fields.pickup_name || ''}
                onChange={(e) => handleFieldChange('pickup_name', e.target.value)}
                disabled={isExported}
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Address</label>
              <input
                type="text"
                value={fields.pickup_address || ''}
                onChange={(e) => handleFieldChange('pickup_address', e.target.value)}
                disabled={isExported}
                className="form-input w-full"
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="form-label">City</label>
                <input
                  type="text"
                  value={fields.pickup_city || ''}
                  onChange={(e) => handleFieldChange('pickup_city', e.target.value)}
                  disabled={isExported}
                  className="form-input w-full"
                />
              </div>
              <div>
                <label className="form-label">State</label>
                <input
                  type="text"
                  value={fields.pickup_state || ''}
                  onChange={(e) => handleFieldChange('pickup_state', e.target.value.toUpperCase())}
                  disabled={isExported}
                  className="form-input w-full"
                  maxLength={2}
                />
              </div>
              <div>
                <label className="form-label">ZIP</label>
                <input
                  type="text"
                  value={fields.pickup_zip || ''}
                  onChange={(e) => handleFieldChange('pickup_zip', e.target.value)}
                  disabled={isExported}
                  className="form-input w-full"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Buyer Info */}
        <div className="bg-white border rounded-lg">
          <div className="px-4 py-3 bg-gray-50 border-b font-medium">Buyer Information</div>
          <div className="p-4 space-y-4">
            <div>
              <label className="form-label">Buyer ID / Member #</label>
              <input
                type="text"
                value={fields.buyer_id || ''}
                onChange={(e) => handleFieldChange('buyer_id', e.target.value)}
                disabled={isExported}
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Buyer Name</label>
              <input
                type="text"
                value={fields.buyer_name || ''}
                onChange={(e) => handleFieldChange('buyer_name', e.target.value)}
                disabled={isExported}
                className="form-input w-full"
              />
            </div>
            {extraction?.auction_type_code === 'MANHEIM' && (
              <div>
                <label className="form-label">Release Date</label>
                <input
                  type="date"
                  value={fields.release_date || ''}
                  onChange={(e) => handleFieldChange('release_date', e.target.value)}
                  disabled={isExported}
                  className="form-input w-full"
                />
              </div>
            )}
          </div>
        </div>

        {/* Pricing */}
        <div className="bg-white border rounded-lg">
          <div className="px-4 py-3 bg-gray-50 border-b font-medium">Transport Pricing</div>
          <div className="p-4 space-y-4">
            <div>
              <label className="form-label">Transport Price ($)</label>
              <input
                type="number"
                value={fields.price_total || ''}
                onChange={(e) => handleFieldChange('price_total', e.target.value)}
                disabled={isExported}
                className="form-input w-full text-lg"
                placeholder="Enter price..."
                min="0"
                step="1"
              />
              <p className="text-xs text-gray-500 mt-1">Price you want to pay the carrier</p>
            </div>
            <div>
              <label className="form-label">Vehicle Type</label>
              <select
                value={fields.vehicle_type || 'SEDAN'}
                onChange={(e) => handleFieldChange('vehicle_type', e.target.value)}
                disabled={isExported}
                className="form-select w-full"
              >
                <option value="SEDAN">Sedan</option>
                <option value="SUV">SUV</option>
                <option value="TRUCK">Truck</option>
                <option value="VAN">Van</option>
                <option value="MOTORCYCLE">Motorcycle</option>
                <option value="OTHER">Other</option>
              </select>
            </div>
            <div>
              <label className="form-label">Condition</label>
              <select
                value={fields.vehicle_condition || 'OPERABLE'}
                onChange={(e) => handleFieldChange('vehicle_condition', e.target.value)}
                disabled={isExported}
                className="form-select w-full"
              >
                <option value="OPERABLE">Operable (Can Roll)</option>
                <option value="INOPERABLE">Inoperable</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* Notes */}
      <div className="mt-6 bg-white border rounded-lg">
        <div className="px-4 py-3 bg-gray-50 border-b font-medium">Notes</div>
        <div className="p-4">
          <textarea
            value={fields.notes || ''}
            onChange={(e) => handleFieldChange('notes', e.target.value)}
            disabled={isExported}
            className="form-input w-full"
            rows={3}
            placeholder="Additional notes for the carrier..."
          />
        </div>
      </div>

      {/* Extraction Info */}
      <div className="mt-6 text-sm text-gray-500 flex items-center gap-4">
        <span>Run ID: {extraction?.id}</span>
        <span>Status: {extraction?.status}</span>
        {extraction?.created_at && (
          <span>Created: {new Date(extraction.created_at).toLocaleString()}</span>
        )}
      </div>
    </div>
  )
}

export default ListingReview
