import { beforeEach, describe, expect, it, vi } from "vitest";
import { openCamera, secureCameraMessage } from "../src/camera";
const decoder = vi.hoisted(() => ({ decode: vi.fn() }));
vi.mock("@zxing/browser", () => ({
  BrowserMultiFormatReader: class {
    decodeFromStream = decoder.decode;
  },
  BarcodeFormat: {},
}));
vi.mock("@zxing/library", () => ({ DecodeHintType: { POSSIBLE_FORMATS: 1 } }));
beforeEach(() => {
  Object.defineProperty(window, "isSecureContext", {
    value: true,
    configurable: true,
  });
});
describe("camera lifecycle", () => {
  it("reports insecure and unsupported browsers", () => {
    Object.defineProperty(window, "isSecureContext", {
      value: false,
      configurable: true,
    });
    expect(secureCameraMessage()).toContain("HTTPS");
    Object.defineProperty(window, "isSecureContext", {
      value: true,
      configurable: true,
    });
    Object.defineProperty(navigator, "mediaDevices", {
      value: undefined,
      configurable: true,
    });
    expect(secureCameraMessage()).toContain("no camera support");
  });
  it("reports permission denial", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi
          .fn()
          .mockRejectedValue(new DOMException("denied", "NotAllowedError")),
      },
      configurable: true,
    });
    const failed = vi.fn();
    const session = await openCamera(
      document.createElement("video"),
      undefined,
      vi.fn(),
      failed,
    );
    await session.ready;
    expect(failed).toHaveBeenCalledWith(
      expect.stringContaining("permission denied"),
    );
  });
  it("accepts one result, requests rear camera, and releases the stream", async () => {
    const stop = vi.fn();
    const getUserMedia = vi
      .fn()
      .mockResolvedValue({ getTracks: () => [{ stop }] });
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia },
      configurable: true,
    });
    let callback!: Function;
    const controls = { stop: vi.fn() };
    decoder.decode.mockImplementation(async (_s, _v, cb) => {
      callback = cb;
      return controls;
    });
    const accepted = vi.fn();
    const video = document.createElement("video");
    const session = await openCamera(video, undefined, accepted, vi.fn());
    await session.ready;
    callback({ getText: () => "00123" }, null, controls);
    callback({ getText: () => "other" }, null, controls);
    expect(accepted).toHaveBeenCalledExactlyOnceWith("00123");
    expect(stop).toHaveBeenCalled();
    expect(video.srcObject).toBeNull();
    expect(getUserMedia.mock.calls[0][0].video.facingMode.ideal).toBe(
      "environment",
    );
  });
  it("releases a stream granted after cancellation", async () => {
    let grant!: (s: unknown) => void;
    const stop = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn(
          () =>
            new Promise((r) => {
              grant = r;
            }),
        ),
      },
      configurable: true,
    });
    const accepted = vi.fn();
    const session = await openCamera(
      document.createElement("video"),
      undefined,
      accepted,
      vi.fn(),
    );
    for (let i = 0; i < 20 && !grant; i++) await Promise.resolve();
    session.stop();
    grant({ getTracks: () => [{ stop }] });
    await session.ready;
    expect(stop).toHaveBeenCalled();
    expect(accepted).not.toHaveBeenCalled();
  });
});

it("reports a missing camera and stops an active stream on explicit cancellation", async () => {
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi
        .fn()
        .mockRejectedValue(new DOMException("missing", "NotFoundError")),
    },
    configurable: true,
  });
  const failed = vi.fn();
  const missing = await openCamera(
    document.createElement("video"),
    undefined,
    vi.fn(),
    failed,
  );
  await missing.ready;
  expect(failed).toHaveBeenCalledWith(
    expect.stringContaining("No camera found"),
  );
  const stop = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }),
    },
    configurable: true,
  });
  decoder.decode.mockResolvedValue({ stop: vi.fn() });
  const active = await openCamera(
    document.createElement("video"),
    "front-camera",
    vi.fn(),
    vi.fn(),
  );
  await active.ready;
  active.stop();
  expect(stop).toHaveBeenCalled();
});
