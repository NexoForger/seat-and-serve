<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { openCamera } from "./camera";
const props = defineProps<{ language: "en" | "ar" }>();
const emit = defineEmits<{ scanned: [value: string]; cancel: [] }>();
const text = (en: string, ar: string) => (props.language === "ar" ? ar : en);
const video = ref<HTMLVideoElement | null>(null);
const error = ref("");
const device = ref("");
const devices = ref<MediaDeviceInfo[]>([]);
let session: Awaited<ReturnType<typeof openCamera>> | undefined;
let generation = 0;
async function start() {
	const current = ++generation;
	session?.stop();
	error.value = "";
	await nextTick();
	if (!video.value || current !== generation) return;
	const candidate = await openCamera(
		video.value,
		device.value || undefined,
		(value) => emit("scanned", value),
		(message) => {
			error.value = message;
		},
	);
	if (current !== generation) {
		candidate.stop();
		return;
	}
	session = candidate;
	await candidate.ready;
	if (current === generation && navigator.mediaDevices?.enumerateDevices) {
		try {
			devices.value = (await navigator.mediaDevices.enumerateDevices()).filter(
				(row) => row.kind === "videoinput",
			);
		} catch {
			/* Optional camera switching. */
		}
	}
}
function close() {
	generation++;
	session?.stop();
	emit("cancel");
}
function key(event: KeyboardEvent) {
	if (event.key === "Escape") {
		event.preventDefault();
		close();
	}
}
function hidden() {
	if (document.hidden) {
		generation++;
		session?.stop();
		emit("cancel");
	}
}
onMounted(() => {
	document.addEventListener("visibilitychange", hidden);
	window.addEventListener("pagehide", close);
	document.addEventListener("keydown", key);
	void start();
});
onBeforeUnmount(() => {
	generation++;
	session?.stop();
	document.removeEventListener("visibilitychange", hidden);
	window.removeEventListener("pagehide", close);
	document.removeEventListener("keydown", key);
});
</script>
<template>
	<section
		class="barcode-camera"
		role="dialog"
		aria-modal="true"
		:aria-label="text('Scan barcode', 'مسح الباركود')"
	>
		<h3>
			{{
				text("Point the camera at the product barcode", "وجّه الكاميرا نحو باركود المنتج")
			}}
		</h3>
		<video
			ref="video"
			autoplay
			muted
			playsinline
			style="width: 100%; max-height: 45vh; background: #111"
		/>
		<label v-if="devices.length > 1"
			>{{ text("Camera", "الكاميرا")
			}}<select v-model="device" @change="start">
				<option value="">
					{{ text("Rear camera (automatic)", "الكاميرا الخلفية تلقائياً") }}
				</option>
				<option v-for="row in devices" :key="row.deviceId" :value="row.deviceId">
					{{ row.label || row.deviceId }}
				</option>
			</select></label
		>
		<p v-if="error" role="alert">
			{{
				language === "ar"
					? "تعذر المسح بالكاميرا. تحقق من HTTPS وإذن الكاميرا أو أدخل الباركود يدوياً. "
					: ""
			}}{{ error }}
		</p>
		<button v-if="error" type="button" @click="start">
			{{ text("Try camera again", "حاول مجدداً") }}
		</button>
		<button type="button" @click="close">{{ text("Close camera", "إغلاق الكاميرا") }}</button>
	</section>
</template>
<style scoped>
.barcode-camera {
	position: fixed;
	inset: 5vh max(16px, calc((100vw - 600px) / 2));
	z-index: 1000;
	overflow: auto;
	background: white;
	border: 2px solid #71823d;
	border-radius: 16px;
	padding: 22px;
	box-shadow: 0 0 0 100vmax #0009;
}
.barcode-camera button {
	margin: 8px;
	padding: 12px;
}
.barcode-camera select {
	padding: 10px;
	max-width: 100%;
}
</style>
