export function secureCameraMessage(): string | null {
  if (!window.isSecureContext)
    return "Camera scanning requires HTTPS. Use manual or USB input instead.";
  if (!navigator.mediaDevices?.getUserMedia)
    return "This browser has no camera support. Use manual or USB input instead.";
  return null;
}

export async function openCamera(
  video: HTMLVideoElement,
  device: string | undefined,
  accepted: (value: string) => void,
  failed: (message: string) => void,
) {
  let cancelled = false;
  let captured = false;
  let stream: MediaStream | undefined;
  let controls: { stop: () => void } | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = () => {
    cancelled = true;
    clearTimeout(timer);
    controls?.stop();
    stream?.getTracks().forEach((track) => track.stop());
    video.srcObject = null;
  };
  const ready = (async () => {
    try {
      const unsupported = secureCameraMessage();
      if (unsupported) throw new Error(unsupported);
      const { BrowserMultiFormatReader, BarcodeFormat } =
        await import("@zxing/browser");
      const { DecodeHintType } = await import("@zxing/library");
      if (cancelled) return;
      const reader = new BrowserMultiFormatReader(
        new Map([
          [
            DecodeHintType.POSSIBLE_FORMATS,
            [
              BarcodeFormat.EAN_13,
              BarcodeFormat.EAN_8,
              BarcodeFormat.UPC_A,
              BarcodeFormat.UPC_E,
              BarcodeFormat.CODE_128,
              BarcodeFormat.CODE_39,
              BarcodeFormat.ITF,
            ],
          ],
        ]),
      );
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: device
          ? { deviceId: { exact: device } }
          : { facingMode: { ideal: "environment" } },
      });
      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      controls = await reader.decodeFromStream(
        stream,
        video,
        (result, _error, scanner) => {
          if (!result || captured || cancelled) return;
          captured = true;
          scanner.stop();
          stop();
          accepted(result.getText());
        },
      );
      if (cancelled) {
        controls.stop();
        return;
      }
      timer = setTimeout(() => {
        stop();
        failed("No barcode found. Try better light or enter it manually.");
      }, 30000);
    } catch (error) {
      if (cancelled) return;
      stop();
      const name = (error as Error).name;
      failed(
        name === "NotAllowedError"
          ? "Camera permission denied. Allow camera access or use manual/USB input."
          : name === "NotFoundError"
            ? "No camera found. Use manual or USB input."
            : String((error as Error).message),
      );
    }
  })();
  return { stop, ready };
}
