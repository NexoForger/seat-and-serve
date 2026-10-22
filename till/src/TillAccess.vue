<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue";
import { get, post } from "../../ui/client";
import App from "./App.vue";
const Scanner = defineAsyncComponent(() =>
	import("./PhoneScanner.vue").then((module) => module.default),
);
const scanner = ["phone", "usb"].includes(
	new URLSearchParams(location.search).get("scanner") || "",
);
const language = ref<"en" | "ar">("en");
const text = (en: string, ar: string) => (language.value === "ar" ? ar : en);
const authenticated = ref(false);
const checking = ref(true);
const busy = ref(false);
const error = ref("");
const user = ref("");
const pinSession = ref(false);
const code = ref("");
const pin = ref("");
const redirect = computed(
	() => "/login?redirect-to=" + encodeURIComponent(location.pathname + location.search),
);
let timer: ReturnType<typeof setInterval> | undefined;
let disposed = false;
let checkingState = false;
// Capture scanner pairing before login; fragments never travel in HTTP requests.
const pairingToken = location.hash.slice(1);
if (scanner && /^[A-Za-z0-9_-]{32,128}$/.test(pairingToken)) {
	sessionStorage.setItem("trt-phone-token", pairingToken);
	history.replaceState(null, "", location.pathname + location.search);
}
async function check() {
	if (checkingState || busy.value || disposed) return;
	checkingState = true;
	try {
		const state = await get<{
			authenticated: boolean;
			user: string | null;
			pin_session: boolean;
		}>("pin_auth.state");
		if (disposed) return;
		authenticated.value = state.authenticated;
		user.value = state.user || "";
		pinSession.value = state.pin_session;
	} catch (cause) {
		if (checking.value) error.value = String(cause);
	} finally {
		checkingState = false;
		checking.value = false;
	}
}
async function signIn() {
	if (busy.value) return;
	busy.value = true;
	error.value = "";
	const secret = pin.value;
	pin.value = "";
	try {
		const result = await post<{ csrf_token: string; user: string }>("pin_auth.login", {
			login_code: code.value.trim(),
			pin_secret: secret,
		});
		if (disposed) return;
		window.csrf_token = result.csrf_token;
		user.value = result.user;
		pinSession.value = true;
		authenticated.value = true;
	} catch (cause) {
		error.value = String(cause);
	} finally {
		busy.value = false;
	}
}
async function lock() {
	if (
		busy.value ||
		!window.confirm(
			text(
				"Sign out and switch staff? Unsaved form details will be lost.",
				"تسجيل الخروج وتبديل الموظف؟ ستفقد تفاصيل النموذج غير المحفوظة.",
			),
		)
	)
		return;
	busy.value = true;
	error.value = "";
	try {
		await post("pin_auth.logout", {});
		// A full reload clears every component's pending requests and refreshes guest CSRF.
		location.reload();
	} catch (cause) {
		error.value = String(cause);
	} finally {
		busy.value = false;
	}
}
function visible() {
	if (!document.hidden) void check();
}
onMounted(() => {
	void check();
	timer = setInterval(visible, 60000);
	document.addEventListener("visibilitychange", visible);
	window.addEventListener("trt-auth-check", visible);
});
onBeforeUnmount(() => {
	disposed = true;
	clearInterval(timer);
	document.removeEventListener("visibilitychange", visible);
	window.removeEventListener("trt-auth-check", visible);
});
</script>
<template>
	<main v-if="!authenticated" class="pin-screen" :dir="language === 'ar' ? 'rtl' : 'ltr'">
		<form class="pin-card" @submit.prevent="signIn">
			<select v-model="language" aria-label="Language / اللغة">
				<option value="en">English</option>
				<option value="ar">العربية</option>
			</select>
			<p class="pin-brand">S&S · Seat & Serve</p>
			<h1>{{ text("Sign in to Till", "الدخول إلى الصندوق") }}</h1>
			<p>
				{{
					text(
						"Enter your staff code and PIN. No ERPNext login is needed.",
						"أدخل رمز الموظف والرقم السري. لا تحتاج إلى تسجيل الدخول إلى ERPNext.",
					)
				}}
			</p>
			<p v-if="checking" role="status">
				{{ text("Checking session…", "جارٍ التحقق من الجلسة…") }}
			</p>
			<p v-if="error" role="alert">{{ error }}</p>
			<label
				>{{ text("Staff code", "رمز الموظف")
				}}<input
					v-model="code"
					name="staff-code"
					type="text"
					autocomplete="username"
					autocapitalize="none"
					spellcheck="false"
					maxlength="40"
					required
					:disabled="busy || checking"
					dir="ltr"
			/></label>
			<label
				>{{ text("PIN", "الرقم السري")
				}}<input
					v-model="pin"
					name="pin-secret"
					type="password"
					inputmode="numeric"
					pattern="[0-9]{6,12}"
					minlength="6"
					maxlength="12"
					autocomplete="off"
					required
					:disabled="busy || checking"
					dir="ltr"
			/></label>
			<button type="submit" :disabled="busy || checking">
				{{
					busy ? text("Signing in…", "جارٍ الدخول…") : text("Unlock Till", "فتح الصندوق")
				}}
			</button>
			<button v-if="error && !busy" type="button" class="pin-retry" @click="check">
				{{ text("Check connection again", "تحقق من الاتصال مجدداً") }}
			</button>
			<p class="pin-help">
				{{
					text(
						"Ask your administrator to set up your staff code and PIN.",
						"اطلب من المسؤول إعداد رمز الموظف والرقم السري.",
					)
				}}
			</p>
			<a v-if="!pinSession" :href="redirect">{{
				text("Administrator / ERPNext login", "دخول المسؤول / ERPNext")
			}}</a>
			<button v-else type="button" class="pin-retry" :disabled="busy" @click="lock">
				{{ text("Sign out of expired session", "الخروج من الجلسة المنتهية") }}
			</button>
		</form>
	</main>
	<section v-else class="till-viewport">
		<div class="pin-session-bar">
			<span
				>{{ user }} ·
				{{
					pinSession
						? text("Till PIN session", "جلسة الصندوق بالرقم السري")
						: text("ERP session", "جلسة ERP")
				}}</span
			><button type="button" :disabled="busy" @click="lock">
				{{ text("Sign out / switch staff", "خروج / تبديل الموظف") }}</button
			><span v-if="error" role="alert">{{ error }}</span>
		</div>
		<div class="till-workspace"><Scanner v-if="scanner" /><App v-else :pin-session="pinSession" /></div>
	</section>
</template>
<style scoped>
.till-viewport { height:100vh;height:100dvh;display:flex;flex-direction:column;min-width:0;overflow:hidden;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);background:#20261e; }
.till-workspace { display:flex;flex-direction:column;flex:1;min-height:0;min-width:0;overflow:hidden; }
.till-workspace :deep(.register-shell) { flex:1;height:auto;min-height:0; }
.till-workspace :deep(.item-manager) { flex:1;min-height:0;overflow:auto; }
.till-workspace :deep(> main) { min-height:0;overflow:auto;max-width:100%; }
.pin-session-bar { flex-shrink:0; }
.pin-session-bar > span { min-width:0;overflow-wrap:anywhere; }
.pin-session-bar > span:first-child { flex:1; }
.pin-session-bar button { flex-shrink:0;min-height:44px; }


.pin-screen {
	min-height: 100vh;
	display: grid;
	place-items: center;
	background: #f5f6ef;
	color: #20261e;
	padding: 24px;
	box-sizing: border-box;
	font-family: system-ui, sans-serif;
}
.pin-card {
	width: min(100%, 400px);
	box-sizing: border-box;
	background: white;
	border: 1px solid #dce0d2;
	border-radius: 20px;
	padding: 28px;
	box-shadow: 0 12px 40px #00000008;
}
.pin-card h1 {
	margin: 12px 0;
}
.pin-brand {
	font-weight: 800;
	color: #58622f;
}
.pin-card label {
	display: grid;
	gap: 8px;
	margin: 20px 0;
	font-weight: 600;
}
.pin-card input,
.pin-card select,
.pin-card button {
	font: inherit;
	min-height: 46px;
	border: 1px solid #c8cdbe;
	border-radius: 9px;
	padding: 10px;
	box-sizing: border-box;
}
.pin-card input {
	width: 100%;
	font-size: 20px;
}
.pin-card button {
	width: 100%;
	background: #e8f574;
	font-weight: 700;
	cursor: pointer;
}
.pin-card button:disabled {
	opacity: 0.5;
	cursor: wait;
}
.pin-card .pin-retry {
	margin-top: 12px;
	background: white;
}
.pin-help {
	font-size: 13px;
	color: #586050;
}
.pin-card [role="alert"] {
	color: #a11;
}
.pin-session-bar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	flex-wrap: wrap;
	padding: 8px 20px;
	background: #20261e;
	color: white;
	font:
		13px system-ui,
		sans-serif;
}
.pin-session-bar button {
	font: inherit;
	border: 1px solid #c8cdbe;
	background: white;
	color: #20261e;
	border-radius: 6px;
	padding: 8px;
	cursor: pointer;
}
@media(max-width:600px) { .pin-session-bar {padding:6px 10px;font-size:11px;gap:6px;} .pin-session-bar button {max-width:45%;white-space:normal;} .pin-card{padding:20px;} .pin-screen{padding:16px;min-height:100dvh;} }
</style>
