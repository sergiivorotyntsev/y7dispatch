import { useState, useEffect, useRef } from 'react'
import api from '../../api'
import { ZONE_COLORS_ARRAY } from '../../constants/zones'
import PdfZoneViewer from '../PdfZoneViewer'

export default function ZoneTemplatesTab({ auctionTypes }) {
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [testDocumentId, setTestDocumentId] = useState(null)
  const [documents, setDocuments] = useState([])
  const [zonePreview, setZonePreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [testResult, setTestResult] = useState(null)

  // Zone editing state
  const [editMode, setEditMode] = useState(false)
  const [editingZones, setEditingZones] = useState([])
  const [selectedZoneIdx, setSelectedZoneIdx] = useState(null)
  const [saving, setSaving] = useState(false)
  const [dragState, setDragState] = useState(null)
  const containerRef = useRef(null)

  useEffect(() => {
    loadTemplates()
    loadDocuments()
  }, [])

  async function loadTemplates() {
    setLoading(true)
    try {
      const result = await api.listZoneTemplates()
      setTemplates(result.items || [])
    } catch (err) {
      console.error('Failed to load templates:', err)
    } finally {
      setLoading(false)
    }
  }

  async function loadDocuments() {
    try {
      const result = await api.listTrainingDocuments({ limit: 50 })
      setDocuments(result.items || [])
    } catch (err) {
      console.error('Failed to load training documents:', err)
    }
  }

  async function loadZonePreview(templateId, docId) {
    if (!templateId || !docId) return
    setPreviewLoading(true)
    try {
      const result = await api.previewZones(templateId, docId)
      setZonePreview(result)
    } catch (err) {
      console.error('Failed to preview zones:', err)
    } finally {
      setPreviewLoading(false)
    }
  }

  // Live preview with current UNSAVED zones (for edit mode)
  async function loadLivePreview() {
    if (!testDocumentId || editingZones.length === 0) return
    setPreviewLoading(true)
    try {
      // Format zones for the API
      const formattedZones = editingZones.map(zone => ({
        name: zone.name,
        x0: zone.x0,
        y0: zone.y0,
        x1: zone.x1,
        y1: zone.y1,
        description: zone.description || null,
        fields: (zone.fields || []).map(f => {
          if (typeof f === 'string') {
            return { key: f, field_type: 'text', required: false }
          }
          return {
            key: f.key || f,
            field_type: f.field_type || 'text',
            pattern: f.pattern || null,
            label: f.label || null,
            required: f.required || false,
          }
        }),
      }))
      const result = await api.livePreviewZones(testDocumentId, formattedZones)
      setZonePreview(result)
    } catch (err) {
      console.error('Failed to load live preview:', err)
    } finally {
      setPreviewLoading(false)
    }
  }

  async function testExtraction() {
    if (!testDocumentId) {
      alert('Select a document first')
      return
    }
    try {
      const result = await api.extractWithZones({
        document_id: testDocumentId,
        auction_type: selectedTemplate?.auction_type,
      })
      setTestResult(result)
    } catch (err) {
      console.error('Extraction failed:', err)
      alert('Extraction failed: ' + err.message)
    }
  }

  // Start editing zones
  function startEditMode() {
    if (!selectedTemplate?.zones) return
    setEditingZones(JSON.parse(JSON.stringify(selectedTemplate.zones)))
    setEditMode(true)
    setSelectedZoneIdx(null)
  }

  // Cancel editing
  function cancelEditMode() {
    setEditMode(false)
    setEditingZones([])
    setSelectedZoneIdx(null)
    setDragState(null)
  }

  // Save edited zones
  async function saveZones() {
    if (!selectedTemplate?.template_id) return
    setSaving(true)
    try {
      // Format zones correctly for the API
      const formattedZones = editingZones.map(zone => ({
        name: zone.name,
        x0: zone.x0,
        y0: zone.y0,
        x1: zone.x1,
        y1: zone.y1,
        description: zone.description || null,
        // Ensure fields are in the correct format (ZoneFieldModel)
        fields: (zone.fields || []).map(f => {
          if (typeof f === 'string') {
            return { key: f, field_type: 'text', required: false }
          }
          return {
            key: f.key || f,
            field_type: f.field_type || 'text',
            pattern: f.pattern || null,
            label: f.label || null,
            required: f.required || false,
          }
        }),
      }))

      // Send complete template data (not just zones)
      const updateData = {
        template_id: selectedTemplate.template_id,
        name: selectedTemplate.name,
        auction_type: selectedTemplate.auction_type,
        version: (selectedTemplate.version || 1) + 1,
        zones: formattedZones,
        description: selectedTemplate.description || null,
        is_active: selectedTemplate.is_active !== false,
      }

      await api.updateZoneTemplate(selectedTemplate.template_id, updateData)
      // Update local state
      setSelectedTemplate(prev => ({ ...prev, zones: formattedZones, version: updateData.version }))
      setTemplates(prev => prev.map(t =>
        t.template_id === selectedTemplate.template_id
          ? { ...t, zones: formattedZones, version: updateData.version }
          : t
      ))
      setEditMode(false)
      setEditingZones([])
      alert('Zones saved successfully!')
    } catch (err) {
      console.error('Failed to save zones:', err)
      // Better error message parsing
      let errorMsg = 'Unknown error'
      if (err.message) {
        errorMsg = err.message
      } else if (err.detail) {
        errorMsg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail)
      } else if (typeof err === 'object') {
        errorMsg = JSON.stringify(err)
      }
      alert('Failed to save: ' + errorMsg)
    } finally {
      setSaving(false)
    }
  }

  // Update a zone's coordinates
  function updateZone(idx, updates) {
    setEditingZones(prev => prev.map((z, i) =>
      i === idx ? { ...z, ...updates } : z
    ))
  }

  // Add new zone
  function addZone() {
    const newZone = {
      name: `Zone ${editingZones.length + 1}`,
      x0: 10,
      y0: 10,
      x1: 50,
      y1: 30,
      page_num: 1,
      fields: [],
    }
    setEditingZones(prev => [...prev, newZone])
    setSelectedZoneIdx(editingZones.length)
  }

  // Delete a zone
  function deleteZone(idx) {
    if (!confirm('Delete this zone?')) return
    setEditingZones(prev => prev.filter((_, i) => i !== idx))
    setSelectedZoneIdx(null)
  }

  // Handle mouse down on zone for dragging/resizing
  function handleZoneMouseDown(e, idx, action) {
    e.preventDefault()
    e.stopPropagation()
    if (!containerRef.current) return

    const rect = containerRef.current.getBoundingClientRect()
    setDragState({
      idx,
      action, // 'move' or 'resize'
      startX: e.clientX,
      startY: e.clientY,
      containerRect: rect,
      originalZone: { ...editingZones[idx] },
    })
    setSelectedZoneIdx(idx)
  }

  // Handle mouse move for dragging
  function handleMouseMove(e) {
    if (!dragState || !containerRef.current) return

    const { idx, action, startX, startY, containerRect, originalZone } = dragState
    const deltaX = ((e.clientX - startX) / containerRect.width) * 100
    const deltaY = ((e.clientY - startY) / containerRect.height) * 100

    if (action === 'move') {
      const newX0 = Math.max(0, Math.min(100 - (originalZone.x1 - originalZone.x0), originalZone.x0 + deltaX))
      const newY0 = Math.max(0, Math.min(100 - (originalZone.y1 - originalZone.y0), originalZone.y0 + deltaY))
      updateZone(idx, {
        x0: Math.round(newX0 * 10) / 10,
        y0: Math.round(newY0 * 10) / 10,
        x1: Math.round((newX0 + (originalZone.x1 - originalZone.x0)) * 10) / 10,
        y1: Math.round((newY0 + (originalZone.y1 - originalZone.y0)) * 10) / 10,
      })
    } else if (action === 'resize') {
      const newX1 = Math.max(originalZone.x0 + 5, Math.min(100, originalZone.x1 + deltaX))
      const newY1 = Math.max(originalZone.y0 + 5, Math.min(100, originalZone.y1 + deltaY))
      updateZone(idx, {
        x1: Math.round(newX1 * 10) / 10,
        y1: Math.round(newY1 * 10) / 10,
      })
    }
  }

  // Handle mouse up
  function handleMouseUp() {
    setDragState(null)
  }

  // Attach mouse events when dragging
  useEffect(() => {
    if (dragState) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
      return () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [dragState])

  const zoneColors = ZONE_COLORS_ARRAY
  const displayZones = editMode ? editingZones : (selectedTemplate?.zones || [])

  return (
    <div className="grid grid-cols-3 gap-6">
      {/* Left: Template List */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold mb-4">Extraction Templates</h3>

        {loading ? (
          <div className="text-center py-4 text-gray-500">Loading...</div>
        ) : templates.length === 0 ? (
          <div className="text-center py-4 text-gray-500">No templates found</div>
        ) : (
          <div className="space-y-2">
            {templates.map((t) => (
              <div
                key={t.template_id}
                className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedTemplate?.template_id === t.template_id
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
                onClick={() => {
                  setSelectedTemplate(t)
                  if (testDocumentId) {
                    loadZonePreview(t.template_id, testDocumentId)
                  }
                }}
              >
                <div className="font-medium">{t.name}</div>
                <div className="text-sm text-gray-500">{t.auction_type}</div>
                <div className="text-xs text-gray-400 mt-1">
                  {t.zones?.length || 0} zones defined
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Center: PDF Preview with Zones */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">
            {editMode ? '✏️ Edit Zones' : 'Zone Preview'}
          </h3>
          <div className="flex items-center gap-2">
            <select
              value={testDocumentId || ''}
              onChange={(e) => {
                const docId = e.target.value ? parseInt(e.target.value) : null
                setTestDocumentId(docId)
                if (docId && selectedTemplate) {
                  loadZonePreview(selectedTemplate.template_id, docId)
                }
              }}
              className="form-select text-sm"
              disabled={editMode}
            >
              <option value="">Select document...</option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.filename} ({doc.auction_type_code || 'unknown'})
                </option>
              ))}
            </select>
            {!editMode && selectedTemplate && (
              <button
                onClick={startEditMode}
                className="btn btn-sm bg-blue-600 text-white hover:bg-blue-700"
                title="Edit zones"
              >
                ✏️ Edit
              </button>
            )}
          </div>
        </div>

        {editMode && (
          <div className="mb-3 p-2 bg-blue-50 border border-blue-200 rounded text-sm text-blue-800">
            <strong>Edit Mode:</strong> Drag zones to move, drag corners to resize. Click zone to select.
          </div>
        )}

        {testDocumentId ? (
          <PdfZoneViewer
            pdfUrl={api.getDocumentFileUrl(testDocumentId)}
            zones={displayZones}
            selectedZoneIdx={selectedZoneIdx}
            editMode={editMode}
            onZoneChange={updateZone}
            onZoneSelect={setSelectedZoneIdx}
            zoneColors={zoneColors}
            height={500}
          />
        ) : (
          <div className="h-[500px] flex items-center justify-center text-gray-400 border rounded-lg bg-gray-50">
            Select a document to preview zones
          </div>
        )}

        <div className="mt-4 flex gap-2">
          {editMode ? (
            <>
              <button
                onClick={addZone}
                className="btn btn-secondary"
              >
                + Add Zone
              </button>
              <button
                onClick={cancelEditMode}
                className="btn btn-secondary flex-1"
              >
                Cancel
              </button>
              <button
                onClick={saveZones}
                disabled={saving}
                className="btn btn-primary flex-1"
              >
                {saving ? 'Saving...' : '💾 Save Zones'}
              </button>
            </>
          ) : (
            <button
              onClick={testExtraction}
              disabled={!testDocumentId || !selectedTemplate}
              className="btn btn-primary flex-1"
            >
              Test Zone Extraction
            </button>
          )}
        </div>
      </div>

      {/* Right: Zone Details & Results */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold mb-4">
          {testResult ? 'Extraction Results' : 'Zone Details'}
        </h3>

        {testResult ? (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sm font-medium">Confidence:</span>
              <span className={`px-2 py-1 rounded text-sm ${
                testResult.confidence > 0.7 ? 'bg-green-100 text-green-800' :
                testResult.confidence > 0.4 ? 'bg-yellow-100 text-yellow-800' :
                'bg-red-100 text-red-800'
              }`}>
                {(testResult.confidence * 100).toFixed(0)}%
              </span>
            </div>

            {testResult.warnings?.length > 0 && (
              <div className="text-sm text-yellow-600 bg-yellow-50 p-2 rounded">
                {testResult.warnings.map((w, i) => (
                  <div key={i}>⚠️ {w}</div>
                ))}
              </div>
            )}

            <div>
              <h4 className="text-sm font-medium mb-2">Extracted Fields:</h4>
              <div className="space-y-1 max-h-[400px] overflow-auto">
                {Object.entries(testResult.fields || {}).map(([key, value]) => (
                  <div key={key} className="flex justify-between text-sm p-2 bg-gray-50 rounded">
                    <span className="font-mono text-gray-600">{key}</span>
                    <span className="text-gray-900 font-medium truncate ml-2 max-w-[150px]" title={value}>
                      {value || '-'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <button
              onClick={() => setTestResult(null)}
              className="btn btn-secondary w-full"
            >
              Clear Results
            </button>
          </div>
        ) : selectedTemplate ? (
          <div className="space-y-4">
            <div>
              <span className="text-sm font-medium">Template ID:</span>
              <span className="ml-2 font-mono text-sm">{selectedTemplate.template_id}</span>
            </div>
            <div>
              <span className="text-sm font-medium">Auction Type:</span>
              <span className="ml-2">{selectedTemplate.auction_type}</span>
            </div>
            <div>
              <span className="text-sm font-medium">Description:</span>
              <p className="text-sm text-gray-600 mt-1">{selectedTemplate.description || 'No description'}</p>
            </div>

            <div>
              <h4 className="text-sm font-medium mb-2">Zones ({displayZones.length}):</h4>
              <div className="space-y-2 max-h-[300px] overflow-auto">
                {displayZones.map((zone, i) => (
                  <div
                    key={i}
                    className={`p-2 border rounded text-sm ${editMode && selectedZoneIdx === i ? 'ring-2 ring-yellow-400' : ''}`}
                    style={{ borderLeftColor: zoneColors[i % zoneColors.length].border, borderLeftWidth: '4px' }}
                    onClick={() => editMode && setSelectedZoneIdx(i)}
                  >
                    {editMode ? (
                      <div className="space-y-2">
                        <input
                          type="text"
                          value={zone.name}
                          onChange={(e) => updateZone(i, { name: e.target.value })}
                          className="form-input w-full text-sm py-1"
                          placeholder="Zone name"
                        />
                        <div className="grid grid-cols-4 gap-1 text-xs">
                          <div>
                            <label className="text-gray-500">X0</label>
                            <input
                              type="number"
                              value={zone.x0}
                              onChange={(e) => updateZone(i, { x0: parseFloat(e.target.value) || 0 })}
                              className="form-input w-full text-xs py-0.5"
                              min="0"
                              max="100"
                              step="0.5"
                            />
                          </div>
                          <div>
                            <label className="text-gray-500">Y0</label>
                            <input
                              type="number"
                              value={zone.y0}
                              onChange={(e) => updateZone(i, { y0: parseFloat(e.target.value) || 0 })}
                              className="form-input w-full text-xs py-0.5"
                              min="0"
                              max="100"
                              step="0.5"
                            />
                          </div>
                          <div>
                            <label className="text-gray-500">X1</label>
                            <input
                              type="number"
                              value={zone.x1}
                              onChange={(e) => updateZone(i, { x1: parseFloat(e.target.value) || 0 })}
                              className="form-input w-full text-xs py-0.5"
                              min="0"
                              max="100"
                              step="0.5"
                            />
                          </div>
                          <div>
                            <label className="text-gray-500">Y1</label>
                            <input
                              type="number"
                              value={zone.y1}
                              onChange={(e) => updateZone(i, { y1: parseFloat(e.target.value) || 0 })}
                              className="form-input w-full text-xs py-0.5"
                              min="0"
                              max="100"
                              step="0.5"
                            />
                          </div>
                        </div>
                        <button
                          onClick={() => deleteZone(i)}
                          className="text-xs text-red-600 hover:text-red-800"
                        >
                          🗑️ Delete Zone
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="font-medium">{zone.name}</div>
                        <div className="text-xs text-gray-500">
                          ({zone.x0}%, {zone.y0}%) - ({zone.x1}%, {zone.y1}%)
                        </div>
                        <div className="text-xs text-gray-400 mt-1">
                          Fields: {zone.fields?.map(f => f.key || f).join(', ') || 'none'}
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Zone Text Preview Section */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <h4 className="text-sm font-medium">Zone Text Preview:</h4>
                {editMode && testDocumentId && (
                  <button
                    onClick={loadLivePreview}
                    disabled={previewLoading}
                    className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
                  >
                    {previewLoading ? '...' : '🔄 Refresh Preview'}
                  </button>
                )}
              </div>

              {editMode && zonePreview?.source !== 'live_preview' && (
                <div className="text-xs text-orange-600 bg-orange-50 p-2 rounded mb-2">
                  ⚠️ Preview shows SAVED zones. Click "Refresh Preview" to see current edits.
                </div>
              )}

              {zonePreview ? (
                <div className="space-y-2 max-h-[200px] overflow-auto">
                  {zonePreview.zones?.map((z, i) => (
                    <div key={i} className="p-2 bg-gray-50 rounded text-xs">
                      <div className="font-medium" style={{ color: zoneColors[i % zoneColors.length].border }}>
                        {z.name}
                      </div>
                      <pre className="whitespace-pre-wrap text-gray-600 mt-1 max-h-20 overflow-auto">
                        {z.text || '(empty)'}
                      </pre>
                    </div>
                  ))}
                </div>
              ) : testDocumentId ? (
                <div className="text-xs text-gray-400 italic">
                  {editMode ? 'Click "Refresh Preview" to see zone text' : 'Loading preview...'}
                </div>
              ) : (
                <div className="text-xs text-gray-400 italic">
                  Select a document to preview zone text
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-center text-gray-400 py-8">
            Select a template to see details
          </div>
        )}
      </div>
    </div>
  )
}
