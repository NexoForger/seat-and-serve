<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { post, eventId } from "../../ui/client";
import CameraScanner from "./CameraScanner.vue";
const language = ref<"en" | "ar">("en");
const text = (en: string, ar: string) => (language.value === "ar" ? ar : en);
const token = location.hash.slice(1) || sessionStorage.getItem("trt-phone-token") || "";
if (token) sessionStorage.setItem("trt-phone-token", token);
history.replaceState(null, "", location.pathname + "?scanner=phone");
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
					"The computer is not ready. Check its item form.",
					"الحاسوب غير جاهز. تحقق من نموذج الصنف.",
				),
			);
		draft.value = state.draft;
		camera.value = true;
	} catch (cause) {
		error.value = String(cause);
	} finally {
		busy.value = false;
	}
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
			"Barcode delivered. Check the computer before saving.",
			"تم إرسال الباركود. تحقق من الحاسوب قبل الحفظ.",
		);
	} catch (cause) {
		error.value = String(cause);
	} finally {
		busy.value = false;
	}
}
async function disconnect() {
	camera.value = false;
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
onMounted(join);
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
		<h1>{{ text("Phone barcode scanner", "ماسح الباركود بالهاتف") }}</h1>
		<p>{{ status }}</p>
		<p v-if="error" role="alert">{{ error }}</p>
		<a
			v-if="loggedOut"
			:href="'/login?redirect-to=' + encodeURIComponent('/till?scanner=phone')"
			>{{
				text(
					"Sign in with the same manager account, then return here",
					"سجّل الدخول بحساب المدير نفسه ثم عد هنا",
				)
			}}</a
		>
		<button v-if="!phone" type="button" :disabled="busy" @click="join">
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
		<CameraScanner
			v-if="camera"
			:language="language"
			@scanned="deliver"
			@cancel="camera = false"
		/>
	</main>
</template>
