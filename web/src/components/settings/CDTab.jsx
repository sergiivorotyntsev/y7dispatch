import { useState, useEffect } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

export default function CDTab() {
  const { settings, showMessage, setSaving, testConnection, testResults } = useSettings()
  const [cd, setCd] = useState(settings.cd || {})
  const [dbTestStatus, setDbTestStatus] = useState(null)
  const [dbTestedAt, setDbTestedAt] = useState(null)
  const [credLoaded, setCredLoaded] = useState(false)

  // Load saved credential from credential store on mount
  useEffect(() => {
    api.getCredential('cd_api').then(data => {
      if (data && data.config) {
        setCd(prev => ({
          ...prev,
          client_id: data.config.client_id || prev.client_id || '',
          client_secret: data.config.client_secret || prev.client_secret || '',
          marketplace_id: data.config.marketplace_id || prev.marketplace_id || '',
          scopes: data.config.scopes || prev.scopes || 'marketplace',
          environment: data.config.environment || prev.environment || 'test',
          shipper_username: data.config.shipper_username || prev.shipper_username || '',
        }))
        setDbTestStatus(data.last_test_status)
        setDbTestedAt(data.last_tested_at)
        setCredLoaded(true)
      }
    }).catch(() => {
      // No saved credential — use settings.cd if available
      setCredLoaded(true)
    })
  }, [])

  async function handleSave() {
    setSaving(true)
    try {
      // Save to both settings and credential store
      await api.updateCDConfig(cd)
      await api.saveCredential('cd_api', {
        client_id: cd.client_id,
        client_secret: cd.client_secret,
        marketplace_id: cd.marketplace_id,
        scopes: cd.scopes,
        environment: cd.environment,
        shipper_username: cd.shipper_username,
      }, true)
      showMessage('success', 'Central Dispatch settings saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    const result = await testConnection('cd', api.testCDConnection)
    if (result && result.status === 'ok') {
      setDbTestStatus('ok')
      setDbTestedAt(new Date().toISOString())
    } else {
      setDbTestStatus('failed')
    }
  }

  function updateField(field, value) {
    setCd(prev => ({ ...prev, [field]: value }))
  }

  const result = testResults.cd
  const isConnected = dbTestStatus === 'ok' || dbTestStatus === 'success'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium mb-1">Central Dispatch — OAuth2 Credentials</h3>
          <p className="text-sm text-gray-500">Client credentials for the CD API (OAuth2 flow)</p>
        </div>
        {credLoaded && (
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium ${
            isConnected ? 'bg-green-100 text-green-800' : dbTestStatus ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-500'
          }`}>
            <span className={`w-2.5 h-2.5 rounded-full ${
              isConnected ? 'bg-green-500' : dbTestStatus ? 'bg-red-500' : 'bg-gray-400'
            }`}></span>
            {isConnected ? 'Connected' : dbTestStatus ? 'Failed' : 'Not tested'}
          </div>
        )}
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

      {dbTestedAt && !result && (
        <div className={`p-3 rounded-lg text-sm ${isConnected ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          Last tested: {new Date(dbTestedAt).toLocaleString()} — {isConnected ? 'Connected' : 'Failed'}
        </div>
      )}

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
      {result.details && result.details.expires_in && (
        <p className="text-xs mt-1">Token expires in: {result.details.expires_in}s</p>
      )}
      {result.duration_ms && <p className="text-xs mt-1">Response time: {result.duration_ms}ms</p>}
    </div>
  )
}
