import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { defineComponent, ref } from "vue";
import BarcodeField from "../src/BarcodeField.vue";
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), serial: 0 }));
vi.mock("../../ui/client", () => ({
  get: api.get,
  post: api.post,
  eventId: () => `id-${++api.serial}`,
}));
vi.mock("qrcode", () => ({toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,test")}));
const wrappers: ReturnType<typeof mount>[] = [];
function form(initial = "") {
  const Host = defineComponent({
    components: { BarcodeField },
    setup: () => ({ code: ref(initial) }),
    template:
      '<form><BarcodeField v-model="code" outlet="OUT" language="en" :disabled="false" /></form>',
  });
  const wrapper = mount(Host, { attachTo: document.body });
  wrappers.push(wrapper);
  return wrapper;
}
beforeEach(() => {
  api.get.mockResolvedValue({ available: true });
  api.post.mockResolvedValue({});
});
afterEach(() => {
  wrappers.forEach((w) => w.unmount());
  wrappers.length = 0;
  vi.useRealTimers();
});
describe("HID and item draft", () => {
  it("Enter accepts a string barcode without form submission; Tab is not prevented", async () => {
    const w = form();
    const submit = vi.fn();
    w.element.addEventListener("submit", submit);
    const input = w.get("input");
    await input.setValue(" 001Ab ");
    const enter = new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    });
    input.element.dispatchEvent(enter);
    await flushPromises();
    expect(enter.defaultPrevented).toBe(true);
    expect(submit).not.toHaveBeenCalled();
    expect(w.vm.code).toBe("001Ab");
    const tab = new KeyboardEvent("keydown", {
      key: "Tab",
      bubbles: true,
      cancelable: true,
    });
    input.element.dispatchEvent(tab);
    await flushPromises();
    expect(tab.defaultPrevented).toBe(false);
  });
  it("confirms replacements, blocks duplicates and resets/focuses after saving", async () => {
    const w = form("001");
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await w.get("input").setValue("002");
    await w.get("input").trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(w.vm.code).toBe("001");
    vi.mocked(window.confirm).mockReturnValue(true);
    api.get.mockResolvedValue({ available: false });
    await w.get("input").setValue("002");
    await w.get("input").trigger("keydown", { key: "Enter" });
    await flushPromises();
    const child = w.getComponent(BarcodeField);
    expect(await child.vm.prepareSave()).toBe(false);
    expect(w.text()).toContain("already assigned");
    await child.vm.reset();
    await flushPromises();
    expect(w.vm.code).toBe("");
    expect(document.activeElement).toBe(w.get("input").element);
  });
  it("waits for a blur lookup before preparing the save", async () => {
    const w = form();
    let resolve!: (value: unknown) => void;
    api.get.mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    await w.get("input").setValue("0007");
    await w.get("input").trigger("blur");
    const ready = w.getComponent(BarcodeField).vm.prepareSave();
    resolve({ available: true });
    await expect(ready).resolves.toBe(true);
    expect(w.vm.code).toBe("0007");
  });
  it("rejects a delayed relay response after clearing the draft", async () => {
    vi.useFakeTimers();
    const w = form();
    api.post.mockImplementation((method, args) => {
      if (method === "barcodes.start")
        return Promise.resolve({ token: "token", desktop_secret: "secret" });
      if (args.action === "poll")
        return new Promise((resolve) => {
          pollResolve = resolve;
        });
      return Promise.resolve({});
    });
    let pollResolve!: (value: unknown) => void;
    await w
      .findAll("button")
      .find((b) => b.text() === "Pair phone")!
      .trigger("click");
    await flushPromises();
    await vi.dynamicImportSettled();
    await flushPromises();
    expect(w.find("img").exists()).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    await w.getComponent(BarcodeField).vm.reset();
    pollResolve({
      paired: true,
      scan: { barcode: "STALE", draft: "old", scan_id: "old" },
    });
    await flushPromises();
    expect(w.vm.code).toBe("");
  });
});
