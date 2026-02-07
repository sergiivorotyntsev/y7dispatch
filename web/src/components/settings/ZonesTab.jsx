/**
 * ZonesTab - Zone-Based Extraction Template Management
 *
 * Allows users to:
 * - View and edit extraction zones for each auction type
 * - Adjust zone boundaries (x0, y0, x1, y1 as percentages)
 * - Map fields to specific zones
 * - Preview zone extraction on sample documents
 * - Visual zone editing with document background (drag & resize)
 */
import { useState, useEffect } from 'react'
import api from '../../api'
import VisualZoneEditor from './VisualZoneEditor'

const AUCTION_TYPES = ['COPART', 'IAA', 'MANHEIM']

function ZoneEditor({ zone, onChange, onDelete }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border rounded-lg bg-white mb-3">
      <div
        className="p-3 flex items-center justify-between cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-6 h-6 rounded border-2 flex items-center justify-center text-xs font-bold"
            style={{
              borderColor: getZoneColor(zone.name),
              color: getZoneColor(zone.name),
            }}
          >
            {zone.name.charAt(0).toUpperCase()}
          </div>
          <div>
            <div className="font-medium text-sm">{zone.name}</div>
            <div className="text-xs text-gray-500">
              {zone.fields?.length || 0} fields • {Math.round((zone.x1 - zone.x0) * (zone.y1 - zone.y0) / 100)}% area
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 font-mono">
            ({zone.x0.toFixed(0)}%, {zone.y0.toFixed(0)}%) → ({zone.x1.toFixed(0)}%, {zone.y1.toFixed(0)}%)
          </span>
          <svg
            className={`w-5 h-5 text-gray-400 transform transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>

      {expanded && (
        <div className="p-4 border-t bg-gray-50">
          {/* Zone Coordinates */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-700 mb-2">
              Zone Boundaries (% of page)
            </label>
            <div className="grid grid-cols-4 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Left (X0)</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={zone.x0}
                  onChange={(e) => onChange({ ...zone, x0: parseFloat(e.target.value) || 0 })}
                  className="form-input form-input-sm text-xs w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Top (Y0)</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={zone.y0}
                  onChange={(e) => onChange({ ...zone, y0: parseFloat(e.target.value) || 0 })}
                  className="form-input form-input-sm text-xs w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Right (X1)</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={zone.x1}
                  onChange={(e) => onChange({ ...zone, x1: parseFloat(e.target.value) || 0 })}
                  className="form-input form-input-sm text-xs w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Bottom (Y1)</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={zone.y1}
                  onChange={(e) => onChange({ ...zone, y1: parseFloat(e.target.value) || 0 })}
                  className="form-input form-input-sm text-xs w-full"
                />
              </div>
            </div>
          </div>

          {/* Zone Description */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
            <input
              type="text"
              value={zone.description || ''}
              onChange={(e) => onChange({ ...zone, description: e.target.value })}
              className="form-input form-input-sm text-xs w-full"
              placeholder="Describe what this zone contains..."
            />
          </div>

          {/* Fields in Zone */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-700 mb-2">
              Fields ({zone.fields?.length || 0})
            </label>
            <div className="space-y-2">
              {(zone.fields || []).map((field, idx) => (
                <div key={idx} className="flex items-center gap-2 p-2 bg-white rounded border">
                  <input
                    type="text"
                    value={field.key}
                    onChange={(e) => {
                      const newFields = [...zone.fields]
                      newFields[idx] = { ...field, key: e.target.value }
                      onChange({ ...zone, fields: newFields })
                    }}
                    className="form-input form-input-sm text-xs flex-1"
                    placeholder="Field key"
                  />
                  <select
                    value={field.field_type || 'text'}
                    onChange={(e) => {
                      const newFields = [...zone.fields]
                      newFields[idx] = { ...field, field_type: e.target.value }
                      onChange({ ...zone, fields: newFields })
                    }}
                    className="form-select form-select-sm text-xs"
                  >
                    <option value="text">Text</option>
                    <option value="number">Number</option>
                    <option value="date">Date</option>
                    <option value="vin">VIN</option>
                    <option value="address">Address</option>
                    <option value="currency">Currency</option>
                  </select>
                  <input
                    type="text"
                    value={field.pattern || ''}
                    onChange={(e) => {
                      const newFields = [...zone.fields]
                      newFields[idx] = { ...field, pattern: e.target.value }
                      onChange({ ...zone, fields: newFields })
                    }}
                    className="form-input form-input-sm text-xs w-32"
                    placeholder="Regex pattern"
                  />
                  <button
                    onClick={() => {
                      const newFields = zone.fields.filter((_, i) => i !== idx)
                      onChange({ ...zone, fields: newFields })
                    }}
                    className="text-red-500 hover:text-red-700 p-1"
                    title="Remove field"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
              <button
                onClick={() => {
                  const newFields = [...(zone.fields || []), { key: '', field_type: 'text', pattern: '' }]
                  onChange({ ...zone, fields: newFields })
                }}
                className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Field
              </button>
            </div>
          </div>

          {/* Delete Zone */}
          <div className="flex justify-end">
            <button
              onClick={onDelete}
              className="text-xs text-red-600 hover:text-red-800 flex items-center gap-1"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Delete Zone
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function ZoneVisualizer({ zones, selectedZone, onSelectZone }) {
  return (
    <div className="relative bg-gray-200 rounded-lg overflow-hidden" style={{ paddingBottom: '141.4%' /* A4 ratio */ }}>
      <div className="absolute inset-0 p-2">
        <div className="relative w-full h-full bg-white shadow-inner">
          {/* Document page representation */}
          <div className="absolute inset-2 border-2 border-dashed border-gray-300">
            {zones.map((zone, idx) => (
              <div
                key={idx}
                className={`absolute border-2 cursor-pointer transition-all ${
                  selectedZone === zone.name
                    ? 'border-blue-500 bg-blue-100 bg-opacity-50'
                    : 'border-gray-400 bg-gray-100 bg-opacity-30 hover:bg-opacity-50'
                }`}
                style={{
                  left: `${zone.x0}%`,
                  top: `${zone.y0}%`,
                  width: `${zone.x1 - zone.x0}%`,
                  height: `${zone.y1 - zone.y0}%`,
                  borderColor: getZoneColor(zone.name),
                }}
                onClick={() => onSelectZone(zone.name)}
                title={`${zone.name}: ${zone.description || 'No description'}`}
              >
                <span
                  className="absolute top-0 left-0 px-1 text-xs font-bold text-white"
                  style={{ backgroundColor: getZoneColor(zone.name) }}
                >
                  {zone.name}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function getZoneColor(name) {
  const colors = {
    header: '#3B82F6',
    vehicle_info: '#10B981',
    buyer_seller: '#F59E0B',
    pricing: '#EF4444',
    dates: '#8B5CF6',
    pickup: '#06B6D4',
    delivery: '#EC4899',
    footer: '#6B7280',
  }
  return colors[name.toLowerCase()] || '#6B7280'
}

function DocumentSelector({ selectedDocumentId, onSelect, auctionType }) {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploadingFile, setUploadingFile] = useState(null)

  useEffect(() => {
    loadDocuments()
  }, [auctionType])

  async function loadDocuments() {
    setLoading(true)
    try {
      // Load recent documents for this auction type
      const result = await api.listDocuments({ limit: 20 })
      setDocuments(result.items || [])
    } catch (err) {
      console.error('Failed to load documents:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadingFile(file.name)
    try {
      const result = await api.uploadDocument(file, null, 'train')
      await loadDocuments()
      if (result.id) {
        onSelect(result.id)
      }
    } catch (err) {
      console.error('Failed to upload document:', err)
    } finally {
      setUploadingFile(null)
    }
  }

  return (
    <div className="p-3 bg-gray-50 border-b">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-gray-700">Background Document:</span>

        <select
          value={selectedDocumentId || ''}
          onChange={(e) => onSelect(e.target.value ? parseInt(e.target.value) : null)}
          className="form-select form-select-sm text-sm flex-1 max-w-md"
        >
          <option value="">Select a document...</option>
          {documents.map(doc => (
            <option key={doc.id} value={doc.id}>
              #{doc.id} - {doc.filename} ({doc.auction_type_code || 'Unknown'})
            </option>
          ))}
        </select>

        <span className="text-gray-400">or</span>

        <label className="px-3 py-1.5 text-sm bg-white border rounded cursor-pointer hover:bg-gray-50 flex items-center gap-2">
          {uploadingFile ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
              <span>Uploading...</span>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              <span>Upload PDF</span>
            </>
          )}
          <input
            type="file"
            accept=".pdf"
            onChange={handleFileUpload}
            className="hidden"
            disabled={!!uploadingFile}
          />
        </label>

        {loading && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400"></div>}
      </div>
    </div>
  )
}

function TemplateEditor({ template, onSave, onCancel }) {
  const [editedTemplate, setEditedTemplate] = useState(template)
  const [selectedZone, setSelectedZone] = useState(null)
  const [selectedZoneIndex, setSelectedZoneIndex] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [editorMode, setEditorMode] = useState('visual') // 'visual' or 'form'
  const [selectedDocumentId, setSelectedDocumentId] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)

  function handleZoneChange(index, updatedZone) {
    const newZones = [...editedTemplate.zones]
    newZones[index] = updatedZone
    setEditedTemplate({ ...editedTemplate, zones: newZones })
  }

  function handleZonesChange(newZones) {
    setEditedTemplate({ ...editedTemplate, zones: newZones })
  }

  function handleZoneDelete(index) {
    if (!confirm('Delete this zone?')) return
    const newZones = editedTemplate.zones.filter((_, i) => i !== index)
    setEditedTemplate({ ...editedTemplate, zones: newZones })
    if (selectedZoneIndex === index) {
      setSelectedZoneIndex(null)
    }
  }

  function handleAddZone() {
    const newZone = {
      name: `zone_${editedTemplate.zones.length + 1}`,
      x0: 10,
      y0: 10,
      x1: 50,
      y1: 30,
      fields: [],
      description: '',
    }
    setEditedTemplate({ ...editedTemplate, zones: [...editedTemplate.zones, newZone] })
    setSelectedZoneIndex(editedTemplate.zones.length)
  }

  function handleZoneSelect(index) {
    setSelectedZoneIndex(index)
    if (index !== null && editedTemplate.zones[index]) {
      setSelectedZone(editedTemplate.zones[index].name)
    } else {
      setSelectedZone(null)
    }
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await onSave(editedTemplate)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const selectedZoneData = selectedZoneIndex !== null ? editedTemplate.zones[selectedZoneIndex] : null

  return (
    <div className="bg-white rounded-lg shadow flex flex-col" style={{ height: 'calc(100vh - 180px)' }}>
      {/* Header */}
      <div className="p-4 border-b flex items-center justify-between flex-shrink-0">
        <div>
          <h3 className="font-semibold text-lg">{editedTemplate.name}</h3>
          <p className="text-sm text-gray-500">
            {editedTemplate.auction_type} • Version {editedTemplate.version}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Editor Mode Toggle */}
          <div className="flex rounded-lg border overflow-hidden">
            <button
              onClick={() => setEditorMode('visual')}
              className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${
                editorMode === 'visual'
                  ? 'bg-blue-50 text-blue-700 border-r'
                  : 'bg-white text-gray-600 hover:bg-gray-50 border-r'
              }`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              Visual
            </button>
            <button
              onClick={() => setEditorMode('form')}
              className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${
                editorMode === 'form'
                  ? 'bg-blue-50 text-blue-700'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Form
            </button>
          </div>

          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Template'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm flex-shrink-0">
          {error}
        </div>
      )}

      {/* Visual Editor Mode */}
      {editorMode === 'visual' && (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Document Selector */}
          <DocumentSelector
            selectedDocumentId={selectedDocumentId}
            onSelect={setSelectedDocumentId}
            auctionType={editedTemplate.auction_type}
          />

          <div className="flex-1 flex overflow-hidden">
            {/* Visual Zone Editor */}
            <div className="flex-1 overflow-hidden border-r">
              <VisualZoneEditor
                zones={editedTemplate.zones}
                documentId={selectedDocumentId}
                pageNum={currentPage}
                onChange={handleZonesChange}
                onZoneSelect={handleZoneSelect}
                selectedZoneIndex={selectedZoneIndex}
              />
            </div>

            {/* Zone Properties Sidebar */}
            <div className="w-80 flex-shrink-0 overflow-y-auto bg-gray-50">
              <div className="p-3 border-b bg-white sticky top-0 z-10">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium text-gray-700">
                    Zones ({editedTemplate.zones.length})
                  </h4>
                  <button
                    onClick={handleAddZone}
                    className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    Add Zone
                  </button>
                </div>

                {/* Page selector */}
                {selectedDocumentId && (
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-xs text-gray-500">Page:</span>
                    <button
                      onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                      className="p-1 rounded hover:bg-gray-200"
                      disabled={currentPage <= 1}
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                      </svg>
                    </button>
                    <span className="text-xs font-mono">{currentPage}</span>
                    <button
                      onClick={() => setCurrentPage(currentPage + 1)}
                      className="p-1 rounded hover:bg-gray-200"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>

              {/* Zone List */}
              <div className="p-3 space-y-2">
                {editedTemplate.zones.map((zone, idx) => (
                  <div
                    key={idx}
                    className={`p-2 rounded border cursor-pointer transition-colors ${
                      selectedZoneIndex === idx
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 bg-white hover:border-gray-300'
                    }`}
                    onClick={() => handleZoneSelect(idx)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div
                          className="w-3 h-3 rounded"
                          style={{ backgroundColor: getZoneColor(zone.name) }}
                        />
                        <span className="text-sm font-medium">{zone.name}</span>
                      </div>
                      <span className="text-xs text-gray-400">
                        {zone.fields?.length || 0} fields
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 mt-1 font-mono">
                      ({zone.x0.toFixed(1)}%, {zone.y0.toFixed(1)}%) - ({zone.x1.toFixed(1)}%, {zone.y1.toFixed(1)}%)
                    </div>
                  </div>
                ))}
              </div>

              {/* Selected Zone Editor */}
              {selectedZoneData && (
                <div className="p-3 border-t bg-white">
                  <h5 className="text-sm font-medium text-gray-700 mb-3">Edit Zone: {selectedZoneData.name}</h5>

                  {/* Zone Name */}
                  <div className="mb-3">
                    <label className="block text-xs text-gray-500 mb-1">Name</label>
                    <input
                      type="text"
                      value={selectedZoneData.name}
                      onChange={(e) => handleZoneChange(selectedZoneIndex, { ...selectedZoneData, name: e.target.value })}
                      className="form-input form-input-sm text-sm w-full"
                    />
                  </div>

                  {/* Zone Coordinates */}
                  <div className="mb-3">
                    <label className="block text-xs text-gray-500 mb-1">Coordinates (%)</label>
                    <div className="grid grid-cols-4 gap-1">
                      <input
                        type="number"
                        value={selectedZoneData.x0}
                        onChange={(e) => handleZoneChange(selectedZoneIndex, { ...selectedZoneData, x0: parseFloat(e.target.value) || 0 })}
                        className="form-input form-input-sm text-xs"
                        placeholder="X0"
                      />
                      <input
                        type="number"
                        value={selectedZoneData.y0}
                        onChange={(e) => handleZoneChange(selectedZoneIndex, { ...selectedZoneData, y0: parseFloat(e.target.value) || 0 })}
                        className="form-input form-input-sm text-xs"
                        placeholder="Y0"
                      />
                      <input
                        type="number"
                        value={selectedZoneData.x1}
                        onChange={(e) => handleZoneChange(selectedZoneIndex, { ...selectedZoneData, x1: parseFloat(e.target.value) || 0 })}
                        className="form-input form-input-sm text-xs"
                        placeholder="X1"
                      />
                      <input
                        type="number"
                        value={selectedZoneData.y1}
                        onChange={(e) => handleZoneChange(selectedZoneIndex, { ...selectedZoneData, y1: parseFloat(e.target.value) || 0 })}
                        className="form-input form-input-sm text-xs"
                        placeholder="Y1"
                      />
                    </div>
                  </div>

                  {/* Description */}
                  <div className="mb-3">
                    <label className="block text-xs text-gray-500 mb-1">Description</label>
                    <input
                      type="text"
                      value={selectedZoneData.description || ''}
                      onChange={(e) => handleZoneChange(selectedZoneIndex, { ...selectedZoneData, description: e.target.value })}
                      className="form-input form-input-sm text-sm w-full"
                      placeholder="What this zone contains..."
                    />
                  </div>

                  {/* Fields */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-xs text-gray-500">Fields</label>
                      <button
                        onClick={() => {
                          const newFields = [...(selectedZoneData.fields || []), { key: '', field_type: 'text', pattern: '' }]
                          handleZoneChange(selectedZoneIndex, { ...selectedZoneData, fields: newFields })
                        }}
                        className="text-xs text-blue-600 hover:text-blue-800"
                      >
                        + Add
                      </button>
                    </div>
                    <div className="space-y-2 max-h-40 overflow-y-auto">
                      {(selectedZoneData.fields || []).map((field, fidx) => (
                        <div key={fidx} className="flex items-center gap-1 p-1.5 bg-gray-50 rounded text-xs">
                          <input
                            type="text"
                            value={field.key}
                            onChange={(e) => {
                              const newFields = [...selectedZoneData.fields]
                              newFields[fidx] = { ...field, key: e.target.value }
                              handleZoneChange(selectedZoneIndex, { ...selectedZoneData, fields: newFields })
                            }}
                            className="form-input form-input-sm text-xs flex-1"
                            placeholder="field_key"
                          />
                          <select
                            value={field.field_type || 'text'}
                            onChange={(e) => {
                              const newFields = [...selectedZoneData.fields]
                              newFields[fidx] = { ...field, field_type: e.target.value }
                              handleZoneChange(selectedZoneIndex, { ...selectedZoneData, fields: newFields })
                            }}
                            className="form-select form-select-sm text-xs w-20"
                          >
                            <option value="text">Text</option>
                            <option value="address">Address</option>
                            <option value="vin">VIN</option>
                            <option value="date">Date</option>
                            <option value="currency">Currency</option>
                          </select>
                          <button
                            onClick={() => {
                              const newFields = selectedZoneData.fields.filter((_, i) => i !== fidx)
                              handleZoneChange(selectedZoneIndex, { ...selectedZoneData, fields: newFields })
                            }}
                            className="text-red-500 hover:text-red-700 p-1"
                          >
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Delete Zone */}
                  <button
                    onClick={() => handleZoneDelete(selectedZoneIndex)}
                    className="w-full text-xs text-red-600 hover:text-red-800 hover:bg-red-50 py-2 rounded border border-red-200"
                  >
                    Delete Zone
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Form Editor Mode (original) */}
      {editorMode === 'form' && (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-3 gap-6">
            {/* Zone Visualizer */}
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">Zone Layout Preview</h4>
              <ZoneVisualizer
                zones={editedTemplate.zones}
                selectedZone={selectedZone}
                onSelectZone={setSelectedZone}
              />
              <p className="text-xs text-gray-500 mt-2">
                Click a zone to select. Zones are defined as percentage of page size.
              </p>
            </div>

            {/* Zone List */}
            <div className="col-span-2">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-medium text-gray-700">
                  Zones ({editedTemplate.zones.length})
                </h4>
                <button
                  onClick={handleAddZone}
                  className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Add Zone
                </button>
              </div>

              <div className="max-h-[500px] overflow-y-auto">
                {editedTemplate.zones.map((zone, idx) => (
                  <ZoneEditor
                    key={idx}
                    zone={zone}
                    onChange={(updated) => handleZoneChange(idx, updated)}
                    onDelete={() => handleZoneDelete(idx)}
                  />
                ))}
                {editedTemplate.zones.length === 0 && (
                  <div className="text-center py-8 text-gray-500">
                    No zones defined. Click "Add Zone" to create one.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function ZonesTab() {
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedAuctionType, setSelectedAuctionType] = useState('COPART')
  const [editingTemplate, setEditingTemplate] = useState(null)

  useEffect(() => {
    loadTemplates()
  }, [])

  async function loadTemplates() {
    setLoading(true)
    setError(null)
    try {
      const result = await api.listZoneTemplates()
      setTemplates(result.items || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSaveTemplate(template) {
    await api.updateZoneTemplate(template.template_id, template)
    await loadTemplates()
    setEditingTemplate(null)
  }

  async function handleCreateTemplate() {
    const newTemplate = {
      template_id: `${selectedAuctionType.toLowerCase()}_custom_${Date.now()}`,
      name: `${selectedAuctionType} Custom Template`,
      auction_type: selectedAuctionType,
      version: 1,
      zones: [
        { name: 'header', x0: 0, y0: 0, x1: 100, y1: 15, fields: [], description: 'Document header area' },
        { name: 'vehicle_info', x0: 0, y0: 15, x1: 50, y1: 50, fields: [], description: 'Vehicle information' },
        { name: 'pricing', x0: 50, y0: 15, x1: 100, y1: 50, fields: [], description: 'Pricing information' },
      ],
      description: 'Custom extraction template',
      is_active: true,
    }
    setEditingTemplate(newTemplate)
  }

  const filteredTemplates = templates.filter(t => t.auction_type === selectedAuctionType)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        <span className="ml-3 text-gray-600">Loading templates...</span>
      </div>
    )
  }

  if (editingTemplate) {
    return (
      <TemplateEditor
        template={editingTemplate}
        onSave={handleSaveTemplate}
        onCancel={() => setEditingTemplate(null)}
      />
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-lg font-semibold text-gray-900">Zone-Based Extraction Templates</h2>
        <p className="text-sm text-gray-500 mt-1">
          Define extraction zones for each document type. Zones specify which region of the document
          contains specific fields like VIN, price, addresses, etc.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
          <button onClick={loadTemplates} className="ml-2 underline">Retry</button>
        </div>
      )}

      {/* Auction Type Tabs */}
      <div className="flex items-center gap-2 mb-6">
        {AUCTION_TYPES.map(at => (
          <button
            key={at}
            onClick={() => setSelectedAuctionType(at)}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              selectedAuctionType === at
                ? 'bg-primary-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {at}
          </button>
        ))}
        <div className="flex-1" />
        <button
          onClick={handleCreateTemplate}
          className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Template
        </button>
      </div>

      {/* Templates List */}
      <div className="space-y-4">
        {filteredTemplates.length === 0 ? (
          <div className="text-center py-12 bg-gray-50 rounded-lg">
            <p className="text-gray-500 mb-4">No templates found for {selectedAuctionType}</p>
            <button
              onClick={handleCreateTemplate}
              className="text-primary-600 hover:text-primary-800"
            >
              Create a template
            </button>
          </div>
        ) : (
          filteredTemplates.map(template => (
            <div key={template.template_id} className="bg-white rounded-lg shadow p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">{template.name}</h3>
                    {template.is_active && (
                      <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded">Active</span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-1">
                    {template.zones?.length || 0} zones • Version {template.version}
                  </p>
                  {template.description && (
                    <p className="text-xs text-gray-400 mt-1">{template.description}</p>
                  )}
                </div>
                <button
                  onClick={() => setEditingTemplate(template)}
                  className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50"
                >
                  Edit Zones
                </button>
              </div>

              {/* Zone Summary */}
              <div className="mt-4 flex flex-wrap gap-2">
                {(template.zones || []).map((zone, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 px-2 py-1 bg-gray-100 rounded text-xs"
                  >
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: getZoneColor(zone.name) }}
                    />
                    <span className="font-medium">{zone.name}</span>
                    <span className="text-gray-400">({zone.fields?.length || 0})</span>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Help Section */}
      <div className="mt-8 p-4 bg-blue-50 rounded-lg">
        <h4 className="font-medium text-blue-800 mb-2">How Zone Extraction Works</h4>
        <ul className="text-sm text-blue-700 space-y-1">
          <li>• Zones define regions on the document (as percentage of page size)</li>
          <li>• Each zone can contain multiple fields with extraction patterns</li>
          <li>• The extractor reads text from each zone and applies field patterns</li>
          <li>• Adjust zone boundaries if fields are being extracted from wrong areas</li>
          <li>• Use specific regex patterns for better field accuracy</li>
        </ul>
      </div>
    </div>
  )
}
