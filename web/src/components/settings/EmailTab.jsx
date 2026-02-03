import { useState, useEffect } from 'react'
import { useSettings } from './SettingsContext'
import api from '../../api'

export default function EmailTab() {
  const { settings, showMessage, setSaving, testConnection, testResults } = useSettings()
  const [email, setEmail] = useState(settings.email || {})
  const [rules, setRules] = useState([])
  const [activity, setActivity] = useState([])
  const [polling, setPolling] = useState(false)

  useEffect(() => {
    loadRulesAndActivity()
  }, [])

  async function loadRulesAndActivity() {
    try {
      const [rulesData, activityData] = await Promise.all([
        api.getEmailRules().catch(() => []),
        api.getEmailActivity().catch(() => []),
      ])
      setRules(rulesData)
      setActivity(activityData)
    } catch (err) {
      console.error('Failed to load email data:', err)
    }
  }

  async function handleSave() {
    setSaving(true)
    try {
      await api.updateEmailConfig(email)
      showMessage('success', 'Email settings saved')
    } catch (err) {
      showMessage('error', err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    await testConnection('email', api.testEmailConnection)
  }

  async function handlePollNow() {
    setPolling(true)
    try {
      const result = await api.pollEmailNow()
      showMessage('success', 'Polled ' + result.processed + ' emails, ' + result.skipped + ' skipped')
      loadRulesAndActivity()
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

  function updateField(field, value) {
    setEmail(prev => ({ ...prev, [field]: value }))
  }

  const result = testResults.email

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium mb-4">Email Ingestion Settings</h3>
      </div>

      {/* IMAP Settings */}
      <div className="border rounded-lg p-4">
        <h4 className="font-medium mb-3">IMAP Connection</h4>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="form-label">IMAP Server</label>
            <input
              type="text"
              value={email.imap_server || ''}
              onChange={e => updateField('imap_server', e.target.value)}
              placeholder="imap.gmail.com"
              className="form-input w-full"
            />
          </div>
          <div>
            <label className="form-label">Port</label>
            <input
              type="number"
              value={email.imap_port || 993}
              onChange={e => updateField('imap_port', parseInt(e.target.value))}
              className="form-input w-full"
            />
          </div>
          <div>
            <label className="form-label">Email Address</label>
            <input
              type="email"
              value={email.email_address || ''}
              onChange={e => updateField('email_address', e.target.value)}
              className="form-input w-full"
            />
          </div>
          <div>
            <label className="form-label">Password</label>
            <input
              type="password"
              value={email.password || ''}
              onChange={e => updateField('password', e.target.value)}
              className="form-input w-full"
            />
          </div>
        </div>
        <div className="flex space-x-3 mt-4">
          <button onClick={handleSave} className="btn btn-primary">Save</button>
          <button onClick={handleTest} className="btn btn-secondary">Test Connection</button>
          <button onClick={handlePollNow} disabled={polling} className="btn btn-secondary">
            {polling ? 'Polling...' : 'Poll Now'}
          </button>
        </div>

        {result && <TestResultCard result={result} />}
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
          <button onClick={loadRulesAndActivity} className="btn btn-sm btn-secondary">
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
                      {item.timestamp ? new Date(item.timestamp).toLocaleString() : '-'}
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
        </div>
      )}
    </div>
  )
}
