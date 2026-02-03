import { useState } from 'react'
import {
  SettingsProvider,
  useSettings,
  ExportTargetsTab,
  CDTab,
  EmailTab,
  WarehousesTab,
  AuditLogTab,
} from '../components/settings'

function SettingsContent() {
  const [activeTab, setActiveTab] = useState('targets')
  const { loading, message } = useSettings()

  const tabs = [
    { id: 'targets', label: 'Export Targets' },
    { id: 'cd', label: 'Central Dispatch' },
    { id: 'email', label: 'Email' },
    { id: 'warehouses', label: 'Warehouses' },
    { id: 'audit', label: 'Audit Log' },
  ]

  if (loading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
          <span className="ml-3 text-gray-600">Loading settings...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>

      {message && (
        <div className={'mb-6 p-4 rounded-lg ' + (message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800')}>
          {message.text}
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="flex space-x-8">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={'py-4 px-1 border-b-2 font-medium text-sm ' + (
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              )}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="card">
        <div className="card-body">
          {activeTab === 'targets' && <ExportTargetsTab />}
          {activeTab === 'cd' && <CDTab />}
          {activeTab === 'email' && <EmailTab />}
          {activeTab === 'warehouses' && <WarehousesTab />}
          {activeTab === 'audit' && <AuditLogTab />}
        </div>
      </div>
    </div>
  )
}

function Settings() {
  return (
    <SettingsProvider>
      <SettingsContent />
    </SettingsProvider>
  )
}

export default Settings
