<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
const props = defineProps<{
	language: "en" | "ar";
	disabled: boolean;
	scan: (barcode: string) => Promise<void>;
}>();
const text = (en: string, ar: string) => (props.language === "ar" ? ar : en);
const value = ref("");
const input = ref<HTMLInputElement | null>(null);
const processing = ref(false);
const message = ref("");
let disposed = false;
function focus() {
	void nextTick(() => {
		input.value?.focus();
		input.value?.select();
	});
}
const queue: string[] = [];
async function submit() {
	if (props.disabled || disposed) return;
	const code = value.value.trim();
	value.value = "";
	if (!code && processing.value) {
		message.value = text(
			"Wait for the current scan, then scan again.",
			"انتظر اكتمال المسح الحالي ثم امسح مجدداً.",
		);
		return;
	}
	if (!code || /[\x00-\x1f\x7f-\x9f]/.test(code) || code.length > 140) {
		message.value = text(
			"Enter a valid barcode (up to 140 characters).",
			"أدخل باركوداً صالحاً حتى ١٤٠ حرفاً.",
		);
		return;
	}
	if (queue.length >= 50) {
		message.value = text(
			"Scanner queue is full. Wait, then rescan this item.",
			"قائمة المسح ممتلئة. انتظر ثم أعد مسح هذا الصنف.",
		);
		return;
	}
	queue.push(code);
	if (processing.value) return;
	processing.value = true;
	message.value = "";
	try {
		while (queue.length && !disposed && !props.disabled) await props.scan(queue.shift()!);
	} catch (cause) {
		const remaining = queue.length;
		queue.length = 0;
		if (!disposed)
			message.value =
				String(cause) +
				(remaining
					? text(
							" Remaining queued scans cancelled; scan them again.",
							" ألغيت عمليات المسح المتبقية؛ امسحها مجدداً.",
						)
					: "");
	} finally {
		queue.length = 0;
		processing.value = false;
		if (!disposed && !value.value) focus();
	}
}
watch(
	() => props.disabled,
	(disabled) => {
		if (!disabled) focus();
	},
);
onMounted(focus);
onBeforeUnmount(() => {
	disposed = true;
	queue.length = 0;
});
</script>
<template>
	<section class="checkout-scanner">
		<label
			>{{ text("Scan item barcode", "مسح باركود الصنف")
			}}<input
				ref="input"
				v-model="value"
				type="text"
				autocomplete="off"
				spellcheck="false"
				maxlength="140"
				dir="ltr"
				:disabled="disabled"
				@keydown.enter.prevent.stop="submit"
				@keydown.tab="submit"
		/></label>
		<button type="button" :disabled="disabled || processing" @click="focus">
			{{ text("Focus scanner", "تحديد الماسح") }}
		</button>
		<button type="button" :disabled="disabled || processing" @click="submit">
			{{ text("Add barcode", "إضافة بالباركود") }}
		</button>
		<p v-if="processing" role="status">{{ text("Adding item…", "جارٍ إضافة الصنف…") }}</p>
		<p v-if="message" role="alert">{{ message }}</p>
	</section>
</template>
<style scoped>
.checkout-scanner {
	display: flex;
	align-items: end;
	gap: 8px;
	flex-wrap: wrap;
	padding: 12px;
	margin-bottom: 18px;
	background: #252b22;
	border-radius: 12px;
	color: #f7f8f3;
}
.checkout-scanner label {
	display: grid;
	gap: 6px;
	flex: 1;
	min-width: 180px;
	font-size: 13px;
}
.checkout-scanner input {
	box-sizing: border-box;
	width: 100%;
	min-height: 44px;
	border-radius: 8px;
	border: 1px solid #61704e;
	padding: 10px;
	font: inherit;
}
.checkout-scanner button {
	min-height: 44px;
	border: 1px solid #61704e;
	border-radius: 8px;
	padding: 8px 12px;
	cursor: pointer;
	font: inherit;
}
.checkout-scanner p {
	width: 100%;
	margin: 0;
	font-size: 13px;
}
</style>
