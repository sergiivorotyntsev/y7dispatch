import { useState } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

export default function ExportTargetsTab() {
  const { settings, updateSettings, showMessage, setSaving } = useSettings()
  const [targets, setTargets] = useState(settings.exportTargets || [])

  async function handleSave() {
    setSaving(true)
    try {
      await api.updateExportTargets(targets)
      showMessage('success', 'Export targets saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  function toggleTarget(target) {
    if (targets.includes(target)) {
      setTargets(targets.filter(t => t !== target))
    } else {
      setTargets([...targets, target])
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium mb-4">Export Targets</h3>
        <p className="text-sm text-gray-500 mb-4">
          Select where extracted data should be exported
        </p>
      </div>

      <div className="space-y-3">
        {[
          { id: 'central_dispatch', name: 'Central Dispatch', description: 'Export listings to CD API' },
          { id: 'clickup', name: 'ClickUp', description: 'Create tasks in ClickUp' },
          { id: 'sheets', name: 'Google Sheets', description: 'Append rows to spreadsheet' },
        ].map(target => (
          <label key={target.id} className="flex items-start p-4 border rounded-lg cursor-pointer hover:bg-gray-50">
            <input
              type="checkbox"
              checked={targets.includes(target.id)}
              onChange={() => toggleTarget(target.id)}
              className="mt-1 form-checkbox"
            />
            <div className="ml-3">
              <p className="font-medium">{target.name}</p>
              <p className="text-sm text-gray-500">{target.description}</p>
            </div>
          </label>
        ))}
      </div>

      <button onClick={handleSave} className="btn btn-primary">
        Save Targets
      </button>
    </div>
  )
}
