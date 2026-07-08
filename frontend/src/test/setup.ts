import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

let nextRandomId = 1;

beforeEach(() => {
  vi.stubGlobal("crypto", {
    ...globalThis.crypto,
    randomUUID: vi.fn(() => `test-id-${nextRandomId++}`),
  });

  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi.fn(),
    },
  });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
