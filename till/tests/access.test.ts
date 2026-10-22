import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import TillAccess from "../src/TillAccess.vue";
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../../ui/client", () => ({ get: api.get, post: api.post }));
vi.mock("../src/App.vue", () => ({
  default: {
    props: ["pinSession"],
    template: '<div data-test="till">Till ready</div>',
  },
}));
vi.mock("../src/PhoneScanner.vue", () => ({
  default: { template: '<div data-test="scanner">Scanner ready</div>' },
}));
let wrapper: ReturnType<typeof mount> | undefined;
beforeEach(() => {
  sessionStorage.clear();
  history.replaceState(null, "", "/till");
  api.get.mockReset();
  api.post.mockReset();
  window.csrf_token = "guest-csrf";
  api.get.mockResolvedValue({
    authenticated: false,
    pin_session: false,
    user: null,
  });
});
afterEach(() => {
  wrapper?.unmount();
});
it("shows the PIN screen to guests and does not mount the Till", async () => {
  wrapper = mount(TillAccess);
  await flushPromises();
  expect(wrapper.text()).toContain("No ERPNext login is needed");
  expect(wrapper.find("[data-test=till]").exists()).toBe(false);
  expect(wrapper.get("input[name=pin-secret]").attributes("type")).toBe(
    "password",
  );
});
it("uses the PIN API, clears the secret, updates CSRF and mounts the Till", async () => {
  api.post.mockResolvedValue({
    csrf_token: "new-csrf",
    user: "cashier@example.com",
  });
  wrapper = mount(TillAccess);
  await flushPromises();
  await wrapper.get("input[name=staff-code]").setValue("cashier-a");
  await wrapper.get("input[name=pin-secret]").setValue("001234");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  expect(api.post).toHaveBeenCalledWith("pin_auth.login", {
    login_code: "cashier-a",
    pin_secret: "001234",
  });
  expect(window.csrf_token).toBe("new-csrf");
  expect(wrapper.find("[data-test=till]").exists()).toBe(true);
});
it("keeps an invalid PIN locked and does not retain it in the field", async () => {
  api.post.mockRejectedValue(new Error("Incorrect staff code or PIN"));
  wrapper = mount(TillAccess);
  await flushPromises();
  await wrapper.get("input[name=staff-code]").setValue("staff-a");
  await wrapper.get("input[name=pin-secret]").setValue("111111");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  expect(wrapper.text()).toContain("Incorrect staff code or PIN");
  expect(
    (wrapper.get("input[name=pin-secret]").element as HTMLInputElement).value,
  ).toBe("");
  expect(wrapper.find("[data-test=till]").exists()).toBe(false);
});
it("preserves a scanner link through PIN login without a query-string secret", async () => {
  const token = "x".repeat(43);
  history.replaceState(null, "", "/till?scanner=usb#" + token);
  wrapper = mount(TillAccess);
  await flushPromises();
  expect(location.hash).toBe("");
  expect(sessionStorage.getItem("trt-phone-token")).toBe(token);
  api.post.mockResolvedValue({
    csrf_token: "new-csrf",
    user: "cashier@example.com",
  });
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  await vi.dynamicImportSettled();
  await flushPromises();
  expect(wrapper.find("[data-test=scanner]").exists()).toBe(true);
});
it("unmounts the Till when a revoked or expired session is detected", async () => {
  api.get.mockResolvedValueOnce({
    authenticated: true,
    pin_session: true,
    user: "staff-a",
  });
  wrapper = mount(TillAccess);
  await flushPromises();
  expect(wrapper.find("[data-test=till]").exists()).toBe(true);
  api.get.mockResolvedValue({
    authenticated: false,
    pin_session: true,
    user: null,
  });
  window.dispatchEvent(new Event("trt-auth-check"));
  await flushPromises();
  expect(wrapper.find("[data-test=till]").exists()).toBe(false);
});
