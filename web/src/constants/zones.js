// Zone colors used across the application
export const ZONE_COLORS = {
  vehicle_vin: { bg: 'rgba(59, 130, 246, 0.3)', border: '#3b82f6', name: 'blue' },
  vehicle_year: { bg: 'rgba(16, 185, 129, 0.3)', border: '#10b981', name: 'green' },
  vehicle_make: { bg: 'rgba(245, 158, 11, 0.3)', border: '#f59e0b', name: 'amber' },
  vehicle_model: { bg: 'rgba(239, 68, 68, 0.3)', border: '#ef4444', name: 'red' },
  pickup_address: { bg: 'rgba(139, 92, 246, 0.3)', border: '#8b5cf6', name: 'violet' },
  pickup_city: { bg: 'rgba(236, 72, 153, 0.3)', border: '#ec4899', name: 'pink' },
  pickup_state: { bg: 'rgba(6, 182, 212, 0.3)', border: '#06b6d4', name: 'cyan' },
  pickup_zip: { bg: 'rgba(132, 204, 22, 0.3)', border: '#84cc16', name: 'lime' },
  lot_number: { bg: 'rgba(251, 146, 60, 0.3)', border: '#fb923c', name: 'orange' },
  buyer_id: { bg: 'rgba(168, 85, 247, 0.3)', border: '#a855f7', name: 'purple' },
  sale_date: { bg: 'rgba(20, 184, 166, 0.3)', border: '#14b8a6', name: 'teal' },
  total_amount: { bg: 'rgba(34, 197, 94, 0.3)', border: '#22c55e', name: 'emerald' },
}

// Get color for a field, with fallback for unknown fields
export function getZoneColor(fieldKey) {
  if (ZONE_COLORS[fieldKey]) {
    return ZONE_COLORS[fieldKey]
  }
  // Generate consistent color for unknown fields
  const colors = Object.values(ZONE_COLORS)
  const hash = fieldKey.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

// Array format for components that need it
export const ZONE_COLORS_ARRAY = [
  { bg: 'rgba(239, 68, 68, 0.3)', border: '#ef4444', name: 'red' },
  { bg: 'rgba(34, 197, 94, 0.3)', border: '#22c55e', name: 'green' },
  { bg: 'rgba(59, 130, 246, 0.3)', border: '#3b82f6', name: 'blue' },
  { bg: 'rgba(234, 179, 8, 0.3)', border: '#eab308', name: 'yellow' },
  { bg: 'rgba(168, 85, 247, 0.3)', border: '#a855f7', name: 'purple' },
  { bg: 'rgba(6, 182, 212, 0.3)', border: '#06b6d4', name: 'cyan' },
]
