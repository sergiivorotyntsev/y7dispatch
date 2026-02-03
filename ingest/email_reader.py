"""Email reader with IMAP and OAuth2/Graph support."""

import email
import hashlib
import imaplib
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional

from core.config import EmailConfig

logger = logging.getLogger(__name__)


@dataclass
class Attachment:
    """Email attachment data."""

    filename: str
    content_type: str
    content: bytes
    size: int
    is_inline: bool = False

    @property
    def hash(self) -> str:
        """SHA256 hash of attachment content."""
        return hashlib.sha256(self.content).hexdigest()

    @property
    def is_pdf(self) -> bool:
        """Check if attachment is a PDF."""
        return self.content_type == "application/pdf" or self.filename.lower().endswith(".pdf")


@dataclass
class EmailMessage:
    """Parsed email message."""

    message_id: str
    subject: str
    sender: str
    date: Optional[datetime]
    body_text: str
    body_html: str
    attachments: list[Attachment] = field(default_factory=list)

    # Threading headers
    in_reply_to: Optional[str] = None
    references: Optional[str] = None

    # Raw data for debugging
    raw_headers: dict = field(default_factory=dict)
    uid: Optional[str] = None

    @property
    def thread_root_id(self) -> str:
        """Get the root message ID of the email thread."""
        if self.references:
            refs = self.references.strip().split()
            if refs:
                return refs[0].strip("<>")
        if self.in_reply_to:
            return self.in_reply_to.strip("<>")
        return (
            self.message_id.strip("<>")
            if self.message_id
            else f"unknown-{datetime.utcnow().isoformat()}"
        )

    @property
    def pdf_attachments(self) -> list[Attachment]:
        """Get only PDF attachments (non-inline)."""
        return [a for a in self.attachments if a.is_pdf and not a.is_inline]


class BaseEmailReader(ABC):
    """Abstract base class for email readers."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to email server."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to email server."""
        pass

    @abstractmethod
    def list_unseen(self) -> list[str]:
        """Get list of unseen message UIDs."""
        pass

    @abstractmethod
    def fetch_message(self, uid: str) -> Optional[EmailMessage]:
        """Fetch a single message by UID."""
        pass

    @abstractmethod
    def mark_seen(self, uid: str) -> bool:
        """Mark a message as seen/read."""
        pass

    @abstractmethod
    def validate_connection(self) -> tuple[bool, str]:
        """Validate that connection can be established. Returns (success, message)."""
        pass

    def fetch_unseen(self) -> Iterator[EmailMessage]:
        """Fetch all unseen messages."""
        uids = self.list_unseen()
        logger.info(f"Found {len(uids)} unseen messages")

        for uid in uids:
            msg = self.fetch_message(uid)
            if msg:
                yield msg

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


class IMAPEmailReader(BaseEmailReader):
    """IMAP email reader with basic auth or OAuth2 XOAUTH2."""

    def __init__(self, config: EmailConfig):
        self.config = config
        self._connection: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> None:
        """Connect to IMAP server."""
        logger.info(f"Connecting to IMAP server: {self.config.imap_server}:{self.config.imap_port}")

        self._connection = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port)

        # Try OAuth2 XOAUTH2 if we have client credentials
        if self.config.client_id and self.config.client_secret:
            access_token = self._get_oauth2_token()
            auth_string = self._build_xoauth2_string(self.config.address, access_token)
            self._connection.authenticate("XOAUTH2", lambda x: auth_string.encode())
        else:
            # Basic auth
            self._connection.login(self.config.address, self.config.password)

        # Select folder
        status, _ = self._connection.select(self.config.folder)
        if status != "OK":
            raise ConnectionError(f"Failed to select folder: {self.config.folder}")

        logger.info(f"Connected to IMAP, selected folder: {self.config.folder}")

    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self._connection:
            try:
                self._connection.close()
                self._connection.logout()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._connection = None

    def _get_oauth2_token(self) -> str:
        """Get OAuth2 access token for M365/Azure AD."""
        import requests

        token_url = f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": "https://outlook.office365.com/.default",
            "grant_type": "client_credentials",
        }

        response = requests.post(token_url, data=data, timeout=30)
        response.raise_for_status()
        return response.json()["access_token"]

    @staticmethod
    def _build_xoauth2_string(user: str, token: str) -> str:
        """Build XOAUTH2 authentication string."""
        return f"user={user}\x01auth=Bearer {token}\x01\x01"

    def list_unseen(self) -> list[str]:
        """Get list of unseen message UIDs."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        # Build search criteria
        criteria = ["UNSEEN"]

        if self.config.from_filter:
            criteria.append(f'FROM "{self.config.from_filter}"')

        if self.config.subject_filter:
            criteria.append(f'SUBJECT "{self.config.subject_filter}"')

        search_str = " ".join(criteria)
        logger.debug(f"IMAP search: {search_str}")

        status, data = self._connection.uid("SEARCH", None, search_str)
        if status != "OK":
            logger.error(f"IMAP search failed: {status}")
            return []

        uids = data[0].decode().split() if data[0] else []
        return uids

    def fetch_message(self, uid: str) -> Optional[EmailMessage]:
        """Fetch and parse a single message by UID."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        status, data = self._connection.uid("FETCH", uid, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            logger.error(f"Failed to fetch message UID {uid}")
            return None

        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        return self._parse_message(msg, uid)

    def _parse_message(self, msg: email.message.Message, uid: str) -> EmailMessage:
        """Parse email.message.Message into EmailMessage dataclass."""

        # Decode subject
        subject_parts = decode_header(msg.get("Subject", ""))
        subject = ""
        for part, encoding in subject_parts:
            if isinstance(part, bytes):
                subject += part.decode(encoding or "utf-8", errors="replace")
            else:
                subject += part

        # Parse date
        date_str = msg.get("Date")
        date = None
        if date_str:
            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                pass

        # Extract body and attachments
        body_text = ""
        body_html = ""
        attachments = []

        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            filename = part.get_filename()

            # Check if inline
            is_inline = "inline" in content_disposition.lower()

            if filename:
                # It's an attachment
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append(
                        Attachment(
                            filename=self._decode_filename(filename),
                            content_type=content_type,
                            content=payload,
                            size=len(payload),
                            is_inline=is_inline,
                        )
                    )
            elif content_type == "text/plain" and not is_inline:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_text += payload.decode(charset, errors="replace")
            elif content_type == "text/html" and not is_inline:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_html += payload.decode(charset, errors="replace")

        return EmailMessage(
            message_id=msg.get("Message-ID", ""),
            subject=subject,
            sender=msg.get("From", ""),
            date=date,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            in_reply_to=msg.get("In-Reply-To"),
            references=msg.get("References"),
            raw_headers=dict(msg.items()),
            uid=uid,
        )

    @staticmethod
    def _decode_filename(filename: str) -> str:
        """Decode potentially encoded filename."""
        parts = decode_header(filename)
        decoded = ""
        for part, encoding in parts:
            if isinstance(part, bytes):
                decoded += part.decode(encoding or "utf-8", errors="replace")
            else:
                decoded += part
        return decoded

    def mark_seen(self, uid: str) -> bool:
        """Mark a message as seen."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        status, _ = self._connection.uid("STORE", uid, "+FLAGS", "\\Seen")
        if status != "OK":
            logger.error(f"Failed to mark message {uid} as seen")
            return False
        return True

    def validate_connection(self) -> tuple[bool, str]:
        """Validate IMAP connection."""
        try:
            self.connect()
            self.disconnect()
            return True, "IMAP connection successful"
        except imaplib.IMAP4.error as e:
            return False, f"IMAP authentication failed: {e}"
        except Exception as e:
            return False, f"IMAP connection failed: {e}"


class GraphEmailReader(BaseEmailReader):
    """
    Microsoft Graph API email reader for M365.
    Requires Azure AD app registration with Mail.Read permission.
    """

    def __init__(self, config: EmailConfig):
        self.config = config
        self._access_token: Optional[str] = None

    def connect(self) -> None:
        """Authenticate and get access token."""
        import requests

        token_url = f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        response = requests.post(token_url, data=data, timeout=30)
        response.raise_for_status()
        self._access_token = response.json()["access_token"]
        logger.info("Connected to Microsoft Graph API")

    def disconnect(self) -> None:
        """Clear access token."""
        self._access_token = None

    def _get_headers(self) -> dict:
        """Get authorization headers."""
        if not self._access_token:
            raise ConnectionError("Not connected to Graph API")
        return {"Authorization": f"Bearer {self._access_token}"}

    def list_unseen(self) -> list[str]:
        """Get list of unseen message IDs."""
        import requests

        # Build filter
        filter_parts = ["isRead eq false"]
        if self.config.from_filter:
            filter_parts.append(f"from/emailAddress/address eq '{self.config.from_filter}'")

        filter_str = " and ".join(filter_parts)
        folder = self.config.folder.replace("/", "%2F")

        url = f"https://graph.microsoft.com/v1.0/users/{self.config.address}/mailFolders/{folder}/messages"
        params = {
            "$filter": filter_str,
            "$select": "id",
            "$top": 100,
        }

        response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
        response.raise_for_status()

        messages = response.json().get("value", [])
        return [m["id"] for m in messages]

    def fetch_message(self, msg_id: str) -> Optional[EmailMessage]:
        """Fetch a single message by ID."""
        import requests

        # Get message
        url = f"https://graph.microsoft.com/v1.0/users/{self.config.address}/messages/{msg_id}"
        params = {"$expand": "attachments"}

        response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
        if response.status_code != 200:
            logger.error(f"Failed to fetch message {msg_id}: {response.status_code}")
            return None

        data = response.json()

        # Parse date
        date = None
        if data.get("receivedDateTime"):
            try:
                date = datetime.fromisoformat(data["receivedDateTime"].replace("Z", "+00:00"))
            except Exception:
                pass

        # Parse attachments
        attachments = []
        for att in data.get("attachments", []):
            if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                import base64

                content = base64.b64decode(att.get("contentBytes", ""))
                attachments.append(
                    Attachment(
                        filename=att.get("name", "unknown"),
                        content_type=att.get("contentType", "application/octet-stream"),
                        content=content,
                        size=len(content),
                        is_inline=att.get("isInline", False),
                    )
                )

        return EmailMessage(
            message_id=data.get("internetMessageId", msg_id),
            subject=data.get("subject", ""),
            sender=data.get("from", {}).get("emailAddress", {}).get("address", ""),
            date=date,
            body_text=(
                data.get("body", {}).get("content", "")
                if data.get("body", {}).get("contentType") == "text"
                else ""
            ),
            body_html=(
                data.get("body", {}).get("content", "")
                if data.get("body", {}).get("contentType") == "html"
                else ""
            ),
            attachments=attachments,
            in_reply_to=data.get("inReplyTo"),
            references=None,  # Graph doesn't expose References header directly
            uid=msg_id,
        )

    def mark_seen(self, msg_id: str) -> bool:
        """Mark a message as read."""
        import requests

        url = f"https://graph.microsoft.com/v1.0/users/{self.config.address}/messages/{msg_id}"
        data = {"isRead": True}

        response = requests.patch(url, headers=self._get_headers(), json=data, timeout=30)
        return response.status_code == 200

    def validate_connection(self) -> tuple[bool, str]:
        """Validate Graph API connection."""
        try:
            self.connect()
            self.disconnect()
            return True, "Microsoft Graph API connection successful"
        except Exception as e:
            return False, f"Graph API connection failed: {e}"


# Type alias for convenience
EmailReader = BaseEmailReader


def create_email_reader(config: EmailConfig) -> EmailReader:
    """Factory function to create appropriate email reader based on config."""
    if config.provider == "graph":
        return GraphEmailReader(config)
    else:
        return IMAPEmailReader(config)
