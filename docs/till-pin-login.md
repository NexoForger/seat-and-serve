# Till staff PIN login

The `/till` page opens without an ERPNext login and shows a staff-code/PIN screen. Till data and actions remain protected until sign-in. Staff do not need to enter their ERPNext username or password. Normal ERP logins continue to work.

## Deploy

This feature adds fields to **TRT Staff Assignment**, so migration is required. From the bench directory, use your deployment's normal update process:

```sh
bench --site SITE migrate
bench --site SITE clear-cache
bench restart
```

The rebuilt Till assets are committed. Hard-refresh open browsers after upgrading. Restart workers so the PIN session restriction hooks are loaded before enabling PINs. The PIN screen and USB scanner relay work over HTTP; browser camera access still requires HTTPS.

## Administrator setup

1. Sign into ERPNext with a **System Manager** account.
2. Create or choose an enabled User with a **TRT Cashier**, **TRT Manager**, or **System Manager** role. Each employee should have their own User so transactions retain their identity. Staff never need to use that User's ERP password at the Till. Guest and Administrator cannot receive PINs.
3. Open **TRT Staff Assignment**, assign that user to the outlet, enable it, and allow Till access (or manager access). Save the assignment.
4. Click **Set Till PIN**. Enter a unique staff code (1–40 letters, digits, `.`, `_` or `-`) and a **6–12 digit PIN**. Codes are case insensitive; leading zeroes in PINs are preserved. Use a different code for each outlet assignment.
5. Give the employee their staff code and PIN.

The same button rotates a PIN. **Revoke Till PIN** disables PIN sign-in. Both operations revoke existing PIN sessions at their next request. Only a System Manager using a normal ERP login may manage PINs; a PIN session cannot set or revoke them. PINs are hashed using Frappe's password hashing API and never stored as readable values in staff records.

## Staff use

Open `/till`, enter the staff code and PIN, then tap **Unlock Till**. The session is limited to that assignment's outlet and permissions. Transactions, shifts and items retain the staff user's ERP identity. Use **Sign out / switch staff** before another employee uses the device. Unsaved form details are lost when signing out; saved order drafts remain in the ERP.

A PIN session expires after eight hours at the latest, or earlier if the site's normal Frappe session expires. Disabling the User, outlet or assignment, revoking/changing the PIN, or moving the assignment to another user/outlet invalidates it. The screen checks access when returning to the tab and once per minute while visible; server requests validate it immediately.

Five failed attempts per staff code are allowed in five minutes, shared across IPs. A separate IP limit applies. Wait five minutes if locked out. No anonymous employee list or outlet list is exposed by the PIN screen.

PIN sessions use Frappe cookies and normal CSRF protection. They permit the Till page and Till APIs, not ERPNext Desk, generic document REST APIs, PIN administration, Kitchen pages or other ERP pages. Manager actions still need manager permission on the assignment, even when the underlying User has the System Manager role. To use Desk, sign out and use the normal ERP login.

## Paired barcode scanner

The phone form and paired scanner PC can both sign into `/till` with the **same staff code and PIN**. Manager access is still required for Add Items and barcode pairing. Pairing links survive PIN sign-in in the same tab. Leave Frappe's **Deny Multiple Sessions** disabled if the same staff user needs to use both devices simultaneously. PIN login does not override that site policy.

## Checks

Backend tests cover authentication, hash verification, request limits, origin rejection, session restriction persistence, route/REST/legacy-command isolation, expiry, PIN rotation, disabled assignments, outlet scoping, manager permissions and administrative PIN control. Browser tests cover the guest screen, sign-in failures, secret clearing, updated CSRF, expired-session locking and scanner-link preservation. Run:

```sh
python3 -m unittest discover -s tests
cd till
yarn test
yarn build
```

These are isolated contract/browser tests. After migration, verify a real cashier PIN on the deployed site, cashier checkout/shift operations, manager Add Items, two-device barcode pairing, revocation and a denied `/app` request from a PIN session before rolling out to staff.
