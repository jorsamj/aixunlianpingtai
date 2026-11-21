// Reuse the offline vendor bundle through its CommonJS export.
// @ts-expect-error The checked-in distribution has no TypeScript declarations.
import echarts from '../../../static/vendor/echarts/echarts.min.js';

type Chart = {
  setOption(options: Record<string, unknown>): void;
  resize(): void;
  dispose(): void;
};
export const init = (element: HTMLElement): Chart => echarts.init(element);
