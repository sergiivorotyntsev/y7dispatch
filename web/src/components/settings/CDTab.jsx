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
        <h3 className="text-lg font-medium mb-1">Central Dispatch — OAuth2 Credentials</h3>
        <p className="text-sm text-gray-500">Client credentials for the CD API (OAuth2 flow)</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="form-label">Client ID *</label>
          <input
            type="text"
            value={cd.client_id || ''}
            onChange={e => updateField('client_id', e.target.value)}
            placeholder="your-client-id"
            className="form-input w-full"
          />
        </div>
        <div>
          <label className="form-label">Client Secret *</label>
          <input
            type="password"
            value={cd.client_secret || ''}
            onChange={e => updateField('client_secret', e.target.value)}
            placeholder="your-client-secret"
            className="form-input w-full"
          />
        </div>
        <div>
          <label className="form-label">Marketplace ID *</label>
          <input
            type="text"
            value={cd.marketplace_id || ''}
            onChange={e => updateField('marketplace_id', e.target.value)}
            placeholder="10000"
            className="form-input w-full"
          />
        </div>
        <div>
          <label className="form-label">Scopes</label>
          <input
            type="text"
            value={cd.scopes || 'marketplace'}
            onChange={e => updateField('scopes', e.target.value)}
            placeholder="marketplace dispatchdocument_api"
            className="form-input w-full"
          />
          <p className="text-xs text-gray-500 mt-1">Space-separated OAuth2 scopes</p>
        </div>
        <div>
          <label className="form-label">Environment</label>
          <select
            value={cd.environment || 'test'}
            onChange={e => updateField('environment', e.target.value)}
            className="form-select w-full"
          >
            <option value="test">Test (Sandbox)</option>
            <option value="production">Production</option>
          </select>
        </div>
        <div>
          <label className="form-label">Shipper Username</label>
          <input
            type="text"
            value={cd.shipper_username || ''}
            onChange={e => updateField('shipper_username', e.target.value)}
            placeholder="shipper-username (reference only)"
            className="form-input w-full"
          />
          <p className="text-xs text-gray-500 mt-1">For reference only — not used in API auth</p>
        </div>
      </div>

      <div className="flex space-x-3">
        <button onClick={handleSave} className="btn btn-primary">Save</button>
        <button onClick={handleTest} className="btn btn-secondary">Test Connection</button>
      </div>

      {result && <TestResultCard result={result} />}

      <div className="bg-blue-50 p-4 rounded-lg">
        <h4 className="font-medium text-blue-800 mb-2">OAuth2 Authentication Flow</h4>
        <ul className="text-sm text-blue-700 space-y-1">
          <li>1. Client ID + Secret are sent to the CD token endpoint</li>
          <li>2. A Bearer token is returned and cached until expiry</li>
          <li>3. All API calls use the Bearer token in the Authorization header</li>
          <li>4. Token is auto-refreshed when it expires</li>
        </ul>
      </div>
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
