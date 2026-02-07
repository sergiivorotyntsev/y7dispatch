/**
 * FieldsTab - Field Taxonomy Configuration UI
 *
 * Displays field configuration organized by:
 * - Category: CD_REQUIRED, CD_OPTIONAL, INTERNAL
 * - Source: EXTRACTED, CONSTANT, WAREHOUSE_REF, USER_INPUT, COMPUTED
 *
 * Part of Option C implementation for extraction pipeline refactoring.
 */
import { useState, useEffect } from 'react'
import api from '../../api'

// Category display config
const CATEGORIES = {
  cd_required: {
    label: 'CD Required',
    description: 'Fields required for Central Dispatch API submission',
    color: 'red',
    bgClass: 'bg-red-50',
    borderClass: 'border-red-200',
    textClass: 'text-red-700',
    badgeClass: 'bg-red-100 text-red-800',
  },
  cd_optional: {
    label: 'CD Optional',
    description: 'Optional fields that enhance CD listing quality',
    color: 'blue',
    bgClass: 'bg-blue-50',
    borderClass: 'border-blue-200',
    textClass: 'text-blue-700',
    badgeClass: 'bg-blue-100 text-blue-800',
  },
  internal: {
    label: 'Internal Only',
    description: 'Fields for internal tracking, not sent to CD API',
    color: 'gray',
    bgClass: 'bg-gray-50',
    borderClass: 'border-gray-200',
    textClass: 'text-gray-700',
    badgeClass: 'bg-gray-100 text-gray-800',
  },
}

// Source type display config
const SOURCES = {
  extracted: {
    label: 'Extracted',
    description: 'Value extracted from document (PDF/image)',
    icon: '📄',
    bgClass: 'bg-green-50',
    textClass: 'text-green-700',
  },
  constant: {
    label: 'Constant',
    description: 'Static default value',
    icon: '🔒',
    bgClass: 'bg-purple-50',
    textClass: 'text-purple-700',
  },
  warehouse_ref: {
    label: 'Warehouse',
    description: 'Value from warehouse reference data',
    icon: '🏭',
    bgClass: 'bg-orange-50',
    textClass: 'text-orange-700',
  },
  user_input: {
    label: 'User Input',
    description: 'Value entered manually by user',
    icon: '✏️',
    bgClass: 'bg-cyan-50',
    textClass: 'text-cyan-700',
  },
  computed: {
    label: 'Computed',
    description: 'Value computed from other fields',
    icon: '⚙️',
    bgClass: 'bg-yellow-50',
    textClass: 'text-yellow-700',
  },
}

function FieldCard({ field, onEdit, expanded, onToggle, pendingChanges = {} }) {
  // Apply pending changes to field values for display
  const pending = pendingChanges[field.key] || {}
  const currentSourceType = pending.source_type ?? field.source_type
  const currentDefaultValue = pending.default_value ?? field.default_value
  const currentRequired = pending.required ?? field.required
  const currentEditable = pending.editable_in_review ?? field.editable_in_review

  const source = SOURCES[currentSourceType] || SOURCES.extracted
  const category = CATEGORIES[field.category] || CATEGORIES.cd_optional
  const hasChanges = Object.keys(pending).length > 0

  return (
    <div className={`rounded border ${source.bgClass} border-gray-200 ${hasChanges ? 'ring-2 ring-orange-400' : ''}`}>
      <div
        className="p-3 cursor-pointer hover:bg-opacity-80"
        onClick={() => onToggle && onToggle(field.key)}
      >
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="text-lg">{source.icon}</span>
              <span className="font-medium text-sm">{field.label}</span>
              {hasChanges && (
                <span className="text-xs px-1.5 py-0.5 bg-orange-100 text-orange-700 rounded">Modified</span>
              )}
              {currentRequired && (
                <span className="text-xs px-1.5 py-0.5 bg-red-100 text-red-700 rounded">Required</span>
              )}
              {field.export_only && (
                <span className="text-xs px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded">Export Only</span>
              )}
            </div>
            <div className="mt-1 text-xs text-gray-500">
              <code className="bg-gray-100 px-1 rounded">{field.key}</code>
              {field.cd_api_key && (
                <span className="ml-2 text-gray-400">→ {field.cd_api_key}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded ${category.badgeClass}`}>
              {category.label}
            </span>
            <svg
              className={`w-4 h-4 text-gray-400 transform transition-transform ${expanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      </div>

      {/* Expanded Configuration */}
      {expanded && (
        <div className="p-3 pt-0 border-t border-gray-200 bg-white bg-opacity-50">
          <div className="grid grid-cols-2 gap-4 mt-3">
            {/* Source Type */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Source Type
              </label>
              <select
                value={currentSourceType}
                onChange={(e) => onEdit && onEdit(field.key, { source_type: e.target.value })}
                className="form-select form-select-sm text-xs w-full"
              >
                {Object.entries(SOURCES).map(([key, config]) => (
                  <option key={key} value={key}>{config.icon} {config.label}</option>
                ))}
                <option value="market_api">📊 Market API</option>
              </select>
            </div>

            {/* Default Value - show input when source is constant */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                {currentSourceType === 'constant' ? 'Constant Value' : 'Default Value'}
              </label>
              {field.options?.length > 0 ? (
                <select
                  value={currentDefaultValue || ''}
                  onChange={(e) => onEdit && onEdit(field.key, { default_value: e.target.value })}
                  className="form-select form-select-sm text-xs w-full"
                >
                  <option value="">— None —</option>
                  {field.options.map(opt => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.field_type === 'number' ? 'number' : 'text'}
                  value={currentDefaultValue || ''}
                  onChange={(e) => onEdit && onEdit(field.key, { default_value: e.target.value })}
                  className={`form-input form-input-sm text-xs w-full ${currentSourceType === 'constant' ? 'border-purple-400 bg-purple-50' : ''}`}
                  placeholder={currentSourceType === 'constant' ? 'Enter constant value...' : 'Enter default...'}
                />
              )}
            </div>
          </div>

          {/* Toggles */}
          <div className="flex items-center gap-6 mt-3">
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={currentEditable !== false}
                onChange={(e) => onEdit && onEdit(field.key, { editable_in_review: e.target.checked })}
                className="form-checkbox h-3.5 w-3.5"
              />
              <span className="text-gray-700">Editable in Review</span>
            </label>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={currentRequired || false}
                onChange={(e) => onEdit && onEdit(field.key, { required: e.target.checked })}
                className="form-checkbox h-3.5 w-3.5"
              />
              <span className="text-gray-700">Required for Export</span>
            </label>
          </div>

          {/* Extraction Hint */}
          {field.extraction_hint && (
            <div className="mt-3 text-xs text-gray-600 italic bg-gray-100 p-2 rounded">
              Extraction hint: {field.extraction_hint}
            </div>
          )}

          {/* Help Text */}
          {field.help_text && (
            <div className="mt-2 text-xs text-gray-500">
              {field.help_text}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CategorySection({ category, fields, expandedField, onToggleField, onEditField, pendingChanges = {} }) {
  const config = CATEGORIES[category] || CATEGORIES.cd_optional
  const [sectionExpanded, setSectionExpanded] = useState(true)

  // Count modified fields in this section
  const modifiedCount = fields.filter(f => pendingChanges[f.key]).length

  return (
    <div className={`rounded-lg border ${config.borderClass} ${config.bgClass} mb-4`}>
      <button
        onClick={() => setSectionExpanded(!sectionExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between text-left"
      >
        <div>
          <h3 className={`font-semibold ${config.textClass}`}>
            {config.label}
            <span className="ml-2 text-sm font-normal text-gray-500">
              ({fields.length} fields)
            </span>
            {modifiedCount > 0 && (
              <span className="ml-2 text-sm font-normal text-orange-600">
                ({modifiedCount} modified)
              </span>
            )}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">{config.description}</p>
        </div>
        <svg
          className={`w-5 h-5 text-gray-400 transform transition-transform ${sectionExpanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {sectionExpanded && (
        <div className="px-4 pb-4 grid gap-2">
          {fields.map(field => (
            <FieldCard
              key={field.key}
              field={field}
              expanded={expandedField === field.key}
              onToggle={onToggleField}
              onEdit={onEditField}
              pendingChanges={pendingChanges}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SourceSummary({ taxonomy }) {
  if (!taxonomy?.by_source) return null

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Fields by Source Type</h3>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Object.entries(SOURCES).map(([key, config]) => {
          const count = taxonomy.by_source[key]?.length || 0
          return (
            <div key={key} className={`p-3 rounded-lg ${config.bgClass} text-center`}>
              <div className="text-2xl mb-1">{config.icon}</div>
              <div className={`text-lg font-semibold ${config.textClass}`}>{count}</div>
              <div className="text-xs text-gray-600">{config.label}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ModeSummary({ taxonomy }) {
  const [selectedMode, setSelectedMode] = useState('training')
  const [modeFields, setModeFields] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadModeFields(selectedMode)
  }, [selectedMode])

  async function loadModeFields(mode) {
    setLoading(true)
    try {
      const data = await api.getFieldsForMode(mode)
      setModeFields(data)
    } catch (err) {
      console.error('Failed to load mode fields:', err)
    } finally {
      setLoading(false)
    }
  }

  const modes = [
    { id: 'training', label: 'Training', description: 'Extraction review (no export-only fields)' },
    { id: 'review', label: 'Review', description: 'All visible fields' },
    { id: 'export', label: 'Export', description: 'All CD API fields' },
  ]

  return (
    <div className="mb-6 p-4 bg-gray-50 rounded-lg">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Fields by Pipeline Mode</h3>
      <div className="flex gap-2 mb-4">
        {modes.map(mode => (
          <button
            key={mode.id}
            onClick={() => setSelectedMode(mode.id)}
            className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedMode === mode.id
                ? 'bg-primary-600 text-white'
                : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-200'
            }`}
          >
            {mode.label}
            {modeFields?.mode === mode.id && (
              <span className="ml-1.5 text-xs opacity-75">({modeFields.count})</span>
            )}
          </button>
        ))}
      </div>
      {loading ? (
        <div className="text-sm text-gray-500">Loading...</div>
      ) : modeFields ? (
        <div className="text-sm text-gray-600">
          <span className="font-medium">{modeFields.count}</span> fields shown in{' '}
          <span className="font-medium">{selectedMode}</span> mode
        </div>
      ) : null}
    </div>
  )
}

function FieldsTab() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [taxonomy, setTaxonomy] = useState(null)
  const [schema, setSchema] = useState(null)
  const [view, setView] = useState('category') // 'category' or 'source'
  const [expandedField, setExpandedField] = useState(null)
  const [pendingChanges, setPendingChanges] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)

  useEffect(() => {
    loadData()
  }, [])

  // Handle field expansion toggle
  function handleToggleField(fieldKey) {
    setExpandedField(prev => prev === fieldKey ? null : fieldKey)
  }

  // Handle field edit (stores changes locally until save)
  function handleEditField(fieldKey, updates) {
    setPendingChanges(prev => ({
      ...prev,
      [fieldKey]: { ...(prev[fieldKey] || {}), ...updates }
    }))
  }

  // Save pending changes to backend
  async function handleSaveChanges() {
    if (Object.keys(pendingChanges).length === 0) return

    setSaving(true)
    setSaveMessage(null)
    try {
      // Call the actual API to persist field config changes
      const result = await api.updateFieldConfigs(pendingChanges)

      setSaveMessage({
        type: 'success',
        text: `Field configuration saved: ${result.updated || 0} updated, ${result.created || 0} created`
      })
      setPendingChanges({})

      // Reload to reflect saved changes
      loadData()
    } catch (err) {
      setSaveMessage({ type: 'error', text: `Failed to save: ${err.message}` })
    } finally {
      setSaving(false)
    }
  }

  async function loadData() {
    setLoading(true)
    setError(null)
    try {
      const [taxonomyData, schemaData, configsData] = await Promise.all([
        api.getFieldTaxonomy(),
        api.getFieldSchema(),
        api.getFieldConfigs().catch(() => ({ configs: [] })),
      ])

      // Apply saved configs to schema fields
      const savedConfigs = {}
      for (const cfg of (configsData.configs || [])) {
        savedConfigs[cfg.field_key] = cfg
      }

      // Merge saved configs into schema
      if (schemaData?.sections) {
        Object.values(schemaData.sections).forEach(section => {
          section.fields.forEach(field => {
            const saved = savedConfigs[field.key]
            if (saved) {
              field.source_type = saved.source_type || field.source_type
              field.default_value = saved.default_value ?? field.default_value
              field.required = saved.is_required ?? field.required
              field.editable_in_review = saved.is_editable ?? field.editable_in_review
            }
          })
        })
      }

      setTaxonomy(taxonomyData)
      setSchema(schemaData)
    } catch (err) {
      setError(err.message)
      console.error('Failed to load field taxonomy:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        <span className="ml-3 text-gray-600">Loading field configuration...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
        <h3 className="font-medium text-red-800">Failed to load field configuration</h3>
        <p className="text-sm text-red-600 mt-1">{error}</p>
        <button
          onClick={loadData}
          className="mt-3 px-3 py-1.5 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200"
        >
          Retry
        </button>
      </div>
    )
  }

  // Organize fields by category from schema
  const fieldsByCategory = {}
  if (schema?.sections) {
    Object.values(schema.sections).forEach(section => {
      section.fields.forEach(field => {
        const cat = field.category || 'cd_optional'
        if (!fieldsByCategory[cat]) fieldsByCategory[cat] = []
        fieldsByCategory[cat].push(field)
      })
    })
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-lg font-semibold text-gray-900">Field Configuration</h2>
        <p className="text-sm text-gray-500 mt-1">
          Configure which fields are extracted, their sources, and validation rules.
        </p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="p-4 bg-red-50 rounded-lg text-center">
          <div className="text-2xl font-bold text-red-700">{taxonomy?.cd_required?.count || 0}</div>
          <div className="text-sm text-red-600">CD Required</div>
        </div>
        <div className="p-4 bg-blue-50 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-700">{taxonomy?.cd_optional?.count || 0}</div>
          <div className="text-sm text-blue-600">CD Optional</div>
        </div>
        <div className="p-4 bg-gray-50 rounded-lg text-center">
          <div className="text-2xl font-bold text-gray-700">{taxonomy?.internal?.count || 0}</div>
          <div className="text-sm text-gray-600">Internal Only</div>
        </div>
      </div>

      {/* Source Type Summary */}
      <SourceSummary taxonomy={taxonomy} />

      {/* Mode Summary */}
      <ModeSummary taxonomy={taxonomy} />

      {/* Save Message */}
      {saveMessage && (
        <div className={`mb-4 p-3 rounded-lg ${
          saveMessage.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
        }`}>
          {saveMessage.text}
        </div>
      )}

      {/* View Toggle and Save */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-gray-700">View by:</span>
          <div className="flex gap-2">
            <button
              onClick={() => setView('category')}
              className={`px-3 py-1.5 text-sm rounded ${
                view === 'category'
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Category
            </button>
            <button
              onClick={() => setView('source')}
              className={`px-3 py-1.5 text-sm rounded ${
                view === 'source'
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Source Type
            </button>
          </div>
        </div>
        {Object.keys(pendingChanges).length > 0 && (
          <button
            onClick={handleSaveChanges}
            disabled={saving}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2"
          >
            {saving ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                Saving...
              </>
            ) : (
              <>Save Changes ({Object.keys(pendingChanges).length})</>
            )}
          </button>
        )}
      </div>

      {/* Field Lists */}
      {view === 'category' ? (
        <div>
          {['cd_required', 'cd_optional', 'internal'].map(category => (
            <CategorySection
              key={category}
              category={category}
              fields={fieldsByCategory[category] || []}
              expandedField={expandedField}
              onToggleField={handleToggleField}
              onEditField={handleEditField}
              pendingChanges={pendingChanges}
            />
          ))}
        </div>
      ) : (
        <div className="grid gap-4">
          {Object.entries(SOURCES).map(([sourceType, config]) => {
            const fields = taxonomy?.by_source?.[sourceType] || []
            const fieldDetails = fields.map(key => {
              // Find field in schema
              for (const section of Object.values(schema?.sections || {})) {
                const field = section.fields.find(f => f.key === key)
                if (field) return field
              }
              return { key, label: key }
            })

            return (
              <div key={sourceType} className={`p-4 rounded-lg ${config.bgClass}`}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xl">{config.icon}</span>
                  <h3 className={`font-semibold ${config.textClass}`}>
                    {config.label}
                    <span className="ml-2 text-sm font-normal text-gray-500">
                      ({fields.length} fields)
                    </span>
                  </h3>
                </div>
                <p className="text-xs text-gray-600 mb-3">{config.description}</p>
                <div className="flex flex-wrap gap-2">
                  {fields.map(key => (
                    <span
                      key={key}
                      className="px-2 py-1 bg-white bg-opacity-70 text-xs rounded border border-gray-200"
                    >
                      {key}
                    </span>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default FieldsTab
