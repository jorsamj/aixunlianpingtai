declare module '*static/modules/api.js' {
  export function messageFromApiError(error:Record<string,unknown>):string;
  export function withRequestDeadline<T>(operation:(signal:AbortSignal)=>Promise<T>,options:{signal?:AbortSignal;mutation?:boolean}):Promise<T>;
}
declare module '*static/auth-session.js' {}

declare module '*static/modules/annotation-task-view.js' {
  export interface AnnotationTaskViewModel {
    status: string;
    statusText: string;
    percent: number;
    completed: number;
    total: number;
    failed: number;
    remaining: number;
    generated: number;
    boxes: number;
    progressText: string;
    queuePosition: number;
    waitReason: string;
    workerId: string;
    attempt: number;
    runtimeText: string;
    executionText: string;
    active: boolean;
    canCancel: boolean;
    canReview: boolean;
    canRetry: boolean;
    canRecoverReview: boolean;
    accepted: boolean | null;
    error: string;
  }
  export function annotationTaskView(task: Record<string, unknown>): AnnotationTaskViewModel;
}

// Existing legacy status/eligibility projection for training jobs. Reused so
// the native page never re-derives pause/resume/delete permissions.
declare module '*static/modules/training-task-runtime.js' {
  export function trainingBatchActionEligible(
    job: Record<string, unknown>, action: 'pause' | 'resume' | 'stop' | 'delete' | string,
  ): boolean;
}
declare module '*static/modules/task-runtime-truth.js' {
  export function trainingDisplayStatus(task: Record<string, unknown>): string;
}

declare module '*static/modules/annotation-geometry-adapter.js' {
  import type {AiEditorBox} from '../types/ai-editor';
  export function withLegacyBoxIdentities(boxes:Partial<AiEditorBox>[],options:{imageId:string}):AiEditorBox[];
}
declare module '*static/modules/annotorious-editor.js' {
  import type {AiEditorBox,AiEditorDomRefs,AiEditorSnapshot} from '../types/ai-editor';
  import type {ReviewLabel} from '../api/ai-review';
  interface Kernel {
    sync(value:{label?:ReviewLabel|null;locked?:boolean;selectedId?:string|number|null}):void;
    select(id:string|number):boolean;deleteSelected():boolean;reclassSelected(label:string):boolean;
    setMode(mode:string):void;setVisibility(value:boolean):void;setClassFilter(codes:string[]|null):void;
    fit():void;zoom(delta:number):void;resetZoom():void;flush():boolean;destroy():void;
    snapshot():NonNullable<AiEditorSnapshot['view']>;
  }
  interface EditorOptions extends AiEditorDomRefs {
    signal:AbortSignal;getBoxes():AiEditorBox[];getLabels():ReviewLabel[];getLabel():ReviewLabel|null;
    isActive():boolean;onCommit(boxes:AiEditorBox[]):void;onSelect(id:string|null):void;
    onSave():void;onUndo():void;onRedo():void;onChooseLabel(label:ReviewLabel):void;
    onError(error:unknown):void;onViewportChange(view:{scale:number}):void;
    onModeChange(mode:string):void;onVisibilityChange(visible:boolean):void;
  }
  export function createAnnotoriousEditor(options:EditorOptions):Promise<Kernel>;
}
