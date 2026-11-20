export interface AiEditorBox {
  id: string | number;
  label: string;
  class_id?: string | number | null;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  [key: string]: unknown;
}
export interface AiEditorSnapshot {
  imageId: string;
  url: string;
  filename: string;
  width: number;
  height: number;
  boxes: AiEditorBox[];
  labels: {code: string; display_name?: string; name?: string}[];
  activeBox: number | null;
  labelCode: string;
  filterCode?: string;
  dirty: boolean;
  saving: boolean;
  pending: boolean;
  error?: string;
  status?: string;
  revision?: string | number;
  view?: {mode: string; visible: boolean; scale: number};
  conflict?: boolean;
  retryPending?: boolean;
  saveDisabled?: boolean;
  editingDisabled?: boolean;
}
// An opaque original-owner handle. The Vue shell never edits the kernel.
export type AiEditorHandle = object;
export interface AiEditorDomRefs {
  image: HTMLImageElement;
  viewport: HTMLElement;
  world: HTMLElement;
  root: HTMLElement;
}
export interface AiEditorContext {
  mount(refs: AiEditorDomRefs): Promise<AiEditorHandle | void>;
  // Undefined releases this context's pending mount; handles release only that instance.
  release(handle?: AiEditorHandle): void;
  actions: {
    mode(value: string): unknown;
    label(code: string): unknown;
    select(index: number): unknown;
    reclass(index: number, code: string): unknown;
    remove(index: number): unknown;
    undo(): unknown;
    redo(): unknown;
    visibility(): unknown;
    filter(code: string): unknown;
    zoom(delta: number): unknown;
    fit(): unknown;
    resetZoom(): unknown;
    save(): unknown;
    reload(): unknown;
    cancel(): unknown;
  };
}
