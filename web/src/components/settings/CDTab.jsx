import { useState } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

export default function CDTab() {
  const { settings, showMessage, setSaving, testConnection, testResults } = useSettings()
  const [cd, setCd] = useState(settings.cd || {})

  async function handleSave() {
    setSaving(true)
    try {
      await api.updateCDConfig(cd)
      showMessage('success', 'Central Dispatch settings saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    await testConnection('cd', api.testCDConnection)
  }

  function updateField(field, value) {
    setCd(prev => ({ ...prev, [field]: value }))
  }

  const result = testResults.cd

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium mb-4">Central Dispatch Configuration</h3>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="form-label">Username</label>
          <input
            type="text"
            value={cd.username || ''}
            onChange={e => updateField('username', e.target.value)}
            className="form-input w-full"
          />
        </div>
        <div>
          <label className="form-label">Password</label>
          <input
            type="password"
            value={cd.password || ''}
            onChange={e => updateField('password', e.target.value)}
            className="form-input w-full"
          />
        </div>
        <div>
          <label className="form-label">Marketplace ID</label>
          <input
            type="text"
            value={cd.marketplace_id || ''}
            onChange={e => updateField('marketplace_id', e.target.value)}
            className="form-input w-full"
          />
        </div>
        <div>
          <label className="form-label">Environment</label>
          <select
            value={cd.sandbox ? 'sandbox' : 'production'}
            onChange={e => updateField('sandbox', e.target.value === 'sandbox')}
            className="form-select w-full"
          >
            <option value="sandbox">Sandbox</option>
            <option value="production">Production</option>
          </select>
        </div>
      </div>

      <div className="flex space-x-3">
        <button onClick={handleSave} className="btn btn-primary">Save</button>
        <button onClick={handleTest} className="btn btn-secondary">Test Connection</button>
      </div>

      {result && <TestResultCard result={result} />}
    </div>
  )
}

function TestResultCard({ result }) {
  const isOk = result.status === 'ok'
  return (
    <div className={'p-4 rounded-lg ' + (isOk ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800')}>
      <p className="font-medium">{isOk ? 'Connected' : 'Failed'}</p>
      <p className="text-sm">{result.message}</p>
      {result.duration_ms && <p className="text-xs mt-1">Response time: {result.duration_ms}ms</p>}
    </div>
  )
}
