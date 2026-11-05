"""Minimal order audit metadata. No browser MAC/private IP claims.

Device IDs are browser-generated identifiers, not reliable hardware identity.
IP is the socket peer seen by ASGI; reverse proxies can change that value.
"""
import ipaddress
import re
import uuid

MAX_AGENT=240


def peer_address(request):
    host=getattr(getattr(request,"client",None),"host",None)
    if not host:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def device_details(request):
    supplied=request.headers.get("x-foodoo-device-id","")
    try:
        device=str(uuid.UUID(supplied))
    except (ValueError,AttributeError):
        device=None
    agent=request.headers.get("user-agent","")[:MAX_AGENT]
    # Strip terminal escapes/control chars for safe storage and inspection.
    agent=re.sub(r"[\x00-\x1f\x7f]","",agent)
    return {"browser_device_id":device,"observed_ip":peer_address(request),
            "user_agent":agent or None}


def actor_details(request,user):
    return {"user_id":user["id"],
            "username":user.get("username",""),
            "role":user.get("role",""),
            "session_id":user.get("_session_id"),
            "device":device_details(request)}
