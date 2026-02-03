"""
Background Workers Module

Workers handle asynchronous tasks like:
- Email polling
- Export retries
- Batch processing
"""

from api.workers.email_worker import EmailWorker

__all__ = ["EmailWorker"]
