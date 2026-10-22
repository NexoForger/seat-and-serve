<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { eventId, get, post } from "../../ui/client";
import CameraScanner from "./CameraScanner.vue";
const props = defineProps<{
	modelValue: string;
	outlet: string;
	language: "en" | "ar";
	disabled: boolean;
	requestId?: string;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const text = (en: string, ar: string) => (props.language === "ar" ? ar : en);
const input = ref<HTMLInputElement | null>(null);
const buffer = ref(props.modelValue);
const camera = ref(false);
const message = ref("");
const duplicate = ref(false);
const processing = ref(false);
const qr = ref("");
const pairingLink = ref("");
const linkInput = ref<HTMLInputElement | null>(null);
const scannerMode = ref("phone");
const paired = ref(false);
const pair = ref<{ token: string; desktop_secret: string } | null>(null);
const tab = eventId();
let draft = eventId();
let disposed = false;
let suspended = false;
let active: Promise<boolean> | null = null;
let polling = false;
let timer: ReturnType<typeof setInterval> | undefined;
let generation = 0;
const seen = new Set<string>();
watch(
	() => props.modelValue,
	(value) => {
		buffer.value = value;
	},
);
watch(
	() => props.outlet,
	() => {
		generation++;
		void disconnect().then(reset);
	},
);
const relay = <T,>(action: string, args: Record<string, unknown> = {}) =>
	post<T>("barcodes.exchange", { ...pair.value, tab, action, ...args });
function focus() {
	void nextTick(() => {
		input.value?.focus();
		input.value?.select();
	});
}
function apply(value: string): Promise<boolean> {
	if (active) return active;
	active = applyValue(value).finally(() => {
		active = null;
	});
	return active;
}
async function applyValue(value: string) {
	if (processing.value || props.disabled || disposed) return false;
	const current = ++generation;
	processing.value = true;
	message.value = "";
	duplicate.value = false;
	try {
		if (/[\x00-\x1f\x7f-\x9f]/.test(value) || value.trim().length > 140)
			throw new Error(
				text(
					"Use at most 140 characters without control characters.",
					"استخدم ١٤٠ حرفاً كحد أقصى دون أحرف تحكم.",
				),
			);
		value = value.trim();
		if (
			props.modelValue &&
			value &&
			value !== props.modelValue &&
			!window.confirm(text("Replace the existing barcode?", "استبدال الباركود الحالي؟"))
		) {
			buffer.value = props.modelValue;
			return false;
		}
		const result = value
			? await get<{ available: boolean; item_name?: string }>("items.barcode_available", {
					outlet: props.outlet,
					barcode: value,
					request_id: props.requestId,
				})
			: { available: true };
		if (disposed || current !== generation) return false;
		buffer.value = value;
		emit("update:modelValue", value);
		duplicate.value = !result.available;
		message.value = result.available
			? value
				? text(
						"Barcode ready. Save the item to register it.",
						"الباركود جاهز. احفظ الصنف لتسجيله.",
					)
				: ""
			: text("Barcode already assigned", "الباركود مستخدم بالفعل") +
				(result.item_name ? ": " + result.item_name : "");
		return result.available;
	} catch (cause) {
		message.value = String(cause);
		duplicate.value = true;
		return false;
	} finally {
		processing.value = false;
	}
}
async function commit() {
	return apply(buffer.value);
}
async function scanned(value: string) {
	camera.value = false;
	await apply(value);
}
async function arm(value: string | null) {
	if (pair.value) await relay("arm", { draft: value });
}
async function prepareSave() {
	// Parent calls before disabling the form, so a blur/Enter scan cannot race saving.
	suspended = true;
	if (active) await active;
	if (!(await commit())) {
		suspended = false;
		return false;
	}
	camera.value = false;
	generation++;
	draft = eventId();
	try {
		await arm(null);
	} catch (cause) {
		message.value = String(cause);
		await resume();
		return false;
	}
	return true;
}
async function resume() {
	suspended = false;
	draft = eventId();
	try {
		await arm(draft);
	} catch (cause) {
		message.value = String(cause);
	}
}
async function reset() {
	generation++;
	if (active) await active;
	emit("update:modelValue", "");
	buffer.value = "";
	message.value = "";
	duplicate.value = false;
	camera.value = false;
	await resume();
	focus();
}
async function disconnect() {
	const previous = pair.value;
	pair.value = null;
	qr.value = "";
	pairingLink.value = "";
	paired.value = false;
	seen.clear();
	if (previous)
		try {
			await post("barcodes.exchange", { ...previous, tab, action: "disconnect" });
		} catch {
			/* TTL revokes unreachable pairings. */
		}
}
function copyLink() {
	linkInput.value?.focus();
	linkInput.value?.select();
	if (navigator.clipboard && window.isSecureContext) {
		void navigator.clipboard.writeText(pairingLink.value).catch(() => {
			message.value = text("Select and copy the pairing link.", "حدد رابط الربط وانسخه.");
		});
	} else {
		try {
			document.execCommand("copy");
		} catch {
			/* The selected link can be copied manually on HTTP. */
		}
		message.value = text(
			"Pairing link selected. Copy it and open it on the scanner PC.",
			"تم تحديد رابط الربط. انسخه وافتحه على حاسوب الماسح.",
		);
	}
}
async function connect(mode = "phone") {
	await disconnect();
	scannerMode.value = mode;
	message.value = "";
	try {
		const created = await post<{ token: string; desktop_secret: string }>("barcodes.start", {
			outlet: props.outlet,
			tab,
			draft,
		});
		if (disposed) return;
		pair.value = created;
		const currentPair = pair.value;
		await arm(suspended ? null : draft);
		const url = new URL("/till?scanner=" + mode, location.origin);
		url.hash = created.token;
		if (!disposed && pair.value === currentPair) pairingLink.value = url.toString();
		if (mode === "usb") return;
		const QR = await import("qrcode");
		const image = await QR.toDataURL(url.toString());
		if (!disposed && pair.value === currentPair) qr.value = image;
	} catch (cause) {
		message.value = String(cause);
	}
}
async function poll() {
	if (
		!pair.value ||
		document.hidden ||
		polling ||
		processing.value ||
		props.disabled ||
		suspended
	)
		return;
	polling = true;
	try {
		const currentDraft = draft;
		const currentPair = pair.value;
		const result = await relay<{
			paired: boolean;
			scan: null | { barcode: string; draft: string; scan_id: string };
		}>("poll");
		if (disposed || suspended || pair.value !== currentPair) return;
		paired.value = result.paired;
		if (result.scan) {
			const scan = result.scan;
			if (!seen.has(scan.scan_id) && scan.draft === draft && currentDraft === draft) {
				seen.add(scan.scan_id);
				await apply(scan.barcode);
			}
			await relay("ack", { scan_id: scan.scan_id });
		}
	} catch (cause) {
		message.value = String(cause);
	} finally {
		polling = false;
	}
}
onMounted(() => {
	focus();
	timer = setInterval(() => void poll(), 1000);
});
onBeforeUnmount(() => {
	disposed = true;
	generation++;
	clearInterval(timer);
	camera.value = false;
	void disconnect();
});
defineExpose({ prepareSave, resume, reset, focus });
</script>
<template>
	<section class="barcode-field">
		<label
			>{{ text("Barcode (optional)", "الباركود (اختياري)")
			}}<input
				ref="input"
				v-model="buffer"
				type="text"
				maxlength="140"
				autocomplete="off"
				spellcheck="false"
				dir="ltr"
				:disabled="disabled"
				:readonly="processing"
				@focus="input?.select()"
				@keydown.enter.prevent.stop="commit"
				@keydown.tab="commit"
				@blur="buffer !== modelValue && !processing && commit()"
		/></label>
		<p>
			{{
				text(
					"Focus this field, then scan with a USB or wireless dongle scanner in keyboard mode.",
					"حدد هذا الحقل ثم امسح بماسح USB أو لاسلكي بوضع لوحة المفاتيح.",
				)
			}}
		</p>
		<div class="barcode-actions">
			<button type="button" :disabled="disabled || processing" @click="focus">
				{{ text("Focus scanner", "تحديد الماسح") }}</button
			><button type="button" :disabled="disabled || processing" @click="camera = true">
				{{ text("Scan with camera", "المسح بالكاميرا") }}</button
			><button type="button" :disabled="disabled || processing" @click="connect('phone')">
				{{ text("Pair phone", "ربط الهاتف") }}</button
			><button type="button" :disabled="disabled || processing" @click="connect('usb')">
				{{ text("Pair PC scanner", "ربط ماسح الحاسوب") }}</button
			><button type="button" :disabled="disabled || processing" @click="reset">
				{{ text("Clear barcode", "مسح الباركود") }}
			</button>
		</div>
		<p v-if="message" :role="duplicate ? 'alert' : 'status'">{{ message }}</p>
		<div v-if="pairingLink">
			<p v-if="scannerMode === 'usb'">
				{{
					text(
						"Open this link on the PC with the USB/dongle scanner. Sign in with the same manager account, then click Scan next on that PC. Keep Add Items open here. No camera or HTTPS is needed for this scanner flow.",
						"افتح هذا الرابط على الحاسوب المتصل بالماسح وسجل الدخول بحساب المدير نفسه ثم اضغط مسح التالي هناك. أبقِ نموذج إضافة الأصناف مفتوحاً هنا. هذا المسار لا يحتاج كاميرا أو HTTPS.",
					)
				}}
			</p>
			<label
				>{{ text("Scanner pairing link", "رابط ربط الماسح")
				}}<input
					ref="linkInput"
					:value="pairingLink"
					readonly
					dir="ltr"
					@focus="linkInput?.select()"
			/></label>
			<button type="button" @click="copyLink">
				{{ text("Copy pairing link", "نسخ رابط الربط") }}
			</button>
			<img
				v-if="qr && scannerMode === 'phone'"
				:src="qr"
				:alt="text('Scan to pair your phone', 'امسح لربط الهاتف')"
				width="190"
				height="190"
			/>
			<p>
				{{
					paired
						? text("Scanner connected", "الماسح متصل")
						: text(
								"Open the pairing link (or scan the QR) and sign in with the same manager account.",
								"افتح رابط الربط أو امسح الرمز وسجل الدخول بحساب المدير نفسه.",
							)
				}}
			</p>
			<button type="button" @click="disconnect">
				{{ text("Disconnect scanner", "فصل الماسح") }}
			</button>
		</div>
		<CameraScanner
			v-if="camera"
			:language="language"
			@scanned="scanned"
			@cancel="camera = false"
		/>
	</section>
</template>
<style scoped>
.barcode-field {
	padding: 16px 0;
	margin-bottom: 16px;
	border-bottom: 1px solid #ddd;
}
.barcode-field p {
	font-size: 13px;
}
.barcode-actions {
	display: flex;
	gap: 8px;
	flex-wrap: wrap;
}
.barcode-field img {
	display: block;
}
.barcode-field label {
	display: grid;
	gap: 8px;
	margin-bottom: 12px;
	font-size: 13px;
	font-weight: 600;
}
.barcode-field input {
	box-sizing: border-box;
	width: 100%;
	min-height: 44px;
	padding: 10px 12px;
	border: 1px solid #c8cdbe;
	border-radius: 8px;
	font: inherit;
}
.barcode-field button {
	min-height: 44px;
	padding: 10px 12px;
	border: 1px solid #c8cdbe;
	border-radius: 8px;
	background: white;
	color: inherit;
	font: inherit;
	cursor: pointer;
}
.barcode-field button:disabled {
	opacity: 0.5;
}
</style>
