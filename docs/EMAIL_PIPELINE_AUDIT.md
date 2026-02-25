# Email Pipeline Audit Report
**Generated:** 2026-02-24
**Branch:** claude/create-claude-md-OomNZ

## Summary

| Metric | Count |
|--------|-------|
| Total emails in log | 216 |
| Processed (created documents) | 145 |
| Skipped | 71 |
| Documents created | 145 |
| Extraction runs | 156 |
| DLQ entries | 0 |

**Effective conversion rate: 100%** (all emails with PDF attachments created documents)

## Skip Breakdown

| Skip Reason | Count | % of Skipped |
|-------------|-------|-------------|
| Thread reply without PDF | 69 | 97.2% |
| No PDF attachments | 2 | 2.8% |
| Banking/wire PDFs only | 0 | 0% |
| Processing error | 0 | 0% |
| Duplicate message_id | 0 | 0% |

## Analysis

The apparent 33% loss (216 emails - 145 documents = 71) is **NOT a pipeline defect**.

All 71 skipped emails are either:
1. **Reply emails** (69): Thread replies to existing emails (Re: ...) that don't contain new PDF attachments.
   These are correctly identified and skipped by `_is_thread_reply_without_pdf()` in email_worker.py.
2. **No-attachment emails** (2): Emails with no PDF attachments at all.

## Extraction Status

| Status | Count |
|--------|-------|
| needs_review | 134 |
| approved | 8 |
| exported | 7 |
| failed | 4 |
| manual_required | 2 |
| pending | 1 |

## Conclusion

The email-to-document pipeline is working correctly. No emails with valid PDF attachments
are being lost. The skip logic for thread replies and no-attachment emails is functioning
as designed.
