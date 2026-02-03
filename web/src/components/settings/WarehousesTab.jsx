import { useState, useEffect } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

export default function WarehousesTab() {
  const { showMessage, setSaving } = useSettings()
  const [warehouses, setWarehouses] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState({
    code: '',
    name: '',
    address: '',
    city: '',
    state: '',
    zip_code: '',
    timezone: 'America/New_York',
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
      address: '',
      city: '',
      state: '',
      zip_code: '',
      timezone: 'America/New_York',
    })
    setEditingId(null)
    setShowForm(false)
  }

  function editWarehouse(wh) {
    setForm({
      code: wh.code,
      name: wh.name,
      address: wh.address || '',
      city: wh.city || '',
      state: wh.state || '',
      zip_code: wh.zip_code || '',
      timezone: wh.timezone || 'America/New_York',
    })
    setEditingId(wh.id)
    setShowForm(true)
  }

  async function handleSave() {
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
        <h3 className="text-lg font-medium">Warehouses</h3>
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
              <label className="form-label">Code</label>
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
              <label className="form-label">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="Main Warehouse"
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
              <label className="form-label">City</label>
              <input
                type="text"
                value={form.city}
                onChange={e => setForm({ ...form, city: e.target.value })}
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">State</label>
              <input
                type="text"
                value={form.state}
                onChange={e => setForm({ ...form, state: e.target.value })}
                maxLength={2}
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
              <label className="form-label">Timezone</label>
              <select
                value={form.timezone}
                onChange={e => setForm({ ...form, timezone: e.target.value })}
                className="form-select w-full"
              >
                <option value="America/New_York">Eastern</option>
                <option value="America/Chicago">Central</option>
                <option value="America/Denver">Mountain</option>
                <option value="America/Los_Angeles">Pacific</option>
              </select>
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
                <th>Code</th>
                <th>Name</th>
                <th>Location</th>
                <th>Timezone</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {warehouses.map(wh => (
                <tr key={wh.id}>
                  <td className="font-mono">{wh.code}</td>
                  <td>{wh.name}</td>
                  <td className="text-sm text-gray-500">
                    {[wh.city, wh.state].filter(Boolean).join(', ') || '-'}
                  </td>
                  <td className="text-sm">{wh.timezone?.split('/')[1] || '-'}</td>
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
