import { useState } from 'react'
import api from '../api'

/**
 * Tiny weather indicator for Documents table.
 * Shows a clickable weather icon that fetches alerts on demand.
 * Renders inline next to warehouse info.
 */
function WeatherIndicator({ runId, warehouseId }) {
  const [state, setState] = useState('idle') // idle | loading | clear | alerts | error
  const [alertCount, setAlertCount] = useState(0)
  const [tooltip, setTooltip] = useState('')

  if (!runId || !warehouseId) return null

  async function handleCheck(e) {
    e.stopPropagation()
    if (state === 'loading') return
    setState('loading')
    try {
      const data = await api.getRouteAlertsForRun(runId, warehouseId)
      const count = data.alerts?.length || 0
      setAlertCount(count)
      if (count > 0) {
        setState('alerts')
        const events = [...new Set(data.alerts.map(a => a.event))]
        setTooltip(events.join(', '))
      } else {
        setState('clear')
        setTooltip('No weather alerts')
      }
    } catch {
      setState('error')
      setTooltip('Could not check weather')
    }
  }

  if (state === 'idle') {
    return (
      <button
        type="button"
        onClick={handleCheck}
        className="ml-1 text-gray-300 hover:text-gray-500 transition-colors"
        title="Check route weather"
      >
        <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
        </svg>
      </button>
    )
  }

  if (state === 'loading') {
    return (
      <span className="ml-1 inline-block w-3.5 h-3.5 animate-spin border border-gray-300 border-t-primary-600 rounded-full"></span>
    )
  }

  if (state === 'alerts') {
    return (
      <span className="ml-1 text-red-500 cursor-default" title={tooltip}>
        <svg className="w-3.5 h-3.5 inline" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        <span className="text-xs text-red-600 ml-0.5">{alertCount}</span>
      </span>
    )
  }

  if (state === 'clear') {
    return (
      <span className="ml-1 text-green-500 cursor-default" title={tooltip}>
        <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      </span>
    )
  }

  // error
  return (
    <span className="ml-1 text-gray-400 cursor-default" title={tooltip}>
      <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01" />
      </svg>
    </span>
  )
}

export default WeatherIndicator
