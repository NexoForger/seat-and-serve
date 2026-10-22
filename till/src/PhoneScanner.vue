<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { post, eventId } from "../../ui/client";
import CameraScanner from "./CameraScanner.vue";
const keyboardMode = new URLSearchParams(location.search).get("scanner") === "usb";
const route = "/till?scanner=" + (keyboardMode ? "usb" : "phone");
const keyboardValue = ref("");
const keyboardInput = ref<HTMLInputElement | null>(null);
const keyboardArmed = ref(false);
const pastedLink = ref("");
const language = ref<"en" | "ar">("en");
const text = (en: string, ar: string) => (language.value === "ar" ? ar : en);
const token = location.hash.slice(1) || sessionStorage.getItem("trt-phone-token") || "";
if (token) sessionStorage.setItem("trt-phone-token", token);
history.replaceState(null, "", route);
const phone = ref(sessionStorage.getItem("trt-phone-credential") || "");
const error = ref("");
const status = ref("");
const camera = ref(false);
const draft = ref<string | null>(null);
const busy = ref(false);
const loggedOut = ref(false);
let disposed = false;
let pending: { barcode: string; scan_id: string; draft: string } | null = null;
const call = <T,>(action: string, args: Record<string, unknown> = {}) =>
	post<T>("barcodes.exchange", { token, action, phone_secret: phone.value, ...args });
async function join() {
	busy.value = true;
	error.value = "";
	try {
		const joined = await call<{ phone_secret: string; draft: string | null }>("join");
		if (disposed) return;
		loggedOut.value = false;
		phone.value = joined.phone_secret;
		draft.value = joined.draft;
		sessionStorage.setItem("trt-phone-credential", joined.phone_secret);
		status.value = text(
			"Connected. Tap Scan next when ready.",
			"تم الاتصال. اضغط مسح التالي.",
		);
	} catch (cause) {
		error.value = String(cause);
		loggedOut.value = true;
	} finally {
		busy.value = false;
	}
}
async function next() {
	busy.value = true;
	error.value = "";
	try {
		const state = await call<{ draft: string | null; pending: boolean }>("state");
		if (!state.draft || state.pending)
			throw new Error(
				text(
					"The item form is not ready. Check the device with Add Items open.",
					"نموذج الصنف غير جاهز. تحقق من الجهاز الذي يعرض إضافة الأصناف.",
				),
			);
		draft.value = state.draft;
		if (keyboardMode) {
			keyboardValue.value = "";
			keyboardArmed.value = true;
			busy.value = false;
			await nextTick();
			keyboardInput.value?.focus();
		} else camera.value = true;
	} catch (cause) {
		error.value = String(cause);
	} finally {
		busy.value = false;
	}
}
function openPairingLink() {
	try {
		const url = new URL(pastedLink.value.trim());
		if (
			url.origin !== location.origin ||
			url.pathname !== "/till" ||
			!/^[A-Za-z0-9_-]{32,128}$/.test(url.hash.slice(1))
		)
			throw new Error("Invalid pairing link");
		sessionStorage.setItem("trt-phone-token", url.hash.slice(1));
		sessionStorage.removeItem("trt-phone-credential");
		location.replace(route);
	} catch {
		error.value = text(
			"Paste a pairing link from Add Items on this ERP.",
			"ألصق رابط الربط من نموذج إضافة الأصناف في هذا النظام.",
		);
	}
}
async function keyboardScan() {
	if (!keyboardArmed.value || busy.value) return;
	const value = keyboardValue.value.trim();
	if (!value || /[\x00-\x1f\x7f-\x9f]/.test(value) || value.length > 140) {
		error.value = text(
			"Scan a barcode of up to 140 characters without control characters.",
			"امسح باركوداً حتى ١٤٠ حرفاً دون أحرف تحكم.",
		);
		return;
	}
	keyboardArmed.value = false;
	await deliver(value);
}
async function deliver(value?: string) {
	camera.value = false;
	busy.value = true;
	error.value = "";
	if (value && draft.value) pending = { barcode: value, scan_id: eventId(), draft: draft.value };
	try {
		if (!pending) return;
		await call("scan", pending);
		pending = null;
		status.value = text(
			"Barcode delivered. Check the Add Items form before saving.",
			"تم إرسال الباركود. تحقق من نموذج إضافة الأصناف قبل الحفظ.",
		);
	} catch (cause) {
		error.value = String(cause);
	} finally {
		busy.value = false;
	}
}
async function disconnect() {
	camera.value = false;
	keyboardArmed.value = false;
	try {
		await call("disconnect");
	} catch {
		/* Expired/disconnected. */
	}
	sessionStorage.removeItem("trt-phone-token");
	sessionStorage.removeItem("trt-phone-credential");
	phone.value = "";
	status.value = text("Disconnected.", "تم قطع الاتصال.");
}
onMounted(() => {
	if (token) void join();
});
onBeforeUnmount(() => {
	disposed = true;
	camera.value = false;
});
</script>
<template>
	<main
		style="max-width: 580px; margin: 30px auto; padding: 20px"
		:dir="language === 'ar' ? 'rtl' : 'ltr'"
	>
		<select v-model="language">
			<option value="en">English</option>
			<option value="ar">العربية</option>
		</select>
		<h1>
			{{
				keyboardMode
					? text("PC USB barcode scanner", "ماسح USB على الحاسوب")
					: text("Phone barcode scanner", "ماسح الباركود بالهاتف")
			}}
		</h1>
		<p v-if="keyboardMode">
			{{
				text(
					"Keep Add Items open on your phone. Click Scan next here, then scan with the USB or wireless dongle scanner in keyboard/HID mode. Enter sends the barcode; Tab sends it and moves focus. Nothing is saved automatically.",
					"أبقِ نموذج إضافة الأصناف مفتوحاً على الهاتف. اضغط مسح التالي هنا ثم امسح بماسح USB أو اللاسلكي بوضع لوحة المفاتيح. Enter يرسل الباركود وTab يرسله وينقل التركيز. لا يتم الحفظ تلقائياً.",
				)
			}}
		</p>
		<form v-if="!token" @submit.prevent="openPairingLink">
			<label
				>{{ text("Pairing link from Add Items", "رابط الربط من إضافة الأصناف")
				}}<input v-model="pastedLink" type="text" required autocomplete="off" /></label
			><button type="submit">{{ text("Connect", "اتصال") }}</button>
		</form>
		<p>{{ status }}</p>
		<p v-if="error" role="alert">{{ error }}</p>
		<a v-if="loggedOut" :href="'/login?redirect-to=' + encodeURIComponent(route)">{{
			text(
				"Sign in with the same manager account, then return here",
				"سجّل الدخول بحساب المدير نفسه ثم عد هنا",
			)
		}}</a>
		<button v-if="token && !phone" type="button" :disabled="busy" @click="join">
			{{ text("Reconnect", "إعادة الاتصال") }}
		</button>
		<button v-if="phone" type="button" :disabled="busy" @click="next">
			{{ text("Scan next", "مسح التالي") }}
		</button>
		<button v-if="error && phone" type="button" :disabled="busy" @click="deliver()">
			{{ text("Retry delivery of the same scan", "إعادة إرسال المسح نفسه") }}
		</button>
		<button v-if="phone" type="button" :disabled="busy" @click="disconnect">
			{{ text("Disconnect", "قطع الاتصال") }}
		</button>
		<label v-if="keyboardMode && keyboardArmed"
			>{{ text("Scan barcode here", "امسح الباركود هنا")
			}}<input
				ref="keyboardInput"
				v-model="keyboardValue"
				type="text"
				maxlength="140"
				autocomplete="off"
				spellcheck="false"
				dir="ltr"
				:disabled="busy"
				@keydown.enter.prevent.stop="keyboardScan"
				@keydown.tab="keyboardScan"
		/></label>
		<CameraScanner
			v-if="camera"
			:language="language"
			@scanned="deliver"
			@cancel="camera = false"
		/>
	</main>
</template>
