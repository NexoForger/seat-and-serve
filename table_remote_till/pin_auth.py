"""Till-only staff PIN sessions, backed by Frappe password hashes and cookies."""
import hashlib
import re
import secrets
import time
from urllib.parse import urlsplit

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils.password import check_password, remove_encrypted_password, update_password

SESSION_HOURS = 8
STAFF_ROLES = {'TRT Cashier', 'TRT Manager', 'System Manager'}
SCOPE_KEY = 'trt_pin_scope'
# PIN cookies cannot be used with generic ERP document APIs or Desk methods.
API_PREFIXES = tuple('table_remote_till.' + name + '.' for name in (
    'api', 'items', 'shifts', 'barcodes', 'reservations'))
PUBLIC_METHODS = {'table_remote_till.pin_auth.' + name for name in ('state', 'login', 'logout')}


def _code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,40}', value.strip()):
        return ''
    return value.strip().lower()


def _scope():
    session = getattr(frappe.local, 'session', None)
    return (session.get('data') or {}).get(SCOPE_KEY) if session else None


def _assignment(scope):
    if not isinstance(scope, dict) or scope.get('expires', 0) <= time.time():
        return None
    row = frappe.db.get_value('TRT Staff Assignment', scope.get('assignment'),
        ['name', 'user', 'outlet', 'enabled', 'allow_till', 'allow_manager', 'allow_kitchen',
         'till_pin_enabled', 'till_pin_revision'], as_dict=True)
    if (not row or not row.enabled or not row.till_pin_enabled
        or not row.till_pin_revision or row.till_pin_revision != scope.get('revision')
        or row.outlet != scope.get('outlet') or row.user != frappe.session.user or not (row.allow_till or row.allow_manager)
        or not frappe.db.get_value('User', row.user, 'enabled')
        or not frappe.db.get_value('TRT Outlet', row.outlet, 'enabled')
        or not set(frappe.get_roles()).intersection(STAFF_ROLES)):
        return None
    return row


def effective_roles():
    roles = set(frappe.get_roles())
    scope = _scope()
    if scope is None:
        return roles
    row = _assignment(scope)
    if not row:
        return set()
    if not row.allow_manager:
        roles.difference_update({'System Manager', 'TRT Manager'})
        if row.allow_till:
            roles.add('TRT Cashier')
    return roles


def check_outlet(outlet, ability='allow_till'):
    """Return True when a PIN scope handled authorization, including System Managers."""
    scope = _scope()
    if scope is None:
        return False
    row = _assignment(scope)
    if not row or row.outlet != outlet or not (row.get(ability) or row.allow_manager):
        frappe.throw('PIN session is not authorized for this outlet or action', frappe.PermissionError)
    return True


def before_request():
    if _scope() is None:
        return
    path = frappe.request.path.rstrip('/') or '/'
    command = frappe.form_dict.get('cmd')
    if not command and path.startswith('/api/method/'):
        command = path[len('/api/method/'):]
    if command in PUBLIC_METHODS:
        return
    # Even expired/revoked PIN sessions must be able to render the sign-in shell.
    if not command and (path == '/till' or path.startswith('/till/')
        or path.startswith('/assets/') or path == '/favicon.ico'):
        return
    if not _assignment(_scope()):
        frappe.throw('Till PIN session expired or revoked. Sign in again.', frappe.AuthenticationError)
    if command:
        if command.startswith(API_PREFIXES) or command == 'table_remote_till.printer_api.drawer_status':
            return
    frappe.throw('This PIN signs into Till only. Sign out and use ERPNext login for Desk.', frappe.PermissionError)


def on_session_creation(login_manager=None):
    scope = frappe.flags.get('trt_pin_login')
    if scope:
        frappe.session.data[SCOPE_KEY] = scope
        # Persist the restriction before a login response can expose the new SID.
        frappe.local.session_obj.update(force=True)


@frappe.whitelist(allow_guest=True)
def state():
    scope = _scope()
    row = _assignment(scope) if scope is not None else None
    authenticated = (bool(row) if scope is not None else
        frappe.session.user != 'Guest' and bool(set(frappe.get_roles()).intersection(STAFF_ROLES)))
    return dict(authenticated=authenticated, pin_session=scope is not None,
        user=frappe.session.user if authenticated else None,
        outlet=row.outlet if row else None)


@frappe.whitelist(allow_guest=True, methods=['POST'])
@rate_limit(limit=60, seconds=300, methods=['POST'])
def login(login_code, pin_secret):
    # Reject cross-origin browser login attempts even for a Guest without saved CSRF.
    origin = frappe.get_request_header('Origin')
    if origin and urlsplit(origin).netloc != urlsplit(frappe.request.host_url).netloc:
        frappe.throw('Open Till on this ERP to sign in', frappe.PermissionError)
    code = _code(login_code)
    # This counter is independent of request rollback and is shared across IPs.
    key = frappe.cache.make_key('trt-pin-attempt:' + hashlib.sha256(code.encode()).hexdigest())
    attempts = frappe.cache.incr(key)
    if attempts == 1:
        frappe.cache.expire(key, 300)
    if attempts > 5:
        frappe.throw('Too many PIN attempts. Try again in five minutes.', frappe.AuthenticationError)
    row = frappe.db.get_value('TRT Staff Assignment', {'till_login_code': code, 'enabled': 1,
        'till_pin_enabled': 1}, ['name', 'user', 'outlet', 'allow_till', 'allow_manager', 'till_pin_revision'], as_dict=True) if code else None
    valid = (isinstance(pin_secret, str) and bool(re.fullmatch(r'[0-9]{6,12}', pin_secret))
        and row and row.user not in ('Guest', 'Administrator') and row.till_pin_revision
        and (row.allow_till or row.allow_manager)
        and frappe.db.get_value('User', row.user, 'enabled')
        and frappe.db.get_value('TRT Outlet', row.outlet, 'enabled')
        and set(frappe.get_roles(row.user)).intersection(STAFF_ROLES))
    if valid:
        try:
            check_password(row.name, pin_secret, doctype='TRT Staff Assignment',
                fieldname='till_pin_secret', delete_tracker_cache=False)
        except frappe.AuthenticationError:
            valid = False
    if not valid:
        frappe.throw('Incorrect staff code or PIN, or access is disabled.', frappe.AuthenticationError)
    from frappe.sessions import get_csrf_token
    scope = dict(assignment=row.name, outlet=row.outlet, revision=row.till_pin_revision,
        expires=int(time.time()) + SESSION_HOURS * 3600)
    frappe.flags.trt_pin_login = scope
    try:
        frappe.local.login_manager.login_as(row.user)
    finally:
        frappe.flags.pop('trt_pin_login', None)
    if _scope() != scope:
        # Fail closed if the installed site has not loaded the session hook yet.
        frappe.local.login_manager.logout()
        frappe.throw('Restart ERP workers after installing PIN login.', frappe.AuthenticationError)
    frappe.cache.delete(key)
    return dict(authenticated=True, user=row.user, outlet=row.outlet,
        pin_session=True, csrf_token=get_csrf_token())


@frappe.whitelist(allow_guest=True, methods=['POST'])
def logout():
    if frappe.session.user != 'Guest':
        frappe.local.login_manager.logout()
    return dict(authenticated=False)


@frappe.whitelist(methods=['POST'])
def set_pin(assignment, login_code, pin_secret):
    _administrator()
    code = _code(login_code)
    if not code or not isinstance(pin_secret, str) or not re.fullmatch(r'[0-9]{6,12}', pin_secret):
        frappe.throw('Use a staff code of 1–40 letters/digits/._- and a PIN of 6–12 digits')
    row = frappe.get_doc('TRT Staff Assignment', assignment)
    if (row.user in ('Guest', 'Administrator') or not row.enabled or not (row.allow_till or row.allow_manager)
        or not frappe.db.get_value('User', row.user, 'enabled')
        or not set(frappe.get_roles(row.user)).intersection(STAFF_ROLES)):
        frappe.throw('Choose an enabled Till staff assignment for an enabled staff user')
    existing = frappe.db.get_value('TRT Staff Assignment', {'till_login_code': code}, 'name')
    if existing and existing != row.name:
        frappe.throw('This staff code is already in use')
    update_password(row.name, pin_secret, doctype='TRT Staff Assignment', fieldname='till_pin_secret')
    row.db_set(dict(till_login_code=code, till_pin_enabled=1, till_pin_revision=secrets.token_hex(16)))
    return dict(enabled=True, login_code=code)


@frappe.whitelist(methods=['POST'])
def revoke_pin(assignment):
    _administrator()
    row = frappe.get_doc('TRT Staff Assignment', assignment)
    row.db_set(dict(till_pin_enabled=0, till_pin_revision=secrets.token_hex(16)))
    remove_encrypted_password('TRT Staff Assignment', row.name, fieldname='till_pin_secret')
    return dict(enabled=False)


def _administrator():
    if _scope() is not None or 'System Manager' not in frappe.get_roles():
        frappe.throw('Use a System Manager ERP login to manage Till PINs', frappe.PermissionError)
