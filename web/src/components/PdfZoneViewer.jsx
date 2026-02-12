import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * PDF Zone Viewer - Renders PDF with zone overlays that scale correctly
 *
 * Uses PDF.js to render PDF to canvas, ensuring zones are properly
 * positioned regardless of zoom level.
 *
 * Props:
 * - pdfUrl: URL to PDF file
 * - zones: Array of zone objects with x0, y0, x1, y1 (in percentages)
 * - selectedZoneIdx: Index of currently selected zone
 * - editMode: Enable zone editing (drag/resize)
 * - onZoneChange: Callback when zone is moved/resized
 * - onZoneSelect: Callback when zone is clicked
 * - zoneColors: Array of color objects for zones
 */

// Load PDF.js from CDN
const PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174'

let pdfjsLib = null

async function loadPdfJs() {
  if (pdfjsLib) return pdfjsLib

  // Load PDF.js script
  if (!window.pdfjsLib) {
    await new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = `${PDFJS_CDN}/pdf.min.js`
      script.onload = resolve
      script.onerror = reject
      document.head.appendChild(script)
    })
  }

  pdfjsLib = window.pdfjsLib
  pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_CDN}/pdf.worker.min.js`

  return pdfjsLib
}

export default function PdfZoneViewer({
  pdfUrl,
  zones = [],
  selectedZoneIdx = null,
  editMode = false,
  onZoneChange,
  onZoneSelect,
  zoneColors = [],
  height = 500,
  initialScale = 1.0,
}) {
  const containerRef = useRef(null)
  const canvasRef = useRef(null)
  const [pdfDoc, setPdfDoc] = useState(null)
  const [pageNum, setPageNum] = useState(1)
  const [numPages, setNumPages] = useState(0)
  const [scale, setScale] = useState(initialScale)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 })
  const [dragState, setDragState] = useState(null)

  // Load PDF
  useEffect(() => {
    if (!pdfUrl) return

    let cancelled = false

    async function loadPdf() {
      setLoading(true)
      setError(null)

      try {
        const pdfjs = await loadPdfJs()
        const doc = await pdfjs.getDocument(pdfUrl).promise

        if (cancelled) return

        setPdfDoc(doc)
        setNumPages(doc.numPages)
        setPageNum(1)
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load PDF:', err)
          setError(err.message)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadPdf()

    return () => {
      cancelled = true
    }
  }, [pdfUrl])

  // Render page
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return

    let cancelled = false

    async function renderPage() {
      try {
        const page = await pdfDoc.getPage(pageNum)
        if (cancelled) return

        const viewport = page.getViewport({ scale })
        const canvas = canvasRef.current
        const context = canvas.getContext('2d')

        canvas.width = viewport.width
        canvas.height = viewport.height

        setPageSize({
          width: viewport.width,
          height: viewport.height,
        })

        await page.render({
          canvasContext: context,
          viewport,
        }).promise
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to render page:', err)
        }
      }
    }

    renderPage()

    return () => {
      cancelled = true
    }
  }, [pdfDoc, pageNum, scale])

  // Zone drag handling
  const handleZoneMouseDown = useCallback((e, idx, action) => {
    if (!editMode || !containerRef.current) return

    e.preventDefault()
    e.stopPropagation()

    const rect = containerRef.current.getBoundingClientRect()
    setDragState({
      idx,
      action, // 'move' or 'resize'
      startX: e.clientX,
      startY: e.clientY,
      containerRect: rect,
      originalZone: { ...zones[idx] },
    })

    if (onZoneSelect) {
      onZoneSelect(idx)
    }
  }, [editMode, zones, onZoneSelect])

  const handleMouseMove = useCallback((e) => {
    if (!dragState || !onZoneChange) return

    const { idx, action, startX, startY, containerRect, originalZone } = dragState
    const deltaX = ((e.clientX - startX) / containerRect.width) * 100
    const deltaY = ((e.clientY - startY) / containerRect.height) * 100

    let updates = {}

    if (action === 'move') {
      const newX0 = Math.max(0, Math.min(100 - (originalZone.x1 - originalZone.x0), originalZone.x0 + deltaX))
      const newY0 = Math.max(0, Math.min(100 - (originalZone.y1 - originalZone.y0), originalZone.y0 + deltaY))
      updates = {
        x0: Math.round(newX0 * 10) / 10,
        y0: Math.round(newY0 * 10) / 10,
        x1: Math.round((newX0 + (originalZone.x1 - originalZone.x0)) * 10) / 10,
        y1: Math.round((newY0 + (originalZone.y1 - originalZone.y0)) * 10) / 10,
      }
    } else if (action === 'resize') {
      const newX1 = Math.max(originalZone.x0 + 5, Math.min(100, originalZone.x1 + deltaX))
      const newY1 = Math.max(originalZone.y0 + 5, Math.min(100, originalZone.y1 + deltaY))
      updates = {
        x1: Math.round(newX1 * 10) / 10,
        y1: Math.round(newY1 * 10) / 10,
      }
    }

    onZoneChange(idx, updates)
  }, [dragState, onZoneChange])

  const handleMouseUp = useCallback(() => {
    setDragState(null)
  }, [])

  // Global mouse events for dragging
  useEffect(() => {
    if (dragState) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
      return () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [dragState, handleMouseMove, handleMouseUp])

  // Default zone colors
  const defaultColors = [
    { bg: 'rgba(59, 130, 246, 0.2)', border: '#3b82f6' },
    { bg: 'rgba(16, 185, 129, 0.2)', border: '#10b981' },
    { bg: 'rgba(245, 158, 11, 0.2)', border: '#f59e0b' },
    { bg: 'rgba(239, 68, 68, 0.2)', border: '#ef4444' },
    { bg: 'rgba(139, 92, 246, 0.2)', border: '#8b5cf6' },
  ]
  const colors = zoneColors.length > 0 ? zoneColors : defaultColors

  if (loading) {
    return (
      <div
        className="flex items-center justify-center bg-gray-100 rounded-lg"
        style={{ height }}
      >
        <div className="text-gray-500">Loading PDF...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className="flex items-center justify-center bg-red-50 rounded-lg"
        style={{ height }}
      >
        <div className="text-red-600">Error: {error}</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Controls */}
      <div className="flex items-center gap-2 text-sm">
        <button
          onClick={() => setScale(s => Math.max(0.5, s - 0.25))}
          className="px-2 py-1 bg-gray-100 rounded hover:bg-gray-200"
          title="Zoom out"
        >
          −
        </button>
        <span className="w-16 text-center">{Math.round(scale * 100)}%</span>
        <button
          onClick={() => setScale(s => Math.min(3, s + 0.25))}
          className="px-2 py-1 bg-gray-100 rounded hover:bg-gray-200"
          title="Zoom in"
        >
          +
        </button>
        <button
          onClick={() => setScale(1)}
          className="px-2 py-1 bg-gray-100 rounded hover:bg-gray-200 text-xs"
        >
          100%
        </button>

        {numPages > 1 && (
          <>
            <span className="mx-2">|</span>
            <button
              onClick={() => setPageNum(p => Math.max(1, p - 1))}
              disabled={pageNum <= 1}
              className="px-2 py-1 bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
            >
              ←
            </button>
            <span>Page {pageNum} / {numPages}</span>
            <button
              onClick={() => setPageNum(p => Math.min(numPages, p + 1))}
              disabled={pageNum >= numPages}
              className="px-2 py-1 bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
            >
              →
            </button>
          </>
        )}

        {editMode && (
          <span className="ml-auto text-xs text-blue-600">
            Zones scale with PDF zoom
          </span>
        )}
      </div>

      {/* PDF with zones overlay */}
      <div
        ref={containerRef}
        className={`relative overflow-auto border rounded-lg bg-gray-200 ${editMode ? 'cursor-crosshair' : ''}`}
        style={{ height, maxHeight: height }}
      >
        <div className="relative inline-block">
          {/* PDF Canvas */}
          <canvas ref={canvasRef} className="block" />

          {/* Zone overlays - positioned relative to canvas size */}
          {pageSize.width > 0 && zones.map((zone, i) => (
            <div
              key={i}
              className={`absolute border-2 ${editMode ? 'cursor-move' : ''} ${
                selectedZoneIdx === i ? 'ring-2 ring-yellow-400 ring-offset-1' : ''
              }`}
              style={{
                left: `${zone.x0}%`,
                top: `${zone.y0}%`,
                width: `${zone.x1 - zone.x0}%`,
                height: `${zone.y1 - zone.y0}%`,
                backgroundColor: colors[i % colors.length].bg,
                borderColor: colors[i % colors.length].border,
              }}
              onMouseDown={editMode ? (e) => handleZoneMouseDown(e, i, 'move') : undefined}
              onClick={editMode ? () => onZoneSelect?.(i) : undefined}
            >
              {/* Zone label */}
              <span
                className="absolute -top-5 left-0 text-xs font-bold px-1 rounded whitespace-nowrap"
                style={{
                  backgroundColor: colors[i % colors.length].border,
                  color: 'white',
                }}
              >
                {zone.name}
              </span>

              {/* Resize handle */}
              {editMode && (
                <div
                  className="absolute bottom-0 right-0 w-3 h-3 bg-white border-2 cursor-se-resize"
                  style={{
                    borderColor: colors[i % colors.length].border,
                    transform: 'translate(50%, 50%)',
                  }}
                  onMouseDown={(e) => handleZoneMouseDown(e, i, 'resize')}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
