/**
 * PDFViewer Component (M3.P2.1 & M3.P2.2)
 *
 * Interactive PDF viewer with bbox overlay for field evidence highlighting.
 *
 * Features:
 * - Display PDF in iframe with overlay canvas
 * - Show all layout blocks as semi-transparent boxes
 * - Highlight specific field evidence when user clicks a field
 * - Support page navigation
 *
 * Note: Uses iframe + overlay approach since PDF.js requires more setup.
 * The overlay coordinates are mapped to PDF coordinates using page dimensions.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import api from '../api'

// Default PDF page dimensions (Letter size at 72 DPI)
const DEFAULT_PAGE_WIDTH = 612
const DEFAULT_PAGE_HEIGHT = 792

function PDFViewer({
  pdfUrl,
  runId,
  highlightedField = null,
  onBlockClick = null,
  showAllBlocks = false,
}) {
  const [evidence, setEvidence] = useState(null)
  const [blocks, setBlocks] = useState([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [scale, setScale] = useState(1.0)
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })

  const containerRef = useRef(null)
  const iframeRef = useRef(null)

  // Fetch evidence data
  useEffect(() => {
    if (!runId) return

    const fetchEvidence = async () => {
      setLoading(true)
      try {
        const data = await api.getRunEvidence(runId)
        setEvidence(data.evidence_by_field || {})
        setBlocks(data.blocks || [])

        // Calculate total pages from blocks
        const maxPage = Math.max(
          1,
          ...data.blocks.map(b => b.page_num || 1)
        )
        setTotalPages(maxPage)
      } catch (err) {
        console.error('Failed to fetch evidence:', err)
        setEvidence({})
        setBlocks([])
      } finally {
        setLoading(false)
      }
    }

    fetchEvidence()
  }, [runId])

  // Update container size on resize
  useEffect(() => {
    if (!containerRef.current) return

    const updateSize = () => {
      if (containerRef.current) {
        setContainerSize({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight,
        })
      }
    }

    updateSize()
    window.addEventListener('resize', updateSize)
    return () => window.removeEventListener('resize', updateSize)
  }, [])

  // Calculate scale factor based on container width
  useEffect(() => {
    if (containerSize.width > 0) {
      // Assume standard PDF width, calculate scale to fit container
      const newScale = containerSize.width / DEFAULT_PAGE_WIDTH
      setScale(newScale)
    }
  }, [containerSize.width])

  // Get blocks for current page
  const currentPageBlocks = blocks.filter(b => (b.page_num || 1) === currentPage)

  // Get highlighted evidence
  const highlightedEvidence = highlightedField && evidence
    ? evidence[highlightedField] || []
    : []

  // Convert PDF coordinates to screen coordinates
  const toScreenCoords = useCallback((bbox) => {
    return {
      left: bbox.x0 * scale,
      top: bbox.y0 * scale,
      width: (bbox.x1 - bbox.x0) * scale,
      height: (bbox.y1 - bbox.y0) * scale,
    }
  }, [scale])

  // Handle page navigation
  const goToPage = (page) => {
    const newPage = Math.max(1, Math.min(page, totalPages))
    setCurrentPage(newPage)
  }

  // Navigate to page containing highlighted evidence
  useEffect(() => {
    if (highlightedEvidence.length > 0) {
      const firstEvidence = highlightedEvidence[0]
      if (firstEvidence.page_num && firstEvidence.page_num !== currentPage) {
        setCurrentPage(firstEvidence.page_num)
      }
    }
  }, [highlightedEvidence, currentPage])

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
        <div className="flex items-center space-x-3">
          <span className="font-medium text-sm text-gray-700">Original Document</span>
          {highlightedField && (
            <span className="px-2 py-0.5 bg-blue-100 text-blue-800 text-xs rounded">
              Showing: {highlightedField.replace(/_/g, ' ')}
            </span>
          )}
        </div>
        <div className="flex items-center space-x-2">
          {/* Page navigation */}
          <div className="flex items-center space-x-1 text-sm">
            <button
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
              className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <span className="text-gray-600 px-2">
              {currentPage} / {totalPages}
            </span>
            <button
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>

          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary-600 hover:text-primary-800 ml-2"
          >
            Open in new tab
          </a>
        </div>
      </div>

      {/* PDF Container with Overlay */}
      <div
        ref={containerRef}
        className="relative"
        style={{ height: 'calc(100vh - 200px)' }}
      >
        {/* PDF iframe */}
        <iframe
          ref={iframeRef}
          src={`${pdfUrl}#page=${currentPage}`}
          className="w-full h-full border-0"
          title="Document PDF"
        />

        {/* Overlay for bboxes */}
        <div
          className="absolute inset-0 pointer-events-none overflow-hidden"
          style={{ pointerEvents: 'none' }}
        >
          {/* Show all blocks if enabled */}
          {showAllBlocks && currentPageBlocks.map((block, idx) => {
            const coords = toScreenCoords(block.bbox)
            return (
              <div
                key={`block-${idx}`}
                className="absolute border border-gray-300 bg-gray-100 opacity-20"
                style={{
                  left: coords.left,
                  top: coords.top,
                  width: coords.width,
                  height: coords.height,
                }}
              />
            )
          })}

          {/* Highlighted evidence boxes */}
          {highlightedEvidence
            .filter(ev => (ev.page_num || 1) === currentPage && ev.bbox)
            .map((ev, idx) => {
              const coords = toScreenCoords(ev.bbox)
              return (
                <div
                  key={`evidence-${idx}`}
                  className="absolute"
                  style={{
                    left: coords.left,
                    top: coords.top,
                    width: coords.width,
                    height: coords.height,
                  }}
                >
                  {/* Highlight box */}
                  <div className="absolute inset-0 bg-blue-400 opacity-30 animate-pulse" />
                  <div className="absolute inset-0 border-2 border-blue-600" />

                  {/* Tooltip */}
                  {ev.text_snippet && (
                    <div
                      className="absolute -top-8 left-0 bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg max-w-xs truncate z-10 pointer-events-auto"
                      style={{ whiteSpace: 'nowrap' }}
                    >
                      {ev.text_snippet.substring(0, 50)}
                      {ev.text_snippet.length > 50 && '...'}
                    </div>
                  )}
                </div>
              )
            })}
        </div>

        {/* Loading overlay */}
        {loading && (
          <div className="absolute inset-0 bg-white bg-opacity-75 flex items-center justify-center">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
              <p className="mt-2 text-sm text-gray-600">Loading evidence...</p>
            </div>
          </div>
        )}
      </div>

      {/* Evidence summary footer */}
      {evidence && Object.keys(evidence).length > 0 && (
        <div className="px-4 py-2 border-t border-gray-200 bg-gray-50 text-xs text-gray-500">
          {Object.keys(evidence).length} fields with evidence
          {highlightedField && highlightedEvidence.length > 0 && (
            <span className="ml-2 text-blue-600">
              | {highlightedEvidence.length} evidence block{highlightedEvidence.length > 1 ? 's' : ''} for {highlightedField.replace(/_/g, ' ')}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export default PDFViewer
