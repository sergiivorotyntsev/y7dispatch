import { useState, useEffect } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'
import { parseUTCDate } from '../../utils/date'

export default function EmailTab() {
  const { showMessage, setSaving } = useSettings()
  const [authMode, setAuthMode] = useState('oauth2') // 'oauth2' or 'imap'
  const [config, setConfig] = useState({})
  const [rules, setRules] = useState([])
  const [activity, setActivity] = useState([])
  const [polling, setPolling] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [loading, setLoading] = useState(true)

  // Auto-polling settings
  const [pollSettings, setPollSettings] = useState({
    auto_poll_enabled: true,
    poll_interval_minutes: 5,
    poll_since_days: 7,
  })
  const [pollStatus, setPollStatus] = useState(null)

  useEffect(() => {
    loadAll()
  }, [])

  async function loadAll() {
    setLoading(true)
    try {
      // Load credential store for both email services
      const [rulesData, activityData, pollData] = await Promise.all([
        api.getEmailRules().catch(() => []),
        api.getEmailActivity().catch(() => []),
        api.getPollStatus().catch(() => null),
      ])
      setRules(rulesData)
      setActivity(activityData)
      if (pollData) {
        setPollSettings({
          auto_poll_enabled: pollData.enabled,
          poll_interval_minutes: pollData.interval_minutes,
          poll_since_days: pollData.since_days,
        })
        setPollStatus(pollData)
      }

      // Check which credential is configured
      try {
        const creds = await api.getCredentials()
        const byService = {}
        creds.forEach(c => { byService[c.service] = c })

        if (byService.email_oauth) {
          setAuthMode('oauth2')
          setConfig(byService.email_oauth.config || {})
        } else if (byService.email_imap) {
          setAuthMode('imap')
          setConfig(byService.email_imap.config || {})
        }
      } catch (err) {
        console.debug('No email credentials found:', err.message)
      }
    } catch (err) {
      console.error('Failed to load email data:', err)
    } finally {
      setLoading(false)
    }
  }

  function updateField(field, value) {
    setConfig(prev => ({ ...prev, [field]: value }))
  }

  async function handleSave() {
    setSaving(true)
    try {
      const service = authMode === 'oauth2' ? 'email_oauth' : 'email_imap'
      // Save to credential store
      await api.saveCredential(service, config, true)

      // Also save allowed_senders + rules config to settings for the worker
      await api.updateEmailConfig({
        auth_type: authMode === 'oauth2' ? 'oauth2' : 'password',
        email_address: config.email_address,
        imap_server: authMode === 'oauth2' ? 'outlook.office365.com' : config.imap_server,
        imap_port: authMode === 'oauth2' ? 993 : (config.imap_port || 993),
        password: authMode === 'imap' ? config.password : undefined,
        allowed_senders: config.allowed_senders || [],
        // OAuth2 fields for worker
        tenant_id: config.tenant_id,
        client_id: config.client_id,
        client_secret: config.client_secret,
      })

      showMessage('success', 'Email settings saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const service = authMode === 'oauth2' ? 'email_oauth' : 'email_imap'
      const result = await api.testCredential(service)
      setTestResult(result)
      if (result.status === 'ok') {
        showMessage('success', result.message)
      } else {
        showMessage('error', result.message)
      }
    } catch (err) {
      setTestResult({ status: 'failed', message: err.message })
      showMessage('error', err.message)
    } finally {
      setTesting(false)
    }
  }

  async function handlePollNow() {
    setPolling(true)
    try {
      const result = await api.pollEmailNow()
      showMessage('success', 'Polled ' + result.processed + ' emails, ' + result.skipped + ' skipped')
      loadAll()
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setPolling(false)
    }
  }

  async function handleSaveRules() {
    setSaving(true)
    try {
      await api.updateEmailRules(rules)
      showMessage('success', 'Email rules saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
        <span className="ml-2 text-gray-500">Loading email settings...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium mb-4">Email Ingestion Settings</h3>
      </div>

      {/* Connection Settings */}
      <div className="border rounded-lg p-4">
        <h4 className="font-medium mb-3">Connection</h4>

        {/* Auth Mode Toggle */}
        <div className="mb-4">
          <label className="form-label">Authentication Method</label>
          <select
            value={authMode}
            onChange={e => {
              setAuthMode(e.target.value)
              setTestResult(null)
              // Pre-fill defaults for OAuth2
              if (e.target.value === 'oauth2') {
                setConfig(prev => ({
                  ...prev,
                  imap_server: 'outlook.office365.com',
                  imap_port: 993,
                }))
              }
            }}
            className="form-select w-full max-w-xs"
          >
            <option value="oauth2">Microsoft OAuth2 (Recommended)</option>
            <option value="imap">IMAP Password</option>
          </select>
          {authMode === 'oauth2' && (
            <p className="text-xs text-gray-500 mt-1">
              Uses Azure AD Client Credentials to authenticate with Microsoft 365 / GoDaddy M365 mailboxes.
              IMAP basic auth is blocked by Microsoft.
            </p>
          )}
        </div>

        {/* Common: Email Address */}
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="form-label">Email Address</label>
            <input
              type="email"
              value={config.email_address || ''}
              onChange={e => updateField('email_address', e.target.value)}
              className="form-input w-full"
              placeholder="dispatch@yourcompany.com"
            />
          </div>
        </div>

        {/* OAuth2 Fields */}
        {authMode === 'oauth2' && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="form-label">Tenant ID</label>
              <input
                type="text"
                value={config.tenant_id || ''}
                onChange={e => updateField('tenant_id', e.target.value)}
                className="form-input w-full"
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              />
              <p className="text-xs text-gray-400 mt-1">Azure AD Tenant ID (from Azure Portal)</p>
            </div>
            <div>
              <label className="form-label">Client ID</label>
              <input
                type="text"
                value={config.client_id || ''}
                onChange={e => updateField('client_id', e.target.value)}
                className="form-input w-full"
                placeholder="App (client) ID from Azure AD"
              />
            </div>
            <div>
              <label className="form-label">Client Secret</label>
              <input
                type="password"
                value={config.client_secret || ''}
                onChange={e => updateField('client_secret', e.target.value)}
                className="form-input w-full"
              />
            </div>
          </div>
        )}

        {/* IMAP Password Fields */}
        {authMode === 'imap' && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="form-label">IMAP Server</label>
              <input
                type="text"
                value={config.imap_server || ''}
                onChange={e => updateField('imap_server', e.target.value)}
                placeholder="imap.gmail.com"
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Port</label>
              <input
                type="number"
                value={config.imap_port || 993}
                onChange={e => updateField('imap_port', parseInt(e.target.value))}
                className="form-input w-full"
              />
            </div>
            <div>
              <label className="form-label">Password / App Password</label>
              <input
                type="password"
                value={config.password || ''}
                onChange={e => updateField('password', e.target.value)}
                className="form-input w-full"
              />
            </div>
          </div>
        )}

        <div className="flex space-x-3 mt-4">
          <button onClick={handleSave} className="btn btn-primary">Save</button>
          <button onClick={handleTest} disabled={testing} className="btn btn-secondary">
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          <button onClick={handlePollNow} disabled={polling} className="btn btn-secondary">
            {polling ? 'Polling...' : 'Poll Now'}
          </button>
        </div>

        {testResult && <TestResultCard result={testResult} />}
      </div>

      {/* Auto-Polling Settings */}
      <div className="border rounded-lg p-4">
        <h4 className="font-medium mb-3">Auto-Polling</h4>
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div>
            <label className="form-label">Auto-poll</label>
            <div className="flex items-center mt-1">
              <button
                onClick={async () => {
                  const newVal = !pollSettings.auto_poll_enabled
                  setPollSettings(prev => ({ ...prev, auto_poll_enabled: newVal }))
                  try {
                    await api.updatePollSettings({ enabled: newVal })
                    showMessage('success', newVal ? 'Auto-poll enabled' : 'Auto-poll disabled')
                  } catch (err) { showMessage('error', err.message) }
                }}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  pollSettings.auto_poll_enabled ? 'bg-green-600' : 'bg-gray-300'
                }`}
              >
                <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                  pollSettings.auto_poll_enabled ? 'translate-x-6' : 'translate-x-1'
                }`} />
              </button>
              <span className="ml-2 text-sm text-gray-700">
                {pollSettings.auto_poll_enabled ? 'ON' : 'OFF'}
              </span>
            </div>
          </div>
          <div>
            <label className="form-label">Interval</label>
            <select
              value={pollSettings.poll_interval_minutes}
              onChange={async (e) => {
                const val = parseInt(e.target.value)
                setPollSettings(prev => ({ ...prev, poll_interval_minutes: val }))
                try {
                  await api.updatePollSettings({ interval_minutes: val })
                  showMessage('success', `Poll interval set to ${val} min`)
                } catch (err) { showMessage('error', err.message) }
              }}
              className="form-select w-full"
            >
              <option value={1}>Every 1 min</option>
              <option value={2}>Every 2 min</option>
              <option value={5}>Every 5 min</option>
              <option value={10}>Every 10 min</option>
              <option value={15}>Every 15 min</option>
              <option value={30}>Every 30 min</option>
            </select>
          </div>
          <div>
            <label className="form-label">Lookback</label>
            <select
              value={pollSettings.poll_since_days}
              onChange={async (e) => {
                const val = parseInt(e.target.value)
                setPollSettings(prev => ({ ...prev, poll_since_days: val }))
                try {
                  await api.updatePollSettings({ since_days: val })
                  showMessage('success', `Lookback set to ${val} days`)
                } catch (err) { showMessage('error', err.message) }
              }}
              className="form-select w-full"
            >
              <option value={1}>1 day</option>
              <option value={3}>3 days</option>
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
            </select>
          </div>
        </div>
        {pollStatus && (
          <div className="text-sm text-gray-600">
            {pollStatus.is_polling ? (
              <span className="text-blue-600 font-medium">Polling now...</span>
            ) : pollStatus.last_poll_at ? (
              <span>Last poll: {parseUTCDate(pollStatus.last_poll_at).toLocaleString()} ({pollStatus.polls_completed} total)</span>
            ) : (
              <span className="text-gray-400">No polls completed yet</span>
            )}
            {pollStatus.last_poll_error && (
              <span className="ml-3 text-red-600">Last error: {pollStatus.last_poll_error}</span>
            )}
          </div>
        )}
      </div>

      {/* Sender Filter */}
      <div className="border rounded-lg p-4">
        <h4 className="font-medium mb-2">Sender Filter</h4>
        <p className="text-sm text-gray-500 mb-3">
          Only process emails from these senders. Leave empty to accept all senders.
        </p>
        <div className="space-y-2">
          {(config.allowed_senders || []).map((sender, idx) => (
            <div key={idx} className="flex items-center space-x-2">
              <input
                type="text"
                value={sender}
                onChange={e => {
                  const updated = [...(config.allowed_senders || [])]
                  updated[idx] = e.target.value
                  updateField('allowed_senders', updated)
                }}
                className="form-input flex-1"
                placeholder="email@example.com or @domain.com"
              />
              <button
                onClick={() => {
                  const updated = (config.allowed_senders || []).filter((_, i) => i !== idx)
                  updateField('allowed_senders', updated)
                }}
                className="text-red-600 hover:text-red-800 p-1"
              >
                X
              </button>
            </div>
          ))}
          <button
            onClick={() => updateField('allowed_senders', [...(config.allowed_senders || []), ''])}
            className="btn btn-sm btn-secondary"
          >
            Add Sender
          </button>
        </div>
      </div>

      {/* Rules */}
      <div className="border rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h4 className="font-medium">Processing Rules</h4>
          <button
            onClick={() => setRules([...rules, {
              name: 'New Rule',
              enabled: true,
              priority: 0,
              condition_type: 'subject_contains',
              condition_value: '',
              action: 'process',
            }])}
            className="btn btn-sm btn-secondary"
          >
            Add Rule
          </button>
        </div>
        {rules.length === 0 ? (
          <p className="text-gray-500 text-sm">No rules configured. Add a rule to start processing emails.</p>
        ) : (
          <div className="space-y-2">
            {rules.map((rule, index) => (
              <div key={index} className="flex items-center space-x-2 p-2 bg-gray-50 rounded">
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={e => {
                    const updated = [...rules]
                    updated[index] = { ...rule, enabled: e.target.checked }
                    setRules(updated)
                  }}
                  className="form-checkbox"
                />
                <input
                  type="text"
                  value={rule.name}
                  onChange={e => {
                    const updated = [...rules]
                    updated[index] = { ...rule, name: e.target.value }
                    setRules(updated)
                  }}
                  className="form-input flex-1"
                  placeholder="Rule name"
                />
                <select
                  value={rule.condition_type}
                  onChange={e => {
                    const updated = [...rules]
                    updated[index] = { ...rule, condition_type: e.target.value }
                    setRules(updated)
                  }}
                  className="form-select"
                >
                  <option value="subject_contains">Subject Contains</option>
                  <option value="from_contains">From Contains</option>
                  <option value="from_domain">From Domain</option>
                  <option value="attachment_type">Attachment Type</option>
                </select>
                <input
                  type="text"
                  value={rule.condition_value}
                  onChange={e => {
                    const updated = [...rules]
                    updated[index] = { ...rule, condition_value: e.target.value }
                    setRules(updated)
                  }}
                  className="form-input w-32"
                  placeholder="Value"
                />
                <select
                  value={rule.action}
                  onChange={e => {
                    const updated = [...rules]
                    updated[index] = { ...rule, action: e.target.value }
                    setRules(updated)
                  }}
                  className="form-select"
                >
                  <option value="process">Process</option>
                  <option value="ignore">Ignore</option>
                </select>
                <button
                  onClick={() => setRules(rules.filter((_, i) => i !== index))}
                  className="text-red-600 hover:text-red-800 p-1"
                >
                  X
                </button>
              </div>
            ))}
            <button onClick={handleSaveRules} className="btn btn-primary mt-2">
              Save Rules
            </button>
          </div>
        )}
      </div>

      {/* Activity Log */}
      <div className="border rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h4 className="font-medium">Recent Activity</h4>
          <button onClick={loadAll} className="btn btn-sm btn-secondary">
            Refresh
          </button>
        </div>
        {activity.length === 0 ? (
          <p className="text-gray-500 text-sm">No activity yet.</p>
        ) : (
          <div className="max-h-64 overflow-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Subject</th>
                  <th>Status</th>
                  <th>Rule</th>
                </tr>
              </thead>
              <tbody>
                {activity.slice(0, 20).map(item => (
                  <tr key={item.id}>
                    <td className="text-xs text-gray-500">
                      {item.timestamp ? parseUTCDate(item.timestamp).toLocaleString() : '-'}
                    </td>
                    <td className="truncate max-w-[200px]">{item.subject || '-'}</td>
                    <td>
                      <span className={'badge ' + (item.status === 'processed' ? 'badge-success' : item.status === 'skipped' ? 'badge-warning' : 'badge-error')}>
                        {item.status}
                      </span>
                    </td>
                    <td className="text-xs">{item.rule_matched || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function TestResultCard({ result }) {
  const isOk = result.status === 'ok'
  return (
    <div className={'mt-4 p-4 rounded-lg ' + (isOk ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800')}>
      <p className="font-medium">{isOk ? 'Connected' : 'Failed'}</p>
      <p className="text-sm">{result.message}</p>
      {result.details && (
        <div className="text-xs mt-2">
          {result.details.unread_messages !== undefined && (
            <p>Unread: {result.details.unread_messages}</p>
          )}
          {result.details.expires_at && (
            <p>Token expires: {new Date(result.details.expires_at).toLocaleString()}</p>
          )}
        </div>
      )}
    </div>
  )
}
