/**
 * ZoneVisualization - Read-only zone overlay for Review page
 *
 * Shows extraction zones overlaid on PDF/document with:
 * - Color-coded zones by type
 * - Highlight active zone when field is selected
 * - Zone labels with field count
 * - Click zone to see extracted fields
 */
import { useState, useEffect, useCallback, useRef } from 'react'

// Zone colors matching VisualZoneEditor
const ZONE_COLORS = {
  header: { bg: 'rgba(59, 130, 246, 0.15)', border: '#3B82F6' },
  vehicle_info: { bg: 'rgba(16, 185, 129, 0.15)', border: '#10B981' },
  member_info: { bg: 'rgba(139, 92, 246, 0.15)', border: '#8B5CF6' },
  buyer_info: { bg: 'rgba(139, 92, 246, 0.15)', border: '#8B5CF6' },
  seller_info: { bg: 'rgba(245, 158, 11, 0.15)', border: '#F59E0B' },
  lot_address: { bg: 'rgba(6, 182, 212, 0.15)', border: '#06B6D4' },
  pickup: { bg: 'rgba(6, 182, 212, 0.15)', border: '#06B6D4' },
  pickup_location: { bg: 'rgba(6, 182, 212, 0.15)', border: '#06B6D4' },
  delivery: { bg: 'rgba(236, 72, 153, 0.15)', border: '#EC4899' },
  pricing: { bg: 'rgba(239, 68, 68, 0.15)', border: '#EF4444' },
  financial_info: { bg: 'rgba(239, 68, 68, 0.15)', border: '#EF4444' },
  dates: { bg: 'rgba(139, 92, 246, 0.15)', border: '#8B5CF6' },
  footer: { bg: 'rgba(107, 114, 128, 0.15)', border: '#6B7280' },
}

function getZoneColor(name) {
  const key = name?.toLowerCase() || ''
  for (const [k, v] of Object.entries(ZONE_COLORS)) {
    if (key.includes(k)) return v
  }
  return { bg: 'rgba(107, 114, 128, 0.15)', border: '#6B7280' }
}

export default function ZoneVisualization({
  zones = [],
  highlightedField = null,
  onZoneClick = null,
  containerWidth = 0,
  containerHeight = 0,
}) {
  const [hoveredZone, setHoveredZone] = useState(null)

  // Find zone containing the highlighted field
  const highlightedZone = highlightedField
    ? zones.find(z => z.fields?.includes(highlightedField))
    : null

  return (
    <div className="absolute inset-0 pointer-events-none">
      {zones.map((zone, index) => {
        const colors = getZoneColor(zone.name)
        const isHighlighted = highlightedZone === zone
        const isHovered = hoveredZone === index

        // Convert percentage coords to pixels
        const left = (zone.x0 / 100) * containerWidth
        const top = (zone.y0 / 100) * containerHeight
        const width = ((zone.x1 - zone.x0) / 100) * containerWidth
        const height = ((zone.y1 - zone.y0) / 100) * containerHeight

        return (
          <div
            key={index}
            className="absolute pointer-events-auto cursor-pointer transition-all duration-200"
            style={{
              left: `${left}px`,
              top: `${top}px`,
              width: `${width}px`,
              height: `${height}px`,
              backgroundColor: isHighlighted
                ? colors.bg.replace('0.15', '0.35')
                : isHovered
                ? colors.bg.replace('0.15', '0.25')
                : colors.bg,
              border: `2px ${isHighlighted ? 'solid' : 'dashed'} ${colors.border}`,
              boxShadow: isHighlighted ? `0 0 8px ${colors.border}80` : 'none',
              zIndex: isHighlighted ? 15 : 10,
            }}
            onMouseEnter={() => setHoveredZone(index)}
            onMouseLeave={() => setHoveredZone(null)}
            onClick={(e) => {
              e.stopPropagation()
              if (onZoneClick) onZoneClick(zone)
            }}
          >
            {/* Zone label */}
            <div
              className="absolute -top-5 left-0 px-1.5 py-0.5 text-xs font-medium text-white rounded-t whitespace-nowrap"
              style={{ backgroundColor: colors.border }}
            >
              {zone.name}
              {zone.fields?.length > 0 && (
                <span className="ml-1 opacity-80">({zone.fields.length})</span>
              )}
            </div>

            {/* Field list tooltip on hover */}
            {isHovered && zone.fields?.length > 0 && (
              <div
                className="absolute top-full left-0 mt-1 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-50"
                style={{ minWidth: '120px', maxWidth: '200px' }}
              >
                <div className="font-medium mb-1">Fields in zone:</div>
                <ul className="space-y-0.5">
                  {zone.fields.slice(0, 5).map((field, i) => (
                    <li key={i} className="truncate">
                      {field.replace(/_/g, ' ')}
                    </li>
                  ))}
                  {zone.fields.length > 5 && (
                    <li className="text-gray-400">+{zone.fields.length - 5} more</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
