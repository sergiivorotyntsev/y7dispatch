/**
 * Section 1: Extraction Info Bar
 * Shows document metadata, auction type badge, extraction method, cost, confidence.
 */
function ExtractionInfoBar({ run }) {
  if (!run) return null

  const auctionCode = run.auction_type_code || run.outputs?.auction_type || 'UNKNOWN'
  const extractionMethod = run.outputs?.extraction_method
  const costUsd = run.outputs?.cost_usd
  const confidence = run.extraction_score

  const auctionColors = {
    COPART: 'bg-blue-100 text-blue-800',
    IAA: 'bg-green-100 text-green-800',
    MANHEIM: 'bg-purple-100 text-purple-800',
    UNKNOWN: 'bg-gray-100 text-gray-600',
  }

  const methodLabels = {
    haiku: { label: 'Claude Haiku', color: 'bg-blue-100 text-blue-700' },
    zone_fallback: { label: 'Zone Fallback', color: 'bg-yellow-100 text-yellow-700' },
    all_failed: { label: 'Pattern Only', color: 'bg-gray-100 text-gray-600' },
  }

  const method = methodLabels[extractionMethod] || { label: extractionMethod || 'Unknown', color: 'bg-gray-100 text-gray-600' }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-3 mb-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center space-x-3">
          <span className="text-sm font-medium text-gray-700 truncate max-w-[200px]" title={run.document_filename}>
            {run.document_filename}
          </span>
          <span className={`px-2 py-0.5 rounded text-xs font-bold ${auctionColors[auctionCode] || auctionColors.UNKNOWN}`}>
            {auctionCode}
          </span>
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${method.color}`}>
            {method.label}
          </span>
        </div>
        <div className="flex items-center space-x-4 text-xs text-gray-500">
          {costUsd != null && (
            <span title="Extraction cost">
              ${typeof costUsd === 'number' ? costUsd.toFixed(4) : costUsd}
            </span>
          )}
          {confidence != null && (
            <span title="Extraction confidence">
              {(confidence * 100).toFixed(0)}% confidence
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

export default ExtractionInfoBar
