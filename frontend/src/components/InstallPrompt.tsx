import { useEffect, useState } from "react";
import { Share, X } from "lucide-react";

const KEY = "finance.installPromptDismissed";

function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iPhone|iPad|iPod/i.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
}

function isStandalone(): boolean {
  // iOS Safari sets navigator.standalone; other browsers use display-mode media query
  const navStandalone = (navigator as unknown as { standalone?: boolean })
    .standalone;
  return (
    navStandalone === true ||
    window.matchMedia?.("(display-mode: standalone)").matches
  );
}

export function InstallPrompt() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (isStandalone()) return;
    if (!isIos()) return;
    try {
      if (localStorage.getItem(KEY)) return;
    } catch {
      // localStorage blocked — skip silently
      return;
    }
    const t = window.setTimeout(() => setShow(true), 1200);
    return () => window.clearTimeout(t);
  }, []);

  if (!show) return null;

  function dismiss() {
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      // ignore
    }
    setShow(false);
  }

  return (
    <div
      className="fixed inset-x-0 bottom-0 z-40 px-4 pb-[calc(4rem+env(safe-area-inset-bottom))]"
      role="dialog"
      aria-label="Install Finance"
    >
      <div className="mx-auto max-w-lg rounded-xl bg-gray-900 text-white shadow-2xl p-4 flex items-start gap-3">
        <div className="flex-1 text-sm leading-snug">
          <p className="font-semibold mb-1">Install Finance</p>
          <p className="text-gray-200">
            Tap{" "}
            <Share className="inline h-3.5 w-3.5 -mt-0.5 text-sky-300" />{" "}
            in Safari, then <span className="font-medium">Add to Home Screen</span>{" "}
            for the full-screen experience.
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          className="text-gray-400 hover:text-white p-1 -m-1"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
