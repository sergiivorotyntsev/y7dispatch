/**
 * Parse a UTC timestamp from SQLite (no Z suffix) into a proper Date object.
 * SQLite CURRENT_TIMESTAMP stores UTC but without the Z suffix,
 * so JS `new Date()` misinterprets it as local time.
 *
 * Also handles RFC 2822 email dates (e.g. "Wed, 25 Feb 2026 16:06:37 +0100")
 * which already contain timezone info and should NOT get a Z suffix.
 */
export function parseUTCDate(dateStr) {
  if (!dateStr) return null
  if (typeof dateStr !== 'string') return new Date(dateStr)
  // RFC 2822 dates contain day-of-week comma or +/- timezone offset — parse directly
  if (/[+-]\d{4}\s*$/.test(dateStr) || /^[A-Z][a-z]{2},/.test(dateStr)) {
    return new Date(dateStr)
  }
  return new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z')
}

/**
 * Format a UTC timestamp to locale string for display.
 */
export function formatTimestamp(dateStr, options) {
  const d = parseUTCDate(dateStr)
  if (!d || isNaN(d.getTime())) return '-'
  return d.toLocaleString('en-US', options || {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/**
 * Format a UTC timestamp as relative time ago.
 */
export function formatTimeAgo(dateStr) {
  const d = parseUTCDate(dateStr)
  if (!d || isNaN(d.getTime())) return null
  const diff = Date.now() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
