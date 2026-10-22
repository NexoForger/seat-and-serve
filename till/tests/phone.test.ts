import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import PhoneScanner from "../src/PhoneScanner.vue";
import CameraScanner from "../src/CameraScanner.vue";
const api = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("../../ui/client", () => ({
  post: api.post,
  eventId: () => "unique-scan-id",
}));
let wrapper: ReturnType<typeof mount> | undefined;
beforeEach(() => {
  sessionStorage.clear();
  history.replaceState(null, "", "/till?scanner=phone#pair-secret");
});
afterEach(() => {
  wrapper?.unmount();
});
it("keeps pairing through login without a secret in the login URL", async () => {
  api.post.mockRejectedValue(new Error("Sign in"));
  wrapper = mount(PhoneScanner);
  await flushPromises();
  expect(location.hash).toBe("");
  expect(sessionStorage.getItem("trt-phone-token")).toBe("pair-secret");
  expect(wrapper.get("a").attributes("href")).not.toContain("pair-secret");
});
it("delivers one capture with the draft and retries the same scan ID", async () => {
  let scans = 0;
  api.post.mockImplementation((_method, args) => {
    if (args.action === "join")
      return Promise.resolve({
        phone_secret: "phone-secret",
        draft: "draft-a",
      });
    if (args.action === "state")
      return Promise.resolve({ draft: "draft-a", pending: false });
    if (args.action === "scan" && scans++ === 0)
      return Promise.reject(new Error("Response lost"));
    return Promise.resolve({});
  });
  wrapper = mount(PhoneScanner, { global: { stubs: { CameraScanner: true } } });
  await flushPromises();
  await wrapper
    .findAll("button")
    .find((b) => b.text() === "Scan next")!
    .trigger("click");
  await flushPromises();
  wrapper.getComponent(CameraScanner).vm.$emit("scanned", "000123");
  await flushPromises();
  expect(wrapper.findComponent(CameraScanner).exists()).toBe(false);
  await wrapper
    .findAll("button")
    .find((b) => b.text().includes("Retry delivery"))!
    .trigger("click");
  await flushPromises();
  const calls = api.post.mock.calls.filter(
    ([, args]) => args.action === "scan",
  );
  expect(calls).toHaveLength(2);
  expect(calls[0][1]).toEqual(calls[1][1]);
  expect(calls[0][1]).toMatchObject({
    draft: "draft-a",
    barcode: "000123",
    phone_secret: "phone-secret",
  });
  expect(
    api.post.mock.calls.every(([method]) => method === "barcodes.exchange"),
  ).toBe(true);
});
