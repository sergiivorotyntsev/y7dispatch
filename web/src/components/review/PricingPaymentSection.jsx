import { useState } from 'react'
import api from '../../api'

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
  runId, warehouseId, hasPickupLocation, hasDeliveryLocation,
  distanceMiles,
}) {
  const codNum = parseFloat(codAmount) || 0
  const totalNum = parseFloat(finalPrice) || parseFloat(pricing?.suggested_price) || 0
  const balanceAmount = Math.max(0, totalNum - codNum)

  // Live $/mile calculation
  const ratePerMile = totalNum > 0 && distanceMiles > 0
    ? (totalNum / distanceMiles).toFixed(2)
    : null

  // CD Market Intelligence state
  const [cdPriceData, setCdPriceData] = useState(null)
  const [cdPriceError, setCdPriceError] = useState(null)
  const [loadingCDPrice, setLoadingCDPrice] = useState(false)

  const canFetchCDPrice = runId && (hasPickupLocation !== false) && (hasDeliveryLocation !== false || warehouseId)

  async function handleFetchCDPrice() {
    if (!runId) return
    setLoadingCDPrice(true)
    setCdPriceError(null)
    setCdPriceData(null)
    try {
      const data = await api.getCDMarketPrice(runId, warehouseId)
      if (data.error) {
        setCdPriceError(data.error)
      } else {
        setCdPriceData(data)
      }
    } catch (err) {
      setCdPriceError(err.message || 'Failed to fetch CD pricing')
    } finally {
      setLoadingCDPrice(false)
    }
  }

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

      {/* CD Market Intelligence — Get Price button */}
      <div className="mb-4">
        <button
          onClick={handleFetchCDPrice}
          disabled={loadingCDPrice || !canFetchCDPrice}
          className="btn btn-secondary text-sm w-full"
          title={!canFetchCDPrice ? 'Set pickup location and warehouse first' : ''}
        >
          {loadingCDPrice ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin rounded-full h-3 w-3 border-b-2 border-gray-600"></span>
              Fetching CD Pricing...
            </span>
          ) : (
            'Get Price from Central Dispatch'
          )}
        </button>
        {!canFetchCDPrice && !loadingCDPrice && (
          <p className="text-xs text-gray-400 mt-1">Requires pickup location and delivery warehouse</p>
        )}

        {/* CD Price Result */}
        {cdPriceData && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded">
            <div className="flex justify-between items-start mb-2">
              <h4 className="text-sm font-medium text-green-800">CD Market Intelligence</h4>
              <span className="text-xs text-green-600">{cdPriceData.data_points} similar loads</span>
            </div>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <div>
                <span className="text-xs text-green-700">Predicted Price</span>
                <div className="text-lg font-bold text-green-900">${cdPriceData.predicted_price?.toFixed(0)}</div>
              </div>
              {cdPriceData.price_range && (
                <div>
                  <span className="text-xs text-green-700">Range</span>
                  <div className="text-sm font-medium text-green-800">
                    ${cdPriceData.price_range.low?.toFixed(0)} - ${cdPriceData.price_range.high?.toFixed(0)}
                  </div>
                </div>
              )}
            </div>
            <div className="flex gap-4 text-xs text-green-700 mb-2">
              {cdPriceData.price_per_mile && <span>$/mi: {cdPriceData.price_per_mile.toFixed(2)}</span>}
              {cdPriceData.distance_miles && <span>Distance: {Math.round(cdPriceData.distance_miles)} mi</span>}
              {cdPriceData.avg_dispatch && <span>Avg Dispatch: ${cdPriceData.avg_dispatch.toFixed(0)}</span>}
            </div>
            <button
              onClick={() => setFinalPrice(String(cdPriceData.predicted_price?.toFixed(0)))}
              className="btn btn-primary text-xs py-1 px-3"
            >
              Use This Price
            </button>
          </div>
        )}

        {/* CD Price Error */}
        {cdPriceError && (
          <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded">
            <p className="text-sm font-medium text-yellow-800 mb-1">CD Pricing Error</p>
            <pre className="text-xs text-yellow-700 whitespace-pre-wrap break-all font-mono">
              {typeof cdPriceError === 'object' ? JSON.stringify(cdPriceError, null, 2) : cdPriceError}
            </pre>
          </div>
        )}
      </div>

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
          <div className="flex items-center gap-3 mt-1">
            {pricing?.suggested_price && !finalPrice && (
              <p className="text-xs text-gray-400">Will use recommended: ${pricing.suggested_price.toFixed(0)}</p>
            )}
            {ratePerMile && (
              <span className="text-xs font-medium text-primary-700 bg-primary-50 px-1.5 py-0.5 rounded">
                ${ratePerMile}/mi
              </span>
            )}
            {distanceMiles && (
              <span className="text-xs text-gray-400">{Math.round(distanceMiles)} mi</span>
            )}
          </div>
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
