/**
 * VisualZoneEditor - Interactive visual zone editor with document background
 *
 * Features:
 * - Display PDF page as background image
 * - Drag zones to reposition them
 * - Resize zones by dragging edges/corners
 * - Click to select and edit zone properties
 * - Real-time coordinate feedback
 */
import { useState, useRef, useEffect, useCallback } from 'react'

// Zone colors for different zone names
const ZONE_COLORS = {
  header: { bg: 'rgba(59, 130, 246, 0.2)', border: '#3B82F6' },
  vehicle_info: { bg: 'rgba(16, 185, 129, 0.2)', border: '#10B981' },
  member_info: { bg: 'rgba(139, 92, 246, 0.2)', border: '#8B5CF6' },
  buyer_info: { bg: 'rgba(139, 92, 246, 0.2)', border: '#8B5CF6' },
  seller_info: { bg: 'rgba(245, 158, 11, 0.2)', border: '#F59E0B' },
  lot_address: { bg: 'rgba(6, 182, 212, 0.2)', border: '#06B6D4' },
  pickup: { bg: 'rgba(6, 182, 212, 0.2)', border: '#06B6D4' },
  pickup_location: { bg: 'rgba(6, 182, 212, 0.2)', border: '#06B6D4' },
  delivery: { bg: 'rgba(236, 72, 153, 0.2)', border: '#EC4899' },
  pricing: { bg: 'rgba(239, 68, 68, 0.2)', border: '#EF4444' },
  financial_info: { bg: 'rgba(239, 68, 68, 0.2)', border: '#EF4444' },
  dates: { bg: 'rgba(139, 92, 246, 0.2)', border: '#8B5CF6' },
  footer: { bg: 'rgba(107, 114, 128, 0.2)', border: '#6B7280' },
}

function getZoneColor(name) {
  const key = name.toLowerCase()
  for (const [k, v] of Object.entries(ZONE_COLORS)) {
    if (key.includes(k)) return v
  }
  return { bg: 'rgba(107, 114, 128, 0.2)', border: '#6B7280' }
}

// Resize handle component
function ResizeHandle({ position, onMouseDown }) {
  const positionStyles = {
    'top-left': { top: -4, left: -4, cursor: 'nw-resize' },
    'top-right': { top: -4, right: -4, cursor: 'ne-resize' },
    'bottom-left': { bottom: -4, left: -4, cursor: 'sw-resize' },
    'bottom-right': { bottom: -4, right: -4, cursor: 'se-resize' },
    'top': { top: -4, left: '50%', transform: 'translateX(-50%)', cursor: 'n-resize' },
    'bottom': { bottom: -4, left: '50%', transform: 'translateX(-50%)', cursor: 's-resize' },
    'left': { left: -4, top: '50%', transform: 'translateY(-50%)', cursor: 'w-resize' },
    'right': { right: -4, top: '50%', transform: 'translateY(-50%)', cursor: 'e-resize' },
  }

  return (
    <div
      className="absolute w-3 h-3 bg-white border-2 border-blue-500 rounded-sm z-20 hover:bg-blue-100"
      style={positionStyles[position]}
      onMouseDown={(e) => {
        e.stopPropagation()
        onMouseDown(e, position)
      }}
    />
  )
}

// Single zone overlay
function ZoneOverlay({
  zone,
  index,
  isSelected,
  containerWidth,
  containerHeight,
  onSelect,
  onChange,
}) {
  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const [resizeHandle, setResizeHandle] = useState(null)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const [initialZone, setInitialZone] = useState(null)

  const colors = getZoneColor(zone.name)

  // Convert percentage to pixels
  const left = (zone.x0 / 100) * containerWidth
  const top = (zone.y0 / 100) * containerHeight
  const width = ((zone.x1 - zone.x0) / 100) * containerWidth
  const height = ((zone.y1 - zone.y0) / 100) * containerHeight

  // Handle drag start
  const handleMouseDown = (e) => {
    if (isResizing) return
    e.preventDefault()
    onSelect(index)
    setIsDragging(true)
    setDragStart({ x: e.clientX, y: e.clientY })
    setInitialZone({ ...zone })
  }

  // Handle resize start
  const handleResizeStart = (e, handle) => {
    e.preventDefault()
    setIsResizing(true)
    setResizeHandle(handle)
    setDragStart({ x: e.clientX, y: e.clientY })
    setInitialZone({ ...zone })
  }

  // Handle mouse move
  useEffect(() => {
    if (!isDragging && !isResizing) return

    const handleMouseMove = (e) => {
      const deltaX = e.clientX - dragStart.x
      const deltaY = e.clientY - dragStart.y

      // Convert pixel delta to percentage
      const deltaXPercent = (deltaX / containerWidth) * 100
      const deltaYPercent = (deltaY / containerHeight) * 100

      let newZone = { ...initialZone }

      if (isDragging) {
        // Move the entire zone
        const newX0 = Math.max(0, Math.min(100 - (initialZone.x1 - initialZone.x0), initialZone.x0 + deltaXPercent))
        const newY0 = Math.max(0, Math.min(100 - (initialZone.y1 - initialZone.y0), initialZone.y0 + deltaYPercent))
        const zoneWidth = initialZone.x1 - initialZone.x0
        const zoneHeight = initialZone.y1 - initialZone.y0

        newZone = {
          ...initialZone,
          x0: Math.round(newX0 * 10) / 10,
          y0: Math.round(newY0 * 10) / 10,
          x1: Math.round((newX0 + zoneWidth) * 10) / 10,
          y1: Math.round((newY0 + zoneHeight) * 10) / 10,
        }
      } else if (isResizing) {
        // Resize based on handle
        switch (resizeHandle) {
          case 'top-left':
            newZone.x0 = Math.max(0, Math.min(initialZone.x1 - 5, initialZone.x0 + deltaXPercent))
            newZone.y0 = Math.max(0, Math.min(initialZone.y1 - 5, initialZone.y0 + deltaYPercent))
            break
          case 'top-right':
            newZone.x1 = Math.max(initialZone.x0 + 5, Math.min(100, initialZone.x1 + deltaXPercent))
            newZone.y0 = Math.max(0, Math.min(initialZone.y1 - 5, initialZone.y0 + deltaYPercent))
            break
          case 'bottom-left':
            newZone.x0 = Math.max(0, Math.min(initialZone.x1 - 5, initialZone.x0 + deltaXPercent))
            newZone.y1 = Math.max(initialZone.y0 + 5, Math.min(100, initialZone.y1 + deltaYPercent))
            break
          case 'bottom-right':
            newZone.x1 = Math.max(initialZone.x0 + 5, Math.min(100, initialZone.x1 + deltaXPercent))
            newZone.y1 = Math.max(initialZone.y0 + 5, Math.min(100, initialZone.y1 + deltaYPercent))
            break
          case 'top':
            newZone.y0 = Math.max(0, Math.min(initialZone.y1 - 5, initialZone.y0 + deltaYPercent))
            break
          case 'bottom':
            newZone.y1 = Math.max(initialZone.y0 + 5, Math.min(100, initialZone.y1 + deltaYPercent))
            break
          case 'left':
            newZone.x0 = Math.max(0, Math.min(initialZone.x1 - 5, initialZone.x0 + deltaXPercent))
            break
          case 'right':
            newZone.x1 = Math.max(initialZone.x0 + 5, Math.min(100, initialZone.x1 + deltaXPercent))
            break
        }

        // Round to 1 decimal place
        newZone.x0 = Math.round(newZone.x0 * 10) / 10
        newZone.y0 = Math.round(newZone.y0 * 10) / 10
        newZone.x1 = Math.round(newZone.x1 * 10) / 10
        newZone.y1 = Math.round(newZone.y1 * 10) / 10
      }

      onChange(index, newZone)
    }

    const handleMouseUp = () => {
      setIsDragging(false)
      setIsResizing(false)
      setResizeHandle(null)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, isResizing, dragStart, initialZone, containerWidth, containerHeight, resizeHandle, index, onChange])

  return (
    <div
      className={`absolute transition-shadow ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
      style={{
        left: `${left}px`,
        top: `${top}px`,
        width: `${width}px`,
        height: `${height}px`,
        backgroundColor: colors.bg,
        border: `2px ${isSelected ? 'solid' : 'dashed'} ${colors.border}`,
        boxShadow: isSelected ? `0 0 0 2px ${colors.border}40` : 'none',
        zIndex: isSelected ? 15 : 10,
      }}
      onMouseDown={handleMouseDown}
    >
      {/* Zone label */}
      <div
        className="absolute -top-5 left-0 px-1.5 py-0.5 text-xs font-medium text-white rounded-t whitespace-nowrap"
        style={{ backgroundColor: colors.border }}
      >
        {zone.name}
      </div>

      {/* Coordinates display */}
      {isSelected && (
        <div className="absolute -bottom-5 left-0 px-1 py-0.5 text-xs font-mono bg-gray-800 text-white rounded whitespace-nowrap">
          ({zone.x0.toFixed(1)}%, {zone.y0.toFixed(1)}%) - ({zone.x1.toFixed(1)}%, {zone.y1.toFixed(1)}%)
        </div>
      )}

      {/* Resize handles - only show when selected */}
      {isSelected && (
        <>
          <ResizeHandle position="top-left" onMouseDown={handleResizeStart} />
          <ResizeHandle position="top-right" onMouseDown={handleResizeStart} />
          <ResizeHandle position="bottom-left" onMouseDown={handleResizeStart} />
          <ResizeHandle position="bottom-right" onMouseDown={handleResizeStart} />
          <ResizeHandle position="top" onMouseDown={handleResizeStart} />
          <ResizeHandle position="bottom" onMouseDown={handleResizeStart} />
          <ResizeHandle position="left" onMouseDown={handleResizeStart} />
          <ResizeHandle position="right" onMouseDown={handleResizeStart} />
        </>
      )}

      {/* Fields count badge */}
      {zone.fields?.length > 0 && (
        <div
          className="absolute top-1 right-1 w-5 h-5 flex items-center justify-center text-xs font-bold rounded-full text-white"
          style={{ backgroundColor: colors.border }}
        >
          {zone.fields.length}
        </div>
      )}
    </div>
  )
}

export default function VisualZoneEditor({
  zones,
  documentId,
  pageNum = 1,
  onChange,
  onZoneSelect,
  selectedZoneIndex = null,
}) {
  const containerRef = useRef(null)
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })
  const [imageLoaded, setImageLoaded] = useState(false)
  const [imageError, setImageError] = useState(null)
  const [imageNaturalSize, setImageNaturalSize] = useState({ width: 0, height: 0 })
  const [zoom, setZoom] = useState(100)

  // Calculate image URL
  const imageUrl = documentId
    ? `/api/documents/${documentId}/page/${pageNum}/image?dpi=150`
    : null

  // Update container size when image loads
  const handleImageLoad = useCallback((e) => {
    const img = e.target
    setImageNaturalSize({ width: img.naturalWidth, height: img.naturalHeight })
    setImageLoaded(true)
    setImageError(null)

    // Update container size
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect()
      setContainerSize({ width: rect.width, height: rect.height })
    }
  }, [])

  // Handle image error
  const handleImageError = useCallback(() => {
    setImageLoaded(false)
    setImageError('Failed to load document image. Make sure the document exists and pdf2image is installed.')
  }, [])

  // Update container size on resize
  useEffect(() => {
    if (!containerRef.current) return

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })

    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  // Handle zone change
  const handleZoneChange = useCallback((index, updatedZone) => {
    const newZones = [...zones]
    newZones[index] = updatedZone
    onChange(newZones)
  }, [zones, onChange])

  // Handle zone selection
  const handleZoneSelect = useCallback((index) => {
    if (onZoneSelect) {
      onZoneSelect(index)
    }
  }, [onZoneSelect])

  // Handle click on empty area to deselect
  const handleBackgroundClick = useCallback((e) => {
    if (e.target === e.currentTarget && onZoneSelect) {
      onZoneSelect(null)
    }
  }, [onZoneSelect])

  // Calculate display dimensions based on zoom
  const aspectRatio = imageNaturalSize.height > 0
    ? imageNaturalSize.width / imageNaturalSize.height
    : 612 / 792 // Default Letter size

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-700">Visual Zone Editor</span>
          {documentId && (
            <span className="text-xs text-gray-500">Document #{documentId}, Page {pageNum}</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Zoom controls */}
          <button
            onClick={() => setZoom(Math.max(50, zoom - 25))}
            className="p-1 rounded hover:bg-gray-200"
            title="Zoom out"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
            </svg>
          </button>
          <span className="text-xs font-mono w-12 text-center">{zoom}%</span>
          <button
            onClick={() => setZoom(Math.min(200, zoom + 25))}
            className="p-1 rounded hover:bg-gray-200"
            title="Zoom in"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
          <button
            onClick={() => setZoom(100)}
            className="px-2 py-0.5 text-xs border rounded hover:bg-gray-100"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Main editor area */}
      <div className="flex-1 overflow-auto bg-gray-200 p-4">
        {!documentId ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-gray-500">
              <svg className="w-16 h-16 mx-auto mb-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-lg font-medium mb-2">No document selected</p>
              <p className="text-sm">Upload a document or select one from the list to start editing zones</p>
            </div>
          </div>
        ) : imageError ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-red-500">
              <svg className="w-16 h-16 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-lg font-medium mb-2">Error loading document</p>
              <p className="text-sm">{imageError}</p>
            </div>
          </div>
        ) : (
          <div
            className="relative mx-auto bg-white shadow-lg"
            style={{
              width: `${(zoom / 100) * 100}%`,
              maxWidth: '1200px',
            }}
          >
            {/* PDF page image */}
            <img
              src={imageUrl}
              alt={`Page ${pageNum}`}
              className="w-full h-auto"
              onLoad={handleImageLoad}
              onError={handleImageError}
              draggable={false}
            />

            {/* Zone overlay container */}
            {imageLoaded && (
              <div
                ref={containerRef}
                className="absolute inset-0"
                onClick={handleBackgroundClick}
              >
                {zones.map((zone, index) => (
                  <ZoneOverlay
                    key={index}
                    zone={zone}
                    index={index}
                    isSelected={selectedZoneIndex === index}
                    containerWidth={containerSize.width}
                    containerHeight={containerSize.height}
                    onSelect={handleZoneSelect}
                    onChange={handleZoneChange}
                  />
                ))}
              </div>
            )}

            {/* Loading overlay */}
            {!imageLoaded && !imageError && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-100">
                <div className="text-center">
                  <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 mx-auto"></div>
                  <p className="mt-3 text-sm text-gray-600">Loading document...</p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Instructions footer */}
      <div className="px-3 py-2 bg-gray-50 border-t text-xs text-gray-500">
        <span className="font-medium">Tips:</span> Click a zone to select it. Drag to move. Use corner/edge handles to resize.
        Coordinates are shown as percentages of page size.
      </div>
    </div>
  )
}
