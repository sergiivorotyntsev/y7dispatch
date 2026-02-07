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
  })

  useEffect(() => {
    loadWarehouses()
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

  function resetForm() {
    setForm({
      code: '',
      name: '',
      state: '',
      city: '',
      address: '',
      zip_code: '',
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

  return (
    <div className="space-y-6">
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
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {warehouses.map(wh => (
                <tr key={wh.id}>
                  <td className="font-medium">{wh.state}</td>
                  <td>{wh.name}</td>
                  <td className="text-gray-500">{wh.city || '-'}</td>
                  <td className="font-mono text-sm">{wh.code}</td>
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
    </div>
  )
}
