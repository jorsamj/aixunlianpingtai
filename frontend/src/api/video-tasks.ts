import {request} from '../app/http';
import {normalizeVideoTask, videoTaskFormValues} from '../../../static/modules/video-tasks.js';
import {digestHex, sha256Bytes} from './file-digest';

interface VideoRecord {
  id: string;
  request_id?: string;
  project_id: string;
  kind: string;
  video_name?: string;
  split: string;
  dataset_id: string;
  max_frames?: number;
  current_item?: string;
  created_at?: string;
  finished_at?: string;
  error?: string;
  result?: {output_ref?: string; extracted_frames?: number};
}

export function videoCreationRequestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return 'video_' + Array.from(bytes, byte => byte.toString(16).padStart(2,'0')).join('');
}

export type VideoTask = ReturnType<typeof normalizeVideoTask> & VideoRecord;
export type VideoRecovery =
  | {state: 'ACCEPTED' | 'TERMINAL'; task: VideoTask}
  | {state: 'IN_FLIGHT' | 'UNREGISTERED' | 'STAGED' | 'UNVERIFIED_INPUT' | 'RETIRED'};

// Hash every byte using bounded reads. This fingerprint is for browser reselection;
// the task payload still uses the server's full-file SHA-256.
export async function videoFileFingerprint(file: File, signal: AbortSignal) {
  const chunkSize = 4 * 1024 * 1024;
  const digest = new Uint8Array(32 * Math.ceil(file.size / chunkSize));
  for (let offset = 0; offset < file.size; offset += chunkSize) {
    signal.throwIfAborted();
    const bytes = await file.slice(offset, offset + chunkSize).arrayBuffer();
    digest.set(await sha256Bytes(bytes), (offset / chunkSize) * 32);
  }
  signal.throwIfAborted();
  return digestHex(await sha256Bytes(digest.buffer));
}

export function videoTasks(projectId: string) {
  const url = '/api/v33/projects/' + encodeURIComponent(projectId) + '/video-tasks';
  const taskUrl = (taskId: string) => url + '/' + encodeURIComponent(taskId);
  function checked(row: VideoRecord, id?: string) {
    if (!row?.id || row.project_id !== projectId || row.kind !== 'VIDEO_FRAMES' || (id && row.id !== id))
      throw new Error('切帧任务回执身份不一致');
    return normalizeVideoTask(row) as VideoTask;
  }
  return {
    async list(cursor: string, signal: AbortSignal) {
      const query = cursor ? '?cursor=' + encodeURIComponent(cursor) : '';
      const page = await request<{items: VideoRecord[]; next_cursor?: string}>(url + query, {signal});
      return {items: page.items.map(item => checked(item)), next: page.next_cursor || ''};
    },
    async detail(taskId: string, signal: AbortSignal) {
      return checked(await request<VideoRecord>(taskUrl(taskId), {signal}), taskId);
    },
    async byRequest(requestId: string, signal: AbortSignal): Promise<VideoRecovery> {
      const path = url + '/by-request/' + encodeURIComponent(requestId) + '?recovery=true';
      const value = await request<{request_id:string;state:VideoRecovery['state'];task?:VideoRecord}>(path, {signal});
      if (value.request_id !== requestId) throw new Error('切帧请求回执身份不一致');
      switch (value.state) {
        case 'ACCEPTED':
        case 'TERMINAL':
          if (value.task) return {state:value.state, task:checked(value.task)};
          break;
        case 'IN_FLIGHT':
        case 'UNREGISTERED':
        case 'STAGED':
        case 'UNVERIFIED_INPUT':
        case 'RETIRED':
          if (!value.task) return {state:value.state};
      }
      throw new Error('切帧请求回执状态无效');
    },
    async create(video: File, split: string, values: ReturnType<typeof videoTaskFormValues>, requestId: string, signal: AbortSignal) {
      const body = new FormData();
      body.set('video', video);
      body.set('split', split);
      body.set('dataset_id', 'default');
      body.set('backend', 'auto');
      for (const [key, value] of Object.entries(values)) body.set(key, String(value));
      body.set('request_id', requestId);
      const value = await request<VideoRecord>(url, {method: 'POST', body, signal}, 120000);
      if (value.request_id !== requestId) throw new Error('切帧创建回执身份不一致');
      return checked(value);
    },
    stop: (taskId: string) => request(taskUrl(taskId) + '/stop', {method: 'POST'}),
  };
}
