import { useState } from 'react'
import api from '../../api'

/**
 * Manual Entry Banner
 *
 * Shown when extraction run status is manual_required.
 * Provides instructions and a "Try Vision Extract" button
 * that calls Claude Haiku Vision API on the scanned PDF.
 */
export default function ManualEntryBanner({ runId, onVisionResult }) {
  const [visionLoading, setVisionLoading] = useState(false)
  const [visionError, setVisionError] = useState(null)
  const [visionDone, setVisionDone] = useState(false)

  async function handleVisionExtract() {
    setVisionLoading(true)
    setVisionError(null)
    try {
      const result = await api.visionExtract(runId)
      if (result.error) {
        setVisionError(result.error)
      } else {
        setVisionDone(true)
        onVisionResult(result.fields)
      }
    } catch (err) {
      setVisionError(err.message)
    } finally {
      setVisionLoading(false)
    }
  }

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
      <div className="flex items-start gap-3">
        <div className="text-amber-600 text-xl mt-0.5">&#9888;</div>
        <div className="flex-1">
          <h3 className="font-semibold text-amber-800">Manual Entry Required (Scanned PDF)</h3>
          <p className="text-sm text-amber-700 mt-1">
            This document has no extractable text. You can:
          </p>
          <ol className="text-sm text-amber-700 mt-1 ml-4 list-decimal space-y-0.5">
            <li>View the PDF and fill in fields manually</li>
            <li>Use Vision Extract — AI reads the scanned image</li>
          </ol>

          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleVisionExtract}
              disabled={visionLoading || visionDone}
              className={`px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors ${
                visionDone
                  ? 'bg-green-100 text-green-700 border border-green-300'
                  : 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50'
              }`}
            >
              {visionLoading ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Running Vision Extract...
                </>
              ) : visionDone ? (
                <>&#10003; Vision fields loaded — review below</>
              ) : (
                <>&#128065; Try Vision Extract</>
              )}
            </button>

            {!visionDone && (
              <span className="text-xs text-amber-600">
                Results still need your review
              </span>
            )}
          </div>

          {visionError && (
            <div className="mt-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
              Vision extract failed: {visionError}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
