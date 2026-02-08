import { useState, useEffect } from 'react'
import api from '../../api'
import { ZONE_COLORS_ARRAY } from '../../constants/zones'

export default function ZoneTemplatesTab({ auctionTypes }) {
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [testDocumentId, setTestDocumentId] = useState(null)
  const [documents, setDocuments] = useState([])
  const [zonePreview, setZonePreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [testResult, setTestResult] = useState(null)

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

  const zoneColors = ZONE_COLORS_ARRAY

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
          <h3 className="text-lg font-semibold">Zone Preview</h3>
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
          >
            <option value="">Select document...</option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.filename} ({doc.auction_type_code || 'unknown'})
              </option>
            ))}
          </select>
        </div>

        {testDocumentId ? (
          <div className="relative border rounded-lg overflow-hidden bg-gray-100" style={{ height: '500px' }}>
            <iframe
              src={api.getDocumentFileUrl(testDocumentId)}
              className="w-full h-full"
              title="PDF Preview"
            />
            {selectedTemplate?.zones && (
              <div className="absolute inset-0 pointer-events-none">
                {selectedTemplate.zones.map((zone, i) => (
                  <div
                    key={i}
                    className="absolute border-2"
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
                      className="absolute -top-5 left-0 text-xs font-bold px-1 rounded"
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
            )}
          </div>
        ) : (
          <div className="h-[500px] flex items-center justify-center text-gray-400 border rounded-lg bg-gray-50">
            Select a document to preview zones
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <button
            onClick={testExtraction}
            disabled={!testDocumentId || !selectedTemplate}
            className="btn btn-primary flex-1"
          >
            Test Zone Extraction
          </button>
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
              <h4 className="text-sm font-medium mb-2">Zones ({selectedTemplate.zones?.length || 0}):</h4>
              <div className="space-y-2 max-h-[300px] overflow-auto">
                {selectedTemplate.zones?.map((zone, i) => (
                  <div
                    key={i}
                    className="p-2 border rounded text-sm"
                    style={{ borderLeftColor: zoneColors[i % zoneColors.length].border, borderLeftWidth: '4px' }}
                  >
                    <div className="font-medium">{zone.name}</div>
                    <div className="text-xs text-gray-500">
                      ({zone.x0}%, {zone.y0}%) - ({zone.x1}%, {zone.y1}%)
                    </div>
                    <div className="text-xs text-gray-400 mt-1">
                      Fields: {zone.fields?.map(f => f.key).join(', ') || 'none'}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {zonePreview && (
              <div>
                <h4 className="text-sm font-medium mb-2">Zone Text Preview:</h4>
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
              </div>
            )}
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
