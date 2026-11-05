"""Policy for WhatsApp invoice sends and deliberate resends."""
from datetime import datetime, timezone


class SendDenied(Exception):
    def __init__(self, status_code, detail):
        self.status_code=status_code
        self.detail=detail
        super().__init__(detail)


def authorize_receipt_send(record, resend=False, at=None):
    """Pure policy. Called inside the Firestore transaction before claiming."""
    data=record or {}
    current=at or datetime.now(timezone.utc)
    state=data.get("state","not_sent")
    if state in ("sending","review_required"):
        raise SendDenied(409,"Receipt send is pending or needs administrator review")
    if resend:
        if state!="submitted":
            raise SendDenied(409,"Receipt must be sent successfully before it can be resent")
        last=data.get("last_sent_at") or data.get("updated_at")
        if last and (current-last).total_seconds()<120:
            raise SendDenied(429,"Wait at least two minutes between receipt sends")
    elif state=="submitted":
        raise SendDenied(409,"Receipt already submitted; use Resend in Order History")
    count=int(data.get("attempt_count",0))
    if count>=3:
        raise SendDenied(429,"Maximum three WhatsApp send attempts reached for this order")
    return count+1
