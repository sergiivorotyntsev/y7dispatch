import { useState, useEffect } from 'react'
import api from '../../api'

export default function AuditLogTab() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    loadLogs()
  }, [])

  async function loadLogs() {
    setLoading(true)
    try {
      const params = filter ? { integration: filter } : {}
      const data = await api.getIntegrationAuditLog(params)
      setLogs(data)
    } catch (err) {
      console.error('Failed to load audit log:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLogs()
  }, [filter])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Integration Audit Log</h3>
        <div className="flex space-x-2">
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="form-select"
          >
            <option value="">All Integrations</option>
            <option value="cd">Central Dispatch</option>
            <option value="clickup">ClickUp</option>
            <option value="sheets">Google Sheets</option>
            <option value="email">Email</option>
            <option value="warehouses">Warehouses</option>
          </select>
          <button onClick={loadLogs} className="btn btn-secondary">
            Refresh
          </button>
        </div>
      </div>

      {loading ? (
        <div className="p-8 text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          No audit log entries found.
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="table text-sm">
            <thead>
              <tr>
                <th>Time</th>
                <th>Integration</th>
                <th>Action</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <tr key={log.id}>
                  <td className="text-xs text-gray-500 whitespace-nowrap">
                    {log.timestamp ? new Date(log.timestamp).toLocaleString() : '-'}
                  </td>
                  <td>
                    <span className="badge badge-info">{log.integration}</span>
                  </td>
                  <td>{log.action}</td>
                  <td>
                    <span className={'badge ' + (log.status === 'success' ? 'badge-success' : log.status === 'failed' ? 'badge-error' : 'badge-warning')}>
                      {log.status}
                    </span>
                  </td>
                  <td className="text-xs max-w-[300px] truncate">
                    {log.error || (log.details ? JSON.stringify(log.details) : '-')}
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
