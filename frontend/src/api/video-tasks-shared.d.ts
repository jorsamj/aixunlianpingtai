declare module '*static/modules/video-tasks.js' {
  export function normalizeVideoTask(task: object): {
    status: string;
    statusText: string;
    samplingText: string;
    runtimeText: string;
    progress: number;
    extractedFrames: number;
  };
  export function isActiveVideoTask(task: {status: string}): boolean;
  export function videoTaskFormValues(mode: string, values: {
    intervalSeconds: number;
    extractFps: number;
    fixedCount: number;
    maxFrames: number;
  }): Record<string, string | number>;
}
