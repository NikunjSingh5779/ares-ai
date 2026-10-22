import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// React 19 only expects act() warnings inside test environments that opt in.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

// jsdom does not implement scrolling; chat scrolls to the newest message.
Element.prototype.scrollIntoView = vi.fn();

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
});
