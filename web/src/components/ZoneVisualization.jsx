/**
 * ZoneVisualization - Read-only zone overlay for Review page
 *
 * Shows extraction zones overlaid on PDF/document with:
 * - Color-coded zones by type
 * - Highlight active zone when field is selected
 * - Zone labels with field count
 * - Click zone to see extracted fields
 */
import { useState } from 'react'

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

const DEFAULT_COLOR = { bg: 'rgba(107, 114, 128, 0.15)', border: '#6B7280' }

function getZoneColor(name) {
  if (!name) return DEFAULT_COLOR
  const key = name.toLowerCase()
  for (const [k, v] of Object.entries(ZONE_COLORS)) {
    if (key.includes(k)) return v
  }
  return DEFAULT_COLOR
}

// Safely get fields array - extract field keys from field objects or strings
function getZoneFields(zone) {
  if (!zone || !zone.fields) return []
  if (!Array.isArray(zone.fields)) return []

  // Fields can be objects with {key: string} or just strings
  return zone.fields.map(f => {
    if (typeof f === 'string') return f
    if (f && typeof f === 'object' && f.key) return f.key
    return null
  }).filter(Boolean)
}

export default function ZoneVisualization({
  zones = [],
  highlightedField = null,
  onZoneClick = null,
}) {
  const [hoveredZone, setHoveredZone] = useState(null)

  // Find zone index containing the highlighted field (by name comparison, not reference)
  const highlightedZoneIndex = highlightedField
    ? zones.findIndex(z => {
        const fields = getZoneFields(z)
        return fields.some(f => f === highlightedField)
      })
    : -1

  // Filter valid zones (must have coordinates)
  const validZones = zones.filter(zone =>
    zone &&
    typeof zone.x0 === 'number' &&
    typeof zone.y0 === 'number' &&
    typeof zone.x1 === 'number' &&
    typeof zone.y1 === 'number'
  )

  return (
    <div className="absolute inset-0 pointer-events-none">
      {validZones.map((zone, index) => {
        const colors = getZoneColor(zone.name)
        const isHighlighted = highlightedZoneIndex === index
        const isHovered = hoveredZone === index
        const fields = getZoneFields(zone)

        // Adjust opacity for highlighting
        let bgColor = colors.bg
        if (isHighlighted) {
          bgColor = colors.bg.replace('0.15', '0.35')
        } else if (isHovered) {
          bgColor = colors.bg.replace('0.15', '0.25')
        }

        return (
          <div
            key={`zone-${index}-${zone.name || 'unnamed'}`}
            className="absolute pointer-events-auto cursor-pointer transition-all duration-200"
            style={{
              left: `${zone.x0}%`,
              top: `${zone.y0}%`,
              width: `${zone.x1 - zone.x0}%`,
              height: `${zone.y1 - zone.y0}%`,
              backgroundColor: bgColor,
              border: `2px ${isHighlighted ? 'solid' : 'dashed'} ${colors.border}`,
              boxShadow: isHighlighted ? `0 0 8px ${colors.border}80` : 'none',
              zIndex: isHighlighted ? 15 : 10,
            }}
            onMouseEnter={() => setHoveredZone(index)}
            onMouseLeave={() => setHoveredZone(null)}
            onClick={(e) => {
              e.stopPropagation()
              if (onZoneClick) {
                try {
                  onZoneClick(zone)
                } catch (err) {
                  console.error('Zone click error:', err)
                }
              }
            }}
          >
            {/* Zone label */}
            <div
              className="absolute -top-5 left-0 px-1.5 py-0.5 text-xs font-medium text-white rounded-t whitespace-nowrap"
              style={{ backgroundColor: colors.border }}
            >
              {zone.name || 'Zone'}
              {fields.length > 0 && (
                <span className="ml-1 opacity-80">({fields.length})</span>
              )}
            </div>

            {/* Field list tooltip on hover */}
            {isHovered && fields.length > 0 && (
              <div
                className="absolute top-full left-0 mt-1 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-50"
                style={{ minWidth: '120px', maxWidth: '200px' }}
              >
                <div className="font-medium mb-1">Fields in zone:</div>
                <ul className="space-y-0.5">
                  {fields.slice(0, 5).map((field, i) => (
                    <li key={i} className="truncate">
                      {typeof field === 'string' ? field.replace(/_/g, ' ') : String(field)}
                    </li>
                  ))}
                  {fields.length > 5 && (
                    <li className="text-gray-400">+{fields.length - 5} more</li>
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
