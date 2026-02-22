import { useState, useEffect } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

// US States for dropdown
const US_STATES = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
]

export default function WarehousesTab() {
  const { showMessage, setSaving } = useSettings()
  const [warehouses, setWarehouses] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState({
    code: '',
    name: '',
    state: '',
    city: '',
    address: '',
    zip_code: '',
    phone: '',
    contact_name: '',
    contact_phone: '',
    location_type: 'BUSINESS',
    transport_special_instructions: '',
    is_default: false,
  })

  // Google Maps API key state
  const [gmapsKey, setGmapsKey] = useState('')
  const [gmapsStatus, setGmapsStatus] = useState(null) // null | 'saved' | 'valid' | 'invalid'
  const [gmapsTesting, setGmapsTesting] = useState(false)
  const [gmapsSaving, setGmapsSaving] = useState(false)

  useEffect(() => {
    loadWarehouses()
    loadGmapsStatus()
  }, [])

  async function loadWarehouses() {
    setLoading(true)
    try {
      const data = await api.listWarehouses()
      setWarehouses(data.items || [])
    } catch (err) {
      console.error('Failed to load warehouses:', err)
    } finally {
      setLoading(false)
    }
  }

  async function loadGmapsStatus() {
    try {
      const cred = await api.getCredential('google_maps')
      if (cred) {
        setGmapsKey(cred.config?.api_key || '')
        setGmapsStatus(cred.last_test_status === 'ok' ? 'valid' : 'saved')
      }
    } catch {
      // No credential stored — that's fine
      setGmapsStatus(null)
    }
  }

  async function handleGmapsSave() {
    if (!gmapsKey || gmapsKey.includes('\u25CF')) {
      showMessage('error', 'Please enter a valid API key')
      return
    }
    setGmapsSaving(true)
    try {
      await api.saveCredential('google_maps', { api_key: gmapsKey }, true)
      setGmapsStatus('saved')
      showMessage('success', 'Google Maps API key saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setGmapsSaving(false)
    }
  }

  async function handleGmapsTest() {
    setGmapsTesting(true)
    try {
      const result = await api.testCredential('google_maps')
      if (result.status === 'ok') {
        setGmapsStatus('valid')
        showMessage('success', `Google Maps API key is valid (${result.duration_ms}ms)`)
      } else {
        setGmapsStatus('invalid')
        showMessage('error', `Test failed: ${result.message}`)
      }
    } catch (err) {
      setGmapsStatus('invalid')
      showMessage('error', err.message)
    } finally {
      setGmapsTesting(false)
    }
  }

  function resetForm() {
    setForm({
      code: '',
      name: '',
      state: '',
      city: '',
      address: '',
      zip_code: '',
      phone: '',
      contact_name: '',
      contact_phone: '',
      location_type: 'BUSINESS',
      transport_special_instructions: '',
      is_default: false,
    })
    setEditingId(null)
    setShowForm(false)
  }

  function editWarehouse(wh) {
    setForm({
      code: wh.code,
      name: wh.name,
      state: wh.state || '',
      city: wh.city || '',
      address: wh.address || '',
      zip_code: wh.zip_code || '',
      phone: wh.phone || '',
      contact_name: wh.contact_name || '',
      contact_phone: wh.contact_phone || '',
      location_type: wh.location_type || 'BUSINESS',
      transport_special_instructions: wh.transport_special_instructions || '',
      is_default: wh.is_default || false,
    })
    setEditingId(wh.id)
    setShowForm(true)
  }

  async function handleSave() {
    // Validation
    if (!form.code || !form.name || !form.state) {
      showMessage('error', 'Code, Name and State are required')
      return
    }

    setSaving(true)
    try {
      if (editingId) {
        await api.updateWarehouse(editingId, form)
        showMessage('success', 'Warehouse updated')
      } else {
        await api.createWarehouse(form)
        showMessage('success', 'Warehouse created')
      }
      resetForm()
      loadWarehouses()
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this warehouse?')) return
    try {
      await api.deleteWarehouseFull(id, true)
      showMessage('success', 'Warehouse deleted')
      loadWarehouses()
    } catch (err) {
      showMessage('error', err.message)
    }
  }

  const gmapsStatusBadge = gmapsStatus === 'valid'
    ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">Valid</span>
    : gmapsStatus === 'invalid'
    ? <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded">Invalid</span>
    : gmapsStatus === 'saved'
    ? <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded">Saved (untested)</span>
    : <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">Not configured</span>

  return (
    <div className="space-y-6">
      {/* Google Maps API Key */}
      <div className="border rounded-lg p-4 bg-white">
        <h4 className="font-medium mb-3 flex items-center gap-2">
          Distance Services
          {gmapsStatusBadge}
        </h4>

        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">Google Maps API Key</label>
            <div className="flex gap-2">
              <input
                type="password"
                value={gmapsKey}
                onChange={e => { setGmapsKey(e.target.value); setGmapsStatus(gmapsStatus === 'valid' ? 'saved' : gmapsStatus) }}
                placeholder="AIza..."
                className="form-input flex-1 text-sm"
              />
              <button
                onClick={handleGmapsSave}
                disabled={gmapsSaving || !gmapsKey}
                className="btn btn-primary text-sm px-3"
              >
                {gmapsSaving ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={handleGmapsTest}
                disabled={gmapsTesting || !gmapsStatus || gmapsStatus === null}
                className="btn btn-secondary text-sm px-3"
              >
                {gmapsTesting ? 'Testing...' : 'Test'}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Enables road distance and drive time calculations for warehouse options.
              Without a key, approximate straight-line distances are used.
            </p>
          </div>

          <div className="flex items-center gap-2 text-sm text-gray-500">
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">CD Market Intelligence</span>
            <span>Subscription required for transport pricing</span>
          </div>
        </div>
      </div>

      {/* Warehouses Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium">Warehouses</h3>
          <p className="text-sm text-gray-500">Delivery locations for vehicle transport</p>
        </div>
        <button
          onClick={() => { resetForm(); setShowForm(true); }}
          className="btn btn-primary"
        >
          Add Warehouse
        </button>
      </div>

      {/* Form */}
      {showForm && (
        <div className="border rounded-lg p-4 bg-gray-50">
          <h4 className="font-medium mb-4">{editingId ? 'Edit Warehouse' : 'New Warehouse'}</h4>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="form-label">Code *</label>
              <input
                type="text"
                value={form.code}
                onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="WHSE01"
                className="form-input w-full"
                disabled={!!editingId}
              />
            </div>
            <div>
              <label className="form-label">Name *</label>
              <input
                type="text"
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="Main Warehouse"
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">State *</label>
              <select
                value={form.state}
                onChange={e => setForm({ ...form, state: e.target.value })}
                className="form-select w-full"
              >
                <option value="">Select State...</option>
                {US_STATES.map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="form-label">City</label>
              <input
                type="text"
                value={form.city}
                onChange={e => setForm({ ...form, city: e.target.value })}
                className="form-input w-full"
              />
            </div>
            <div className="col-span-2">
              <label className="form-label">Address</label>
              <input
                type="text"
                value={form.address}
                onChange={e => setForm({ ...form, address: e.target.value })}
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">ZIP Code</label>
              <input
                type="text"
                value={form.zip_code}
                onChange={e => setForm({ ...form, zip_code: e.target.value })}
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Phone</label>
              <input
                type="text"
                value={form.phone}
                onChange={e => setForm({ ...form, phone: e.target.value })}
                placeholder="(555) 123-4567"
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Contact Name</label>
              <input
                type="text"
                value={form.contact_name}
                onChange={e => setForm({ ...form, contact_name: e.target.value })}
                placeholder="John Smith"
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Contact Phone</label>
              <input
                type="text"
                value={form.contact_phone}
                onChange={e => setForm({ ...form, contact_phone: e.target.value })}
                placeholder="(555) 123-4567"
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Location Type</label>
              <select
                value={form.location_type}
                onChange={e => setForm({ ...form, location_type: e.target.value })}
                className="form-select w-full"
              >
                <option value="BUSINESS">Business</option>
                <option value="RESIDENCE">Residence</option>
                <option value="DEALERSHIP">Dealership</option>
                <option value="AUCTION">Auction</option>
              </select>
            </div>
            <div>
              <label className="flex items-center gap-2 mt-6">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  onChange={e => setForm({ ...form, is_default: e.target.checked })}
                  className="form-checkbox"
                />
                <span className="text-sm">Default Warehouse</span>
              </label>
            </div>
            <div className="col-span-2">
              <label className="form-label">Transport Special Instructions</label>
              <textarea
                value={form.transport_special_instructions}
                onChange={e => setForm({ ...form, transport_special_instructions: e.target.value })}
                placeholder="Appointment required, hours: Mon-Fri 8am-5pm, etc."
                className="form-input w-full"
                rows={3}
              />
              <p className="text-xs text-gray-500 mt-1">
                These instructions will be included in exports to Central Dispatch
              </p>
            </div>
          </div>
          <div className="flex space-x-3 mt-4">
            <button onClick={handleSave} className="btn btn-primary">
              {editingId ? 'Update' : 'Create'}
            </button>
            <button onClick={resetForm} className="btn btn-secondary">Cancel</button>
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="p-8 text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
        </div>
      ) : warehouses.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          No warehouses configured yet.
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="table">
            <thead>
              <tr>
                <th>State</th>
                <th>Name</th>
                <th>City</th>
                <th>Code</th>
                <th>Contact</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {warehouses.map(wh => (
                <tr key={wh.id} className={wh.is_default ? 'bg-green-50' : ''}>
                  <td className="font-medium">
                    {wh.state}
                    {wh.is_default && (
                      <span className="ml-2 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">Default</span>
                    )}
                  </td>
                  <td>{wh.name}</td>
                  <td className="text-gray-500">{wh.city || '-'}</td>
                  <td className="font-mono text-sm">{wh.code}</td>
                  <td className="text-gray-500 text-sm">
                    {wh.contact_name && <div>{wh.contact_name}</div>}
                    {wh.phone && <div>{wh.phone}</div>}
                    {!wh.contact_name && !wh.phone && '-'}
                  </td>
                  <td>
                    <div className="flex space-x-2">
                      <button
                        onClick={() => editWarehouse(wh)}
                        className="text-sm text-blue-600 hover:text-blue-800"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDelete(wh.id)}
                        className="text-sm text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Help text */}
      <div className="bg-blue-50 p-4 rounded-lg">
        <h4 className="font-medium text-blue-800 mb-2">About Warehouses</h4>
        <ul className="text-sm text-blue-700 space-y-1">
          <li>Warehouses are used as delivery locations when exporting to Central Dispatch</li>
          <li>The default warehouse is auto-selected for new documents</li>
          <li>Transport Special Instructions are included in the CD listing notes</li>
          <li>Add a Google Maps API key above to enable road distance calculations</li>
        </ul>
      </div>
    </div>
  )
}
