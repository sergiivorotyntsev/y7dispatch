/**
 * Section 5: Dates
 * Available date (default today, Manheim release exception), expiration (+30d), desired delivery.
 */
function DatesSection({
  availableDate, setAvailableDate,
  expirationDate, setExpirationDate,
  desiredDeliveryDate, setDesiredDeliveryDate,
  manheimReleaseDate, auctionType,
}) {
  const isManheim = auctionType?.toUpperCase() === 'MANHEIM'
  const hasNoRelease = manheimReleaseDate === 'NO_RELEASE_DOCUMENT'
  const isAvailableNow = manheimReleaseDate === 'AVAILABLE_NOW'
  const hasReleaseDate = manheimReleaseDate && !hasNoRelease && !isAvailableNow

  // Auto-calculate expiration when available date changes
  function handleAvailableDateChange(dateStr) {
    setAvailableDate(dateStr)
    if (dateStr) {
      const d = new Date(dateStr)
      d.setDate(d.getDate() + 30)
      setExpirationDate(d.toISOString().split('T')[0])
    }
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        Dates
      </h3>

      {/* Manheim release warning */}
      {isManheim && hasNoRelease && (
        <div className="mb-3 p-3 bg-yellow-50 border border-yellow-300 rounded">
          <div className="flex items-start">
            <svg className="w-4 h-4 text-yellow-500 mr-2 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <p className="text-sm font-medium text-yellow-800">No Onsite Vehicle Release</p>
              <p className="text-xs text-yellow-700 mt-1">
                Contact the seller to request an Onsite Vehicle Release document.
                Available date defaults to today.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Manheim release date info */}
      {isManheim && hasReleaseDate && (
        <div className="mb-3 p-3 bg-blue-50 border border-blue-200 rounded">
          <p className="text-xs text-blue-700">
            Manheim release date detected: <span className="font-medium">{manheimReleaseDate}</span>.
            Available date set to release date.
          </p>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {/* Available Date */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Date Available to Ship <span className="text-red-500">*</span>
          </label>
          <input
            type="date"
            value={availableDate}
            onChange={(e) => handleAvailableDateChange(e.target.value)}
            className="form-input w-full text-sm"
          />
          <p className="text-xs text-gray-400 mt-1">
            {isManheim && hasReleaseDate ? 'From release document' : 'Default: today'}
          </p>
        </div>

        {/* Expiration Date */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Expiration Date
          </label>
          <input
            type="date"
            value={expirationDate}
            className="form-input w-full text-sm bg-gray-50"
            readOnly
          />
          <p className="text-xs text-gray-400 mt-1">Auto: available + 30 days</p>
        </div>

        {/* Desired Delivery Date */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Desired Delivery Date
            <span className="ml-1 text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="date"
            value={desiredDeliveryDate}
            onChange={(e) => setDesiredDeliveryDate(e.target.value)}
            className="form-input w-full text-sm"
          />
        </div>
      </div>
    </div>
  )
}

export default DatesSection
