import { afterEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import CheckoutScanner from "../src/CheckoutScanner.vue";
let wrapper: ReturnType<typeof mount> | undefined;
afterEach(() => wrapper?.unmount());
it("passes a lossless barcode and prevents Enter form submission", async () => {
  const scan = vi.fn().mockResolvedValue(undefined);
  wrapper = mount(CheckoutScanner, {
    props: { language: "en", disabled: false, scan },
  });
  await wrapper.get("input").setValue(" 000Ab ");
  const event = new KeyboardEvent("keydown", {
    key: "Enter",
    bubbles: true,
    cancelable: true,
  });
  wrapper.get("input").element.dispatchEvent(event);
  await flushPromises();
  expect(event.defaultPrevented).toBe(true);
  expect(scan).toHaveBeenCalledExactlyOnceWith("000Ab");
  expect((wrapper.get("input").element as HTMLInputElement).value).toBe("");
});
it("ignores an accidental repeat Enter while the current scan is running", async () => {
  let resolve!: () => void;
  const scan = vi.fn(
    () =>
      new Promise<void>((r) => {
        resolve = r;
      }),
  );
  wrapper = mount(CheckoutScanner, {
    props: { language: "en", disabled: false, scan },
  });
  await wrapper.get("input").setValue("001");
  await wrapper.get("input").trigger("keydown", { key: "Enter" });
  await wrapper.get("input").trigger("keydown", { key: "Enter" });
  expect(scan).toHaveBeenCalledTimes(1);
  expect(wrapper.text()).toContain("Wait for the current scan");
  resolve();
  await flushPromises();
});
it("shows unknown barcode failures and disables scanning for a closed bill", async () => {
  const scan = vi.fn().mockRejectedValue(new Error("Barcode not found"));
  wrapper = mount(CheckoutScanner, {
    props: { language: "en", disabled: false, scan },
  });
  await wrapper.get("input").setValue("001");
  await wrapper.get("input").trigger("keydown", { key: "Enter" });
  await flushPromises();
  expect(wrapper.text()).toContain("Barcode not found");
  await wrapper.setProps({ disabled: true });
  await wrapper.get("input").setValue("002");
  await wrapper.get("input").trigger("keydown", { key: "Enter" });
  expect(scan).toHaveBeenCalledTimes(1);
});

it("serializes fast scans without losing repeated items", async () => {
  let first!: () => void;
  let count = 0;
  const scan = vi.fn(() =>
    ++count === 1
      ? new Promise<void>((r) => {
          first = r;
        })
      : Promise.resolve(),
  );
  wrapper = mount(CheckoutScanner, {
    props: { language: "en", disabled: false, scan },
  });
  for (const code of ["001", "001", "002"]) {
    await wrapper.get("input").setValue(code);
    await wrapper.get("input").trigger("keydown", { key: "Enter" });
  }
  expect(scan).toHaveBeenCalledTimes(1);
  first();
  await flushPromises();
  expect(scan.mock.calls.map((call) => call[0])).toEqual(["001", "001", "002"]);
});
