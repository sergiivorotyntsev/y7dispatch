import { useState, useCallback } from 'react'

/**
 * CopyableCell — click-to-copy table cell content.
 *
 * Renders text that copies to clipboard on click.
 * Shows a clipboard icon on hover, checkmark after copy.
 * Calls e.stopPropagation() to prevent row navigation.
 */
export default function CopyableCell({ value, mono = false }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback((e) => {
    e.stopPropagation()
    if (!value) return
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }).catch(() => {})
  }, [value])

  if (!value) return <span className="text-gray-400">-</span>

  return (
    <span
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Click to copy'}
      className={`inline-flex items-center gap-1 cursor-pointer rounded px-1 -mx-1 transition-colors hover:bg-blue-50 group ${
        mono ? 'font-mono' : ''
      }`}
    >
      <span className="text-xs">{value}</span>
      {copied ? (
        <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="w-3 h-3 text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      )}
    </span>
  )
}
