import useDocuments from '../hooks/useDocuments'
import ExportPreviewModal from '../components/ExportPreviewModal'
import DocumentsHeader from '../components/documents/DocumentsHeader'
import DocumentsFilters from '../components/documents/DocumentsFilters'
import DocumentsBatchBar from '../components/documents/DocumentsBatchBar'
import DocumentsTable from '../components/documents/DocumentsTable'
import { UploadModal, HoldModal, BatchHoldModal, BatchPostModal } from '../components/documents/DocumentsModals'

/**
 * Documents Page - Production Workflow
 *
 * Lists documents ready for Central Dispatch export.
 * State and handlers live in useDocuments hook.
 * Sub-components receive focused props.
 */
function Documents() {
  const d = useDocuments()

  return (
    <div className="p-6">
      <DocumentsHeader
        stats={d.stats}
        onUploadClick={() => d.setShowUpload(true)}
      />

      <DocumentsBatchBar
        selectedCount={d.selectedDocs.size}
        eligibility={d.getBatchEligibility()}
        batchOperating={d.batchOperating}
        batchPosting={d.batchPosting}
        batchOpResult={d.batchOpResult}
        onApprove={d.handleBatchApprove}
        onExportPreflight={d.handleBatchPostPreflight}
        onHold={() => d.setShowBatchHold(true)}
        onArchive={d.handleBatchArchive}
        onAutoAssignWarehouse={d.handleAutoAssignWarehouse}
        onClearSelection={() => d.setSelectedDocs(new Set())}
        onDismissResult={() => d.setBatchOpResult(null)}
      />

      {d.error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          <strong>Error:</strong> {d.error}
          <button onClick={() => d.setError(null)} className="ml-4 text-sm underline">Dismiss</button>
        </div>
      )}

      <DocumentsFilters
        search={d.search}
        onSearchChange={(val) => { d.setSearch(val); d.setPagination(p => ({ ...p, page: 1 })) }}
        filter={d.filter}
        onFilterChange={(f) => { d.setFilter(f); d.setPagination(p => ({ ...p, page: 1 })) }}
        auctionTypes={d.auctionTypes}
        sortConfig={d.sortConfig}
        onSortChange={d.setSortConfig}
        pagination={d.pagination}
        onLimitChange={(limit) => d.setPagination(p => ({ ...p, limit, page: 1 }))}
        onRefresh={d.fetchDocuments}
        onExpandAll={d.expandAll}
        onCollapseAll={d.collapseAll}
      />

      <UploadModal
        show={d.showUpload}
        auctionTypes={d.auctionTypes}
        selectedAuctionType={d.selectedAuctionType}
        onAuctionTypeChange={d.setSelectedAuctionType}
        uploadFile={d.uploadFile}
        onFileChange={(file) => { d.setUploadFile(file); d.setUploadResult(null) }}
        uploading={d.uploading}
        uploadResult={d.uploadResult}
        onUpload={d.handleUpload}
        onClose={() => { d.setShowUpload(false); d.setUploadFile(null); d.setUploadResult(null) }}
        onNavigate={(path) => { d.setShowUpload(false); d.navigate(path) }}
      />

      <DocumentsTable
        loading={d.loading}
        documents={d.documents}
        docExtractions={d.docExtractions}
        warehouses={d.warehouses}
        selectedDocs={d.selectedDocs}
        collapsedDates={d.collapsedDates}
        editingPrice={d.editingPrice}
        extractingDocId={d.extractingDocId}
        exportingDocId={d.exportingDocId}
        pagination={d.pagination}
        onRowClick={d.handleRowClick}
        onToggleSelect={d.toggleSelectDoc}
        onToggleSelectAll={d.toggleSelectAll}
        onToggleDate={d.toggleDate}
        onWarehouseChange={d.handleWarehouseChange}
        onEditPrice={d.handlePriceUpdate}
        onSetEditingPrice={d.setEditingPrice}
        onRunExtraction={d.handleRunExtraction}
        onExportPreview={d.setShowExportPreview}
        onReleaseHold={d.handleReleaseHold}
        onHold={d.setHoldModal}
        onArchive={d.handleArchive}
        onDelete={d.handleDelete}
        onPageChange={(page) => d.setPagination(p => ({ ...p, page }))}
        onUploadClick={() => d.setShowUpload(true)}
        getSourceDisplay={d.getSourceDisplay}
        navigate={d.navigate}
      />

      {/* Export Preview Modal */}
      {d.showExportPreview && (
        <ExportPreviewModal
          extractionId={d.showExportPreview.extractionId}
          documentId={d.showExportPreview.documentId}
          onClose={() => d.setShowExportPreview(null)}
          onExport={(result) => {
            d.fetchDocuments()
            if (result.posted > 0) d.setShowExportPreview(null)
          }}
        />
      )}

      <HoldModal
        holdModal={d.holdModal}
        holdReason={d.holdReason}
        holdNote={d.holdNote}
        onReasonChange={d.setHoldReason}
        onNoteChange={d.setHoldNote}
        onConfirm={d.handleSetHold}
        onCancel={() => { d.setHoldModal(null); d.setHoldReason('awaiting_gate_pass'); d.setHoldNote('') }}
      />

      <BatchHoldModal
        show={d.showBatchHold}
        holdCount={d.getBatchEligibility().holdDocIds.length}
        batchHoldReason={d.batchHoldReason}
        batchHoldNote={d.batchHoldNote}
        batchOperating={d.batchOperating}
        onReasonChange={d.setBatchHoldReason}
        onNoteChange={d.setBatchHoldNote}
        onConfirm={d.handleBatchHoldConfirm}
        onCancel={() => { d.setShowBatchHold(false); d.setBatchHoldReason('awaiting_gate_pass'); d.setBatchHoldNote('') }}
      />

      <BatchPostModal
        show={d.showBatchPost}
        batchPosting={d.batchPosting}
        batchPreflight={d.batchPreflight}
        batchResult={d.batchResult}
        onPost={d.handleBatchPost}
        onClose={d.closeBatchPostModal}
      />
    </div>
  )
}

export default Documents
