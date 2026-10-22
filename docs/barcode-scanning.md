# Barcode scanning in Add Items

Open **Till → Add items** with a manager account assigned to the outlet. Barcodes are optional. Scanning fills only the barcode: enter the item name, price, category and sale unit, then explicitly **Save & add to menu**. One barcode is saved in ERPNext's existing **Item → Barcodes** child table with the sale unit. No Item schema change or product catalog service is required.

## USB or wireless dongle scanner

1. Connect the wired USB scanner or its wireless USB receiver to the device running the browser.
2. Configure the scanner for **keyboard/HID mode**, using its manufacturer setup sheet. Select the keyboard layout matching the computer. Use an **Enter** suffix (recommended) or **Tab** suffix. Serial/COM mode is unsupported.
3. Click **Focus scanner**, then scan. Leading zeroes and letter case are preserved. Enter completes the barcode without submitting the item; Tab completes it and moves focus normally.
4. Existing barcodes block creation. Replacing a populated barcode requires confirmation. Saving resets the barcode and restores scanner focus.

No print agent, WebUSB permission or scanner driver is involved. The scanner types into the browser like a keyboard; the ERP can be hosted remotely.

## PC USB scanner → Add Items on a phone (works over HTTP)

1. On the **phone**, open Add items and tap **Pair PC scanner**.
2. Tap **Copy pairing link** and open that full link in the browser on the **PC** with the wired USB or wireless dongle scanner. On HTTP, the link is selected so you can copy it manually if the browser cannot copy automatically. You can also open `/till?scanner=usb` on the PC and paste the link there.
3. Sign in on the PC with the **same manager account** as the phone. Keep the Add Items form open and visible on the phone.
4. On the PC, click **Scan next**. The barcode input receives focus. Scan using keyboard/HID mode with an Enter or Tab suffix. The PC sends only the barcode through the ERP relay, bound to the phone's current item draft.
5. Check the barcode on the **phone**, enter the item details and explicitly save. For another capture click **Scan next** on the PC again.

This flow uses no camera, WebUSB, driver or print agent and does **not** require HTTPS or a shared LAN. The PC scanner page must have focus while scanning, and both devices must be able to reach the same ERP. The same pairing expiry, duplicate protection and stale-draft rules apply. Browser camera access still requires HTTPS; the USB relay provides the camera-free option on HTTP.

## Camera on the same phone

Open Add items on the phone over **HTTPS**, tap **Scan with camera**, and allow camera access. The rear camera is preferred; use the camera selector if necessary. Supported formats: EAN-13, EAN-8, UPC-A, UPC-E, Code 128, Code 39 and ITF. Images are decoded locally with bundled ZXing and are not uploaded. Capture stops after one result. Close the camera to cancel; hiding or leaving the page releases its stream. Manual input and keyboard scanners remain available when camera access fails.

## Pair a phone with a computer

1. On the computer's Add items form, click **Pair phone**.
2. Scan the QR link with the phone's normal camera and open it in the browser. Sign into the **same manager account**, with manager access to the selected outlet. The pairing survives the login redirect in that browser tab.
3. On the scanner page tap **Scan next**, capture one barcode, and check it on the computer. Confirm replacement on the computer if requested. The manager still enters details and saves on the computer.
4. Tap **Scan next** for each new capture. If delivery loses its response, **Retry delivery of the same scan** uses the same ID and cannot apply it twice.
5. Disconnect on either device when finished. Reconnect in the same phone tab after a page reload. A different phone requires disconnecting and pairing again.

The ERP relays scans through authenticated ERP requests; neither device needs a shared LAN with the other or with the ERP. The visible computer tab polls once per second. Pairing remains active across new items, expires after 15 minutes without scan/form activity or after one hour total, and allows one phone. Merely polling does not extend inactivity. The phone is authorized to transfer barcodes only; it cannot save an item or edit other form fields. Saving, clearing the barcode or leaving the form invalidates the previous draft; old or repeated deliveries cannot fill the next item.

The QR secret is in the URL fragment, which browsers do not send in HTTP requests. The scanner removes that fragment and keeps credentials only in that phone tab's session storage. Relay credentials use secret-named POST fields for Frappe log redaction; Redis holds credential hashes and expiring pairing state. Preserve normal Frappe CSRF protection. Do not configure proxies or debug tools to record full request bodies. Redis must be available for pairing.

## Upgrade and verification

Pull `main`, restart the ERP web workers and clear the site's cache using the deployment's normal bench commands. The rebuilt Till assets are committed; no barcode schema migration is needed. Hard refresh the browser. If rebuilding from source:

```sh
cd till
yarn install --frozen-lockfile
yarn test
yarn build
```

Backend contract tests run with `python3 -m unittest discover -s tests` from the app directory. They cover optional and string barcodes, duplicates and simulated uniqueness races, retry protection, authorization, expiry, session/tab/draft isolation, one-phone ownership, disconnect, acknowledgement and repeated delivery. Browser unit tests cover keyboard handling, replacement confirmation, duplicate feedback, save/reset timing, camera permissions and stream cleanup. These tests use mocked Frappe/Redis/browser hardware; they do not replace deployed integration checks.

Before production use, verify on the remote equipment:

- Android Chrome and iPhone Safari: camera permission, rear camera, switching, cancellation/backgrounding, QR login and Scan next.
- Wired HID and wireless USB-dongle scanners: leading zeroes, case, Enter/Tab suffixes and focus after saving.
- Two devices on different networks: pairing, reconnect/disconnect, expiry, delayed delivery after clearing/saving, and same-account/outlet restrictions.
- In deployed ERPNext, confirm the Item Barcode and UOM, duplicate rejection, and no partial Item/Price/Menu/Recipe after a failed save.

Checkout scanning and serial-mode scanners are outside this feature.
