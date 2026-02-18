/**
 * Section 6: Pricing and Payment
 * Market intel pricing, final price, COD, balance, payment methods/terms.
 */
function PricingPaymentSection({
  pricing, pricingLoading, urgency, handleUrgencyChange, finalPrice, setFinalPrice,
  codAmount, setCodAmount,
  codPaymentMethod, setCodPaymentMethod,
  codPaymentLocation, setCodPaymentLocation,
  balancePaymentMethod, setBalancePaymentMethod,
  balancePaymentTime, setBalancePaymentTime,
  balanceTermsBeginOn, setBalanceTermsBeginOn,
}) {
  const codNum = parseFloat(codAmount) || 0
  const totalNum = parseFloat(finalPrice) || parseFloat(pricing?.suggested_price) || 0
  const balanceAmount = Math.max(0, totalNum - codNum)

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center">
        <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        Pricing and Payment
      </h3>

      {/* Loading state */}
      {pricingLoading && (
        <div className="flex items-center text-gray-500 mb-3">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600 mr-2"></div>
          <span className="text-sm">Loading pricing...</span>
        </div>
      )}

      {/* Market Intelligence Data */}
      {pricing && !pricingLoading && (
        <>
          <div className="flex justify-between items-start mb-3">
            <p className="text-xs text-gray-500">
              {pricing.pickup_location && pricing.delivery_location
                ? `${pricing.pickup_location} → ${pricing.delivery_location}`
                : 'Based on route and vehicle'}
              {pricing.distance_miles > 0 && ` (${Math.round(pricing.distance_miles)} mi)`}
            </p>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              pricing.source === 'CD_MARKET_INTELLIGENCE' || pricing.price_source === 'market_intelligence'
                ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
            }`}>
              {pricing.source === 'CD_MARKET_INTELLIGENCE' || pricing.price_source === 'market_intelligence'
                ? `CD Market Intel (${pricing.data_points || 0} pts)`
                : pricing.source === 'MANUAL_REQUIRED' || pricing.price_source === 'manual_required'
                  ? 'Manual Required'
                  : pricing.source || 'Default'}
            </span>
          </div>

          {/* Market range */}
          {(pricing.avg_dispatch || pricing.avg_listing) && (
            <div className="grid grid-cols-3 gap-3 mb-3">
              <div className="text-center p-2 bg-gray-50 rounded">
                <div className="text-xs text-gray-500">Avg Dispatch</div>
                <div className="text-sm font-bold">${pricing.avg_dispatch?.toFixed(0) || '---'}</div>
              </div>
              <div className="text-center p-2 bg-gray-50 rounded">
                <div className="text-xs text-gray-500">Avg Listing</div>
                <div className="text-sm font-bold">${pricing.avg_listing?.toFixed(0) || '---'}</div>
              </div>
              <div className="text-center p-2 bg-gray-50 rounded">
                <div className="text-xs text-gray-500">Spread</div>
                <div className="text-sm font-bold">${pricing.spread?.toFixed(0) || '---'}</div>
              </div>
            </div>
          )}

          {(pricing.source === 'MANUAL_REQUIRED' || pricing.price_source === 'manual_required') && (
            <div className="mb-3 p-3 bg-yellow-50 border border-yellow-200 rounded">
              <p className="text-sm text-yellow-800">No market data available for this route. Enter carrier price manually.</p>
            </div>
          )}
        </>
      )}

      {/* Amount to Pay Carrier + Urgency */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Amount to Pay Carrier <span className="text-red-500">*</span>
          </label>
          <div className="flex items-center gap-2">
            <span className="text-gray-500">$</span>
            <input
              type="number"
              value={finalPrice}
              onChange={(e) => setFinalPrice(e.target.value)}
              placeholder={pricing?.suggested_price ? `Suggested: ${pricing.suggested_price.toFixed(0)}` : 'Enter price'}
              className={`form-input flex-1 text-sm ${
                !finalPrice && (pricing?.source === 'MANUAL_REQUIRED' || pricing?.price_source === 'manual_required')
                  ? 'border-red-300 bg-red-50' : ''
              }`}
              step="0.01"
              min="0"
            />
          </div>
          {pricing?.suggested_price && !finalPrice && (
            <p className="text-xs text-gray-400 mt-1">Will use recommended: ${pricing.suggested_price.toFixed(0)}</p>
          )}
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Urgency</label>
          <select value={urgency} onChange={(e) => handleUrgencyChange(e.target.value)} className="form-select w-full text-sm">
            <option value="STANDARD">Standard (1.0x)</option>
            <option value="PRIORITY">Priority (1.12x)</option>
            <option value="URGENT">Urgent (1.25x)</option>
          </select>
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-gray-200 my-4"></div>

      {/* COD Section */}
      <div className="mb-4">
        <h4 className="text-xs font-medium text-gray-700 mb-2">COP/COD (Cash on Delivery)</h4>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">COD Amount</label>
            <div className="flex items-center gap-1">
              <span className="text-gray-400 text-sm">$</span>
              <input
                type="number"
                value={codAmount}
                onChange={(e) => setCodAmount(e.target.value)}
                className="form-input w-full text-sm"
                step="0.01"
                min="0"
                placeholder="0.00"
              />
            </div>
          </div>
          {codNum > 0 && (
            <>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Payment Method</label>
                <select value={codPaymentMethod} onChange={(e) => setCodPaymentMethod(e.target.value)} className="form-select w-full text-sm">
                  <option value="CASH_CERTIFIED_FUNDS">Cash/Certified Funds</option>
                  <option value="CHECK">Check</option>
                  <option value="CASH">Cash</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Location</label>
                <select value={codPaymentLocation} onChange={(e) => setCodPaymentLocation(e.target.value)} className="form-select w-full text-sm">
                  <option value="DELIVERY">Delivery</option>
                  <option value="PICKUP">Pickup</option>
                </select>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Balance Section */}
      <div>
        <h4 className="text-xs font-medium text-gray-700 mb-2">Balance</h4>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Balance Amount</label>
            <div className="flex items-center gap-1">
              <span className="text-gray-400 text-sm">$</span>
              <input
                type="number"
                value={balanceAmount.toFixed(2)}
                className="form-input w-full text-sm bg-gray-50"
                readOnly
              />
            </div>
            <p className="text-xs text-gray-400 mt-1">Auto: total - COD</p>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Payment Method</label>
            <select value={balancePaymentMethod} onChange={(e) => setBalancePaymentMethod(e.target.value)} className="form-select w-full text-sm">
              <option value="CERTIFIED_FUNDS">Certified Funds</option>
              <option value="CHECK">Check</option>
              <option value="ACH">ACH</option>
              <option value="CASH">Cash</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Payment Time</label>
            <select value={balancePaymentTime} onChange={(e) => setBalancePaymentTime(e.target.value)} className="form-select w-full text-sm">
              <option value="IMMEDIATELY">Immediately</option>
              <option value="2_BUSINESS_DAYS_QUICK_PAY">2 Business Days (Quick Pay)</option>
              <option value="5_BUSINESS_DAYS">5 Business Days</option>
              <option value="15_BUSINESS_DAYS">15 Business Days</option>
              <option value="30_BUSINESS_DAYS">30 Business Days</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Terms Begin On</label>
            <select value={balanceTermsBeginOn} onChange={(e) => setBalanceTermsBeginOn(e.target.value)} className="form-select w-full text-sm">
              <option value="RECEIVING_SIGNED_BOL">Receiving Signed BOL</option>
              <option value="DELIVERY">Delivery</option>
              <option value="PICKUP">Pickup</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PricingPaymentSection
