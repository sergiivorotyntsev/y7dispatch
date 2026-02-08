// Status indicator and badge components for TestLab

export function StatusIndicator({ status }) {
  const colors = {
    needs_review: 'bg-yellow-500',
    approved: 'bg-green-500',
    reviewed: 'bg-green-500',
    exported: 'bg-green-500',
    failed: 'bg-red-500',
    manual_required: 'bg-orange-500',
    pending: 'bg-gray-400',
    processing: 'bg-blue-500',
  }

  return (
    <span className={'w-3 h-3 rounded-full ' + (colors[status] || 'bg-gray-400')}></span>
  )
}

export function StatusBadge({ status }) {
  const styles = {
    needs_review: 'badge-warning',
    approved: 'badge-success',
    reviewed: 'badge-success',
    exported: 'badge-success',
    failed: 'badge-error',
    manual_required: 'badge-info',
    pending: 'badge-gray',
    processing: 'badge-info',
  }

  const labels = {
    needs_review: 'Needs Review',
    manual_required: 'Manual Required',
  }

  return (
    <span className={'badge ' + (styles[status] || 'badge-gray')}>
      {labels[status] || status}
    </span>
  )
}
