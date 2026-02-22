import { useState, useEffect } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

const SERVICES = [
  { id: 'sheets', label: 'Google Sheets', group: 'sheets' },
  { id: 'anthropic', label: 'Anthropic (Claude)', group: 'anthropic' },
  { id: 'google_maps', label: 'Google Maps', group: 'google_maps' },
]

export default function CredentialsTab() {
  const { showMessage } = useSettings()
  const [credentials, setCredentials] = useState({})
  const [loading, setLoading] = useState(true)
  const [expandedCard, setExpandedCard] = useState(null)
  const [testResults, setTestResults] = useState({})
  const [testing, setTesting] = useState({})

  useEffect(() => {
    loadCredentials()
  }, [])

  async function loadCredentials() {
    setLoading(true)
    try {
      const data = await api.getCredentials()
      const byService = {}
      data.forEach(c => { byService[c.service] = c })
      setCredentials(byService)
    } catch (err) {
      showMessage('error', 'Failed to load credentials: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSave(service, config, enabled) {
    try {
      await api.saveCredential(service, config, enabled)
      showMessage('success', `${service} credentials saved`)
      loadCredentials()
    } catch (err) {
      showMessage('error', err.message)
    }
  }

  async function handleTest(service) {
    setTesting(prev => ({ ...prev, [service]: true }))
    setTestResults(prev => ({ ...prev, [service]: null }))
    try {
      const result = await api.testCredential(service)
      setTestResults(prev => ({ ...prev, [service]: result }))
      if (result.status === 'ok') {
        showMessage('success', result.message)
      } else {
        showMessage('error', result.message)
      }
      // Reload credentials so DB status (green/red dot) persists in StatusSummary
      loadCredentials()
    } catch (err) {
      setTestResults(prev => ({ ...prev, [service]: { status: 'failed', message: err.message } }))
      showMessage('error', err.message)
    } finally {
      setTesting(prev => ({ ...prev, [service]: false }))
    }
  }

  async function handleDelete(service) {
    if (!confirm(`Delete ${service} credentials?`)) return
    try {
      await api.deleteCredential(service)
      showMessage('success', `${service} credentials deleted`)
      loadCredentials()
    } catch (err) {
      showMessage('error', err.message)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
        <span className="ml-2 text-gray-500">Loading credentials...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium mb-2">Integration Credentials</h3>
        <p className="text-sm text-gray-500">Manage encrypted credentials for all integrations. Secrets are stored with Fernet encryption.</p>
      </div>

      {/* Status Summary */}
      <StatusSummary credentials={credentials} />

      {/* Google Sheets */}
      <CredentialCard
        title="Google Sheets"
        expanded={expandedCard === 'sheets'}
        onToggle={() => setExpandedCard(expandedCard === 'sheets' ? null : 'sheets')}
        configured={!!credentials.sheets}
        testStatus={testResults.sheets}
        dbTestStatus={credentials.sheets?.last_test_status}
      >
        <SheetsForm
          initial={credentials.sheets?.config || {}}
          enabled={credentials.sheets?.enabled || false}
          onSave={(config, enabled) => handleSave('sheets', config, enabled)}
          onTest={() => handleTest('sheets')}
          onDelete={() => handleDelete('sheets')}
          testing={testing.sheets}
          testResult={testResults.sheets}
          hasCredential={!!credentials.sheets}
        />
      </CredentialCard>

      {/* Anthropic */}
      <CredentialCard
        title="Anthropic (Claude AI)"
        expanded={expandedCard === 'anthropic'}
        onToggle={() => setExpandedCard(expandedCard === 'anthropic' ? null : 'anthropic')}
        configured={!!credentials.anthropic}
        testStatus={testResults.anthropic}
        dbTestStatus={credentials.anthropic?.last_test_status}
      >
        <AnthropicForm
          initial={credentials.anthropic?.config || {}}
          enabled={credentials.anthropic?.enabled || false}
          onSave={(config, enabled) => handleSave('anthropic', config, enabled)}
          onTest={() => handleTest('anthropic')}
          onDelete={() => handleDelete('anthropic')}
          testing={testing.anthropic}
          testResult={testResults.anthropic}
          hasCredential={!!credentials.anthropic}
        />
      </CredentialCard>

      {/* Google Maps */}
      <CredentialCard
        title="Google Maps (Distance Services)"
        expanded={expandedCard === 'google_maps'}
        onToggle={() => setExpandedCard(expandedCard === 'google_maps' ? null : 'google_maps')}
        configured={!!credentials.google_maps}
        testStatus={testResults.google_maps}
        dbTestStatus={credentials.google_maps?.last_test_status}
      >
        <GoogleMapsForm
          initial={credentials.google_maps?.config || {}}
          enabled={credentials.google_maps?.enabled || false}
          onSave={(config, enabled) => handleSave('google_maps', config, enabled)}
          onTest={() => handleTest('google_maps')}
          onDelete={() => handleDelete('google_maps')}
          testing={testing.google_maps}
          testResult={testResults.google_maps}
          hasCredential={!!credentials.google_maps}
        />
      </CredentialCard>
    </div>
  )
}


// =============================================================================
// Sub-components
// =============================================================================

function StatusSummary({ credentials }) {
  const services = [
    { key: 'sheets', label: 'Google Sheets' },
    { key: 'anthropic', label: 'Anthropic' },
    { key: 'google_maps', label: 'Google Maps' },
  ]

  return (
    <div className="grid grid-cols-3 gap-3">
      {services.map(svc => {
        const cred = credentials[svc.key]
        const configured = !!cred
        const testOk = cred?.last_test_status === 'ok'
        const testFailed = cred?.last_test_status === 'failed'

        return (
          <div key={svc.key} className="flex items-center space-x-2 p-2 rounded bg-gray-50">
            <span className={
              'w-2 h-2 rounded-full ' +
              (testOk ? 'bg-green-500' : testFailed ? 'bg-red-500' : configured ? 'bg-yellow-500' : 'bg-gray-300')
            } />
            <span className="text-sm text-gray-700">{svc.label}</span>
            <span className={'text-xs ml-auto ' + (configured ? 'text-green-600' : 'text-gray-400')}>
              {testOk ? 'OK' : testFailed ? 'Failed' : configured ? 'Saved' : 'Not set'}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function CredentialCard({ title, expanded, onToggle, configured, testStatus, dbTestStatus, children }) {
  // Use session test result if available, otherwise fall back to DB status
  const effectiveStatus = testStatus?.status || dbTestStatus
  return (
    <div className="border rounded-lg">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
      >
        <div className="flex items-center space-x-3">
          <span className={
            'w-3 h-3 rounded-full ' +
            (effectiveStatus === 'ok' ? 'bg-green-500' :
             effectiveStatus === 'failed' ? 'bg-red-500' :
             configured ? 'bg-yellow-500' : 'bg-gray-300')
          } />
          <h4 className="font-medium">{title}</h4>
          <span className={'text-xs px-2 py-0.5 rounded ' + (configured ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500')}>
            {configured ? 'Configured' : 'Not configured'}
          </span>
        </div>
        <span className="text-gray-400">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>
      {expanded && <div className="p-4 pt-0 border-t">{children}</div>}
    </div>
  )
}

function FormButtons({ onSave, onTest, onDelete, testing, hasCredential }) {
  return (
    <div className="flex space-x-3 mt-4">
      <button onClick={onSave} className="btn btn-primary">Save</button>
      {hasCredential && (
        <>
          <button onClick={onTest} disabled={testing} className="btn btn-secondary">
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          <button onClick={onDelete} className="btn btn-secondary text-red-600 hover:text-red-800">
            Delete
          </button>
        </>
      )}
    </div>
  )
}

function TestResultBanner({ result }) {
  if (!result) return null
  const isOk = result.status === 'ok'
  return (
    <div className={'mt-3 p-3 rounded-lg text-sm ' + (isOk ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800')}>
      <p className="font-medium">{isOk ? 'Connected' : 'Failed'}</p>
      <p>{result.message}</p>
      {result.duration_ms && <p className="text-xs mt-1">Response time: {result.duration_ms}ms</p>}
    </div>
  )
}

function EnableToggle({ enabled, onChange }) {
  return (
    <label className="flex items-center space-x-2 mb-4">
      <input type="checkbox" checked={enabled} onChange={e => onChange(e.target.checked)} className="form-checkbox" />
      <span className="text-sm text-gray-700">Enabled</span>
    </label>
  )
}


// =============================================================================
// Service-specific forms
// =============================================================================

function SheetsForm({ initial, enabled: initEnabled, onSave, onTest, onDelete, testing, testResult, hasCredential }) {
  const [config, setConfig] = useState(initial)
  const [enabled, setEnabled] = useState(initEnabled)
  const update = (k, v) => setConfig(prev => ({ ...prev, [k]: v }))

  return (
    <div>
      <EnableToggle enabled={enabled} onChange={setEnabled} />
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="form-label">Spreadsheet ID</label>
          <input type="text" value={config.spreadsheet_id || ''} onChange={e => update('spreadsheet_id', e.target.value)} className="form-input w-full" />
        </div>
        <div>
          <label className="form-label">Sheet Name</label>
          <input type="text" value={config.sheet_name || 'Pickups'} onChange={e => update('sheet_name', e.target.value)} className="form-input w-full" />
        </div>
        <div className="col-span-2">
          <label className="form-label">Credentials File Path</label>
          <input type="text" value={config.credentials_file || 'config/sheets_credentials.json'} onChange={e => update('credentials_file', e.target.value)} className="form-input w-full" />
          <p className="text-xs text-gray-400 mt-1">Path to the Google service account JSON file on the server</p>
        </div>
      </div>
      <FormButtons onSave={() => onSave(config, enabled)} onTest={onTest} onDelete={onDelete} testing={testing} hasCredential={hasCredential} />
      <TestResultBanner result={testResult} />
    </div>
  )
}

function AnthropicForm({ initial, enabled: initEnabled, onSave, onTest, onDelete, testing, testResult, hasCredential }) {
  const [config, setConfig] = useState(initial)
  const [enabled, setEnabled] = useState(initEnabled)
  const update = (k, v) => setConfig(prev => ({ ...prev, [k]: v }))

  return (
    <div>
      <EnableToggle enabled={enabled} onChange={setEnabled} />
      <div className="grid grid-cols-1 gap-4">
        <div>
          <label className="form-label">API Key</label>
          <input type="password" value={config.api_key || ''} onChange={e => update('api_key', e.target.value)} placeholder="sk-ant-..." className="form-input w-full" />
          <p className="text-xs text-gray-400 mt-1">Used for Claude Haiku extraction. Falls back to ANTHROPIC_API_KEY env var if not set.</p>
        </div>
      </div>
      <FormButtons onSave={() => onSave(config, enabled)} onTest={onTest} onDelete={onDelete} testing={testing} hasCredential={hasCredential} />
      <TestResultBanner result={testResult} />
    </div>
  )
}

function GoogleMapsForm({ initial, enabled: initEnabled, onSave, onTest, onDelete, testing, testResult, hasCredential }) {
  const [config, setConfig] = useState(initial)
  const [enabled, setEnabled] = useState(initEnabled)
  const update = (k, v) => setConfig(prev => ({ ...prev, [k]: v }))

  return (
    <div>
      <EnableToggle enabled={enabled} onChange={setEnabled} />
      <div className="grid grid-cols-1 gap-4">
        <div>
          <label className="form-label">API Key</label>
          <input type="password" value={config.api_key || ''} onChange={e => update('api_key', e.target.value)} placeholder="AIza..." className="form-input w-full" />
          <p className="text-xs text-gray-400 mt-1">Enables road distance and drive time calculations for warehouse options. Without a key, approximate straight-line distances are used.</p>
        </div>
      </div>
      <FormButtons onSave={() => onSave(config, enabled)} onTest={onTest} onDelete={onDelete} testing={testing} hasCredential={hasCredential} />
      <TestResultBanner result={testResult} />
    </div>
  )
}
