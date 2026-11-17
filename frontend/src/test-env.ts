import { builtinEnvironments } from "vitest/environments";
import type { Environment } from "vitest/environments";

const customEnv: Environment = {
  name: "custom-jsdom",
  transformMode: "web",
  setup(global, options) {
    return builtinEnvironments.jsdom.setup(global, options);
  },
};

export default customEnv;

