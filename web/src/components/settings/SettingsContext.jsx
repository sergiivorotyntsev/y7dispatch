import { createContext, useContext, useState, useEffect } from 'react'
import api from '../../api'

const SettingsContext = createContext(null)

export function SettingsProvider({ children }) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState(null)
  const [settings, setSettings] = useState({})
  const [testResults, setTestResults] = useState({})

  useEffect(() => {
    loadSettings()
  }, [])

  async function loadSettings() {
    setLoading(true)
    try {
      const data = await api.getAllSettings()
      setSettings(data)
    } catch (err) {
      showMessage('error', 'Failed to load settings: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  function showMessage(type, text) {
    setMessage({ type, text })
    setTimeout(() => setMessage(null), 5000)
  }

  function updateSettings(key, value) {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  async function testConnection(integration, testFn) {
    setTesting(true)
    setTestResults(prev => ({ ...prev, [integration]: null }))
    try {
      const result = await testFn()
      setTestResults(prev => ({ ...prev, [integration]: result }))
      if (result.status === 'ok') {
        showMessage('success', integration + ' connection successful')
      } else {
        showMessage('error', result.message)
      }
      return result
    } catch (err) {
      const errorResult = { status: 'error', message: err.message }
      setTestResults(prev => ({ ...prev, [integration]: errorResult }))
      showMessage('error', err.message)
      return errorResult
    } finally {
      setTesting(false)
    }
  }

  const value = {
    loading,
    saving,
    setSaving,
    testing,
    message,
    settings,
    setSettings,
    updateSettings,
    testResults,
    showMessage,
    loadSettings,
    testConnection,
  }

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const context = useContext(SettingsContext)
  if (!context) {
    throw new Error('useSettings must be used within a SettingsProvider')
  }
  return context
}
