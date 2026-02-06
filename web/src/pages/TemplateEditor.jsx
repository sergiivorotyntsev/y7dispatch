import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api'

/**
 * Template Editor - Zone-Based Extraction Configuration
 *
 * Allows users to:
 * 1. View PDF with overlaid zones
 * 2. Drag/resize zones to adjust boundaries
 * 3. See extracted text from each zone
 * 4. Test extraction with current zone settings
 */
function TemplateEditor() {
  const { templateId } = useParams()
  const navigate = useNavigate()

  // State
  const [template, setTemplate] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  // Test document for preview
  const [testDocumentId, setTestDocumentId] = useState(null)
  const [documents, setDocuments] = useState([])
  const [zonePreview, setZonePreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // Selected zone for editing
  const [selectedZone, setSelectedZone] = useState(null)

  // Zone colors
  const zoneColors = [
    { bg: 'rgba(239, 68, 68, 0.2)', border: '#ef4444' },   // red
    { bg: 'rgba(34, 197, 94, 0.2)', border: '#22c55e' },   // green
    { bg: 'rgba(59, 130, 246, 0.2)', border: '#3b82f6' },  // blue
    { bg: 'rgba(234, 179, 8, 0.2)', border: '#eab308' },   // yellow
    { bg: 'rgba(168, 85, 247, 0.2)', border: '#a855f7' },  // purple
    { bg: 'rgba(6, 182, 212, 0.2)', border: '#06b6d4' },   // cyan
  ]

  // Load template
  useEffect(() => {
    async function loadTemplate() {
      setLoading(true)
      try {
        const result = await api.getTemplate(templateId)
        setTemplate(result)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    if (templateId) {
      loadTemplate()
    }
  }, [templateId])

  // Load documents for testing
  useEffect(() => {
    async function loadDocuments() {
      try {
        const result = await api.listDocuments({ limit: 50 })
        // Filter by auction type if template is loaded
        let docs = result.items || []
        if (template?.auction_type) {
          docs = docs.filter(d =>
            d.auction_type_code === template.auction_type ||
            !d.auction_type_code
          )
        }
        setDocuments(docs)
        // Auto-select first document
        if (docs.length > 0 && !testDocumentId) {
          setTestDocumentId(docs[0].id)
        }
      } catch (err) {
        console.error('Failed to load documents:', err)
      }
    }
    loadDocuments()
  }, [template?.auction_type])

  // Load zone preview when document changes
  useEffect(() => {
    async function loadPreview() {
      if (!templateId || !testDocumentId) return
      setPreviewLoading(true)
      try {
        const result = await api.previewZones(templateId, testDocumentId)
        setZonePreview(result)
      } catch (err) {
        console.error('Failed to load zone preview:', err)
      } finally {
        setPreviewLoading(false)
      }
    }
    loadPreview()
  }, [templateId, testDocumentId])

  // Update zone coordinates
  function updateZone(zoneIndex, updates) {
    setTemplate(prev => {
      const newZones = [...prev.zones]
      newZones[zoneIndex] = { ...newZones[zoneIndex], ...updates }
      return { ...prev, zones: newZones }
    })
  }

  // Add new zone
  function addZone() {
    const newZone = {
      name: `zone_${(template?.zones?.length || 0) + 1}`,
      x0: 25,
      y0: 25,
      x1: 75,
      y1: 50,
      fields: [],
      description: 'New zone',
    }
    setTemplate(prev => ({
      ...prev,
      zones: [...(prev.zones || []), newZone],
    }))
  }

  // Remove zone
  function removeZone(zoneIndex) {
    if (!confirm('Delete this zone?')) return
    setTemplate(prev => ({
      ...prev,
      zones: prev.zones.filter((_, i) => i !== zoneIndex),
    }))
    setSelectedZone(null)
  }

  // Add field to zone
  function addFieldToZone(zoneIndex) {
    const key = prompt('Field key (e.g., pickup_city):')
    if (!key) return

    setTemplate(prev => {
      const newZones = [...prev.zones]
      newZones[zoneIndex] = {
        ...newZones[zoneIndex],
        fields: [
          ...(newZones[zoneIndex].fields || []),
          { key, field_type: 'text', required: false },
        ],
      }
      return { ...prev, zones: newZones }
    })
  }

  // Remove field from zone
  function removeFieldFromZone(zoneIndex, fieldIndex) {
    setTemplate(prev => {
      const newZones = [...prev.zones]
      newZones[zoneIndex] = {
        ...newZones[zoneIndex],
        fields: newZones[zoneIndex].fields.filter((_, i) => i !== fieldIndex),
      }
      return { ...prev, zones: newZones }
    })
  }

  // Save template
  async function handleSave() {
    setSaving(true)
    try {
      await api.updateTemplate(templateId, template)
      alert('Template saved!')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  // Test extraction
  async function handleTestExtraction() {
    if (!testDocumentId) {
      alert('Select a document first')
      return
    }
    try {
      const result = await api.extractWithZones({
        document_id: testDocumentId,
        template_id: templateId,
      })
      alert(`Extracted ${Object.keys(result.fields).length} fields\nConfidence: ${(result.confidence * 100).toFixed(0)}%\n\n${JSON.stringify(result.fields, null, 2)}`)
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        <span className="ml-3">Loading template...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          Error: {error}
        </div>
      </div>
    )
  }

  if (!template) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          Template not found
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Template Editor</h1>
          <p className="text-sm text-gray-500">
            {template.name} ({template.auction_type})
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => navigate('/templates')}
            className="btn btn-secondary"
          >
            Back
          </button>
          <button
            onClick={handleTestExtraction}
            disabled={!testDocumentId}
            className="btn btn-secondary"
          >
            Test Extraction
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn btn-primary"
          >
            {saving ? 'Saving...' : 'Save Template'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Left: Zone List */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Zones</h2>
            <button
              onClick={addZone}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              + Add Zone
            </button>
          </div>

          <div className="space-y-3">
            {template.zones?.map((zone, i) => (
              <div
                key={i}
                className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedZone === i
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
                onClick={() => setSelectedZone(i)}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div
                    className="w-4 h-4 rounded"
                    style={{ backgroundColor: zoneColors[i % zoneColors.length].border }}
                  />
                  <span className="font-medium">{zone.name}</span>
                </div>
                <div className="text-xs text-gray-500">
                  ({zone.x0.toFixed(0)}%, {zone.y0.toFixed(0)}%) -
                  ({zone.x1.toFixed(0)}%, {zone.y1.toFixed(0)}%)
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {zone.fields?.length || 0} fields
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Center: PDF Preview with Zones */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Preview</h2>
            <select
              value={testDocumentId || ''}
              onChange={(e) => setTestDocumentId(e.target.value ? parseInt(e.target.value) : null)}
              className="form-select text-sm"
            >
              <option value="">Select document...</option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.filename}
                </option>
              ))}
            </select>
          </div>

          {testDocumentId ? (
            <div className="relative border rounded-lg overflow-hidden bg-gray-100">
              {/* PDF as background */}
              <iframe
                src={api.getDocumentFileUrl(testDocumentId)}
                className="w-full h-[600px]"
                title="PDF Preview"
              />

              {/* Zone overlays */}
              <div className="absolute inset-0 pointer-events-none">
                {template.zones?.map((zone, i) => (
                  <div
                    key={i}
                    className="absolute border-2 transition-colors"
                    style={{
                      left: `${zone.x0}%`,
                      top: `${zone.y0}%`,
                      width: `${zone.x1 - zone.x0}%`,
                      height: `${zone.y1 - zone.y0}%`,
                      backgroundColor: zoneColors[i % zoneColors.length].bg,
                      borderColor: zoneColors[i % zoneColors.length].border,
                    }}
                  >
                    <span
                      className="absolute -top-5 left-0 text-xs font-medium px-1 rounded"
                      style={{
                        backgroundColor: zoneColors[i % zoneColors.length].border,
                        color: 'white',
                      }}
                    >
                      {zone.name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="h-[600px] flex items-center justify-center text-gray-400 border rounded-lg">
              Select a document to preview zones
            </div>
          )}
        </div>

        {/* Right: Zone Editor */}
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-lg font-semibold mb-4">
            {selectedZone !== null ? `Edit: ${template.zones[selectedZone]?.name}` : 'Select a zone'}
          </h2>

          {selectedZone !== null && template.zones[selectedZone] && (
            <div className="space-y-4">
              {/* Zone name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Zone Name
                </label>
                <input
                  type="text"
                  value={template.zones[selectedZone].name}
                  onChange={(e) => updateZone(selectedZone, { name: e.target.value })}
                  className="form-input w-full"
                />
              </div>

              {/* Coordinates */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Left (x0) %
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={template.zones[selectedZone].x0}
                    onChange={(e) => updateZone(selectedZone, { x0: parseFloat(e.target.value) || 0 })}
                    className="form-input w-full"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Top (y0) %
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={template.zones[selectedZone].y0}
                    onChange={(e) => updateZone(selectedZone, { y0: parseFloat(e.target.value) || 0 })}
                    className="form-input w-full"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Right (x1) %
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={template.zones[selectedZone].x1}
                    onChange={(e) => updateZone(selectedZone, { x1: parseFloat(e.target.value) || 0 })}
                    className="form-input w-full"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Bottom (y1) %
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={template.zones[selectedZone].y1}
                    onChange={(e) => updateZone(selectedZone, { y1: parseFloat(e.target.value) || 0 })}
                    className="form-input w-full"
                  />
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={template.zones[selectedZone].description || ''}
                  onChange={(e) => updateZone(selectedZone, { description: e.target.value })}
                  className="form-input w-full"
                  placeholder="What data is in this zone?"
                />
              </div>

              {/* Fields */}
              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-sm font-medium text-gray-700">
                    Fields to Extract
                  </label>
                  <button
                    onClick={() => addFieldToZone(selectedZone)}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    + Add Field
                  </button>
                </div>
                <div className="space-y-2">
                  {template.zones[selectedZone].fields?.map((field, fi) => (
                    <div
                      key={fi}
                      className="flex items-center justify-between p-2 bg-gray-50 rounded"
                    >
                      <div>
                        <span className="font-mono text-sm">{field.key}</span>
                        {field.required && (
                          <span className="ml-2 text-xs text-red-500">*required</span>
                        )}
                      </div>
                      <button
                        onClick={() => removeFieldFromZone(selectedZone, fi)}
                        className="text-red-500 hover:text-red-700 text-sm"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                  {(!template.zones[selectedZone].fields || template.zones[selectedZone].fields.length === 0) && (
                    <p className="text-sm text-gray-400">No fields defined</p>
                  )}
                </div>
              </div>

              {/* Extracted Text Preview */}
              {zonePreview && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Extracted Text
                  </label>
                  <pre className="p-3 bg-gray-100 rounded text-xs overflow-auto max-h-40 whitespace-pre-wrap">
                    {zonePreview.zones?.find(z => z.name === template.zones[selectedZone].name)?.text || 'No text extracted'}
                  </pre>
                </div>
              )}

              {/* Delete Zone */}
              <button
                onClick={() => removeZone(selectedZone)}
                className="w-full py-2 text-red-600 border border-red-200 rounded hover:bg-red-50"
              >
                Delete Zone
              </button>
            </div>
          )}

          {selectedZone === null && (
            <div className="text-center text-gray-400 py-8">
              Click a zone to edit its properties
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default TemplateEditor
