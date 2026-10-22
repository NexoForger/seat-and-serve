"""Barcode values and authenticated, ephemeral phone-to-form relay."""
import hashlib
import secrets
import time
import uuid

import frappe
from frappe.rate_limiter import rate_limit


from table_remote_till.barcode_values import normalize


def _manager(outlet):
    from table_remote_till.items import _manager as authorize
    authorize(outlet)


def _sid():
    return hashlib.sha256(frappe.session.sid.encode()).hexdigest()


def _key(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        frappe.throw('Invalid or expired pairing')
    return 'trt-barcode-pair:' + hashlib.sha256(token.encode()).hexdigest()


@frappe.whitelist(methods=['POST'])
@rate_limit(limit=10, seconds=60, methods=['POST'])
def start(outlet, tab, draft):
    _manager(outlet)
    if not all(isinstance(value, str) and 1 <= len(value) <= 64 for value in (tab, draft)):
        frappe.throw('Invalid scanner form')
    token, desktop_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = time.time()
    state = dict(owner=frappe.session.user, outlet=outlet, tab=tab, draft=draft,
        desktop_hash=hashlib.sha256(desktop_secret.encode()).hexdigest(), desktop_sid=_sid(), phone_hash=None, phone_sid=None,
        created=now, activity=now, pending=None, seen=[])
    frappe.cache.set_value(_key(token), state, expires_in_sec=900)
    return dict(token=token, desktop_secret=desktop_secret)


@frappe.whitelist(methods=['POST'])
@rate_limit(limit=180, seconds=60, methods=['POST'])
def exchange(token, action, tab=None, desktop_secret=None, phone_secret=None, draft=None, scan_id=None, barcode=None):
    key = _key(token)
    with frappe.cache.lock(frappe.cache.make_key(key + ':lock'), timeout=5, blocking_timeout=3):
        state = frappe.cache.get_value(key, use_local_cache=False)
        now = time.time()
        if not state or now-state['created'] >= 3600 or now-state['activity'] >= 900:
            frappe.throw('Pairing expired. Pair the phone again.')
        if frappe.session.user != state['owner']:
            frappe.throw('Sign in with the same manager account as the computer', frappe.PermissionError)
        _manager(state['outlet'])
        is_desktop = (isinstance(desktop_secret, str) and secrets.compare_digest(hashlib.sha256(desktop_secret.encode()).hexdigest(), state['desktop_hash'])
            and tab == state['tab'] and _sid() == state['desktop_sid'])
        is_phone = (isinstance(phone_secret, str) and state['phone_hash'] and secrets.compare_digest(hashlib.sha256(phone_secret.encode()).hexdigest(), state['phone_hash'])
            and _sid() == state['phone_sid'])
        if action == 'join':
            if state['phone_hash'] and not is_phone:
                frappe.throw('A phone is already paired. Disconnect it on the computer first.')
            if not state['phone_hash']:
                phone_secret = secrets.token_urlsafe(32)
                state['phone_hash'], state['phone_sid'] = hashlib.sha256(phone_secret.encode()).hexdigest(), _sid()
            state['activity'] = now
            result = dict(phone_secret=phone_secret, outlet=state['outlet'], draft=state['draft'])
        elif action in ('arm', 'poll', 'ack'):
            if not is_desktop:
                frappe.throw('This pairing belongs to another form', frappe.PermissionError)
            if action == 'arm':
                if draft is not None and (not isinstance(draft, str) or not 1 <= len(draft) <= 64):
                    frappe.throw('Invalid scanner draft')
                state['draft'], state['pending'] = draft, None
                state['activity'] = now
            if action == 'ack' and state['pending'] and state['pending']['scan_id'] == scan_id:
                state['pending'] = None
                state['activity'] = now
            result = dict(paired=bool(state['phone_hash']), draft=state['draft'], scan=state['pending'])
        elif action in ('state', 'scan'):
            if not is_phone:
                frappe.throw('Phone pairing is not valid', frappe.PermissionError)
            if action == 'scan':
                try:
                    scan_id = str(uuid.UUID(scan_id))
                    barcode = normalize(barcode)
                except (ValueError, TypeError, AttributeError) as error:
                    frappe.throw(str(error))
                if not barcode or not draft or draft != state['draft']:
                    frappe.throw('This item form changed. Scan again for the current item.')
                if scan_id not in state['seen']:
                    if state['pending']:
                        frappe.throw('The computer has not received the previous scan yet')
                    state['pending'] = dict(barcode=barcode, draft=draft, scan_id=scan_id)
                    state['seen'].append(scan_id)
                state['activity'] = now
            result = dict(draft=state['draft'], ready=bool(state['draft']), pending=bool(state['pending']))
        elif action == 'disconnect':
            if not (is_desktop or is_phone):
                frappe.throw('Pairing access denied', frappe.PermissionError)
            frappe.cache.delete_value(key)
            return dict(disconnected=True)
        else:
            frappe.throw('Invalid scanner action')
        frappe.cache.set_value(key, state, expires_in_sec=max(1, int(min(900, 3600-(now-state['created'])))))
        return result
