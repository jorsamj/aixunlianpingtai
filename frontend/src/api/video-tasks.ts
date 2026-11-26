import {request} from '../app/http';
import {normalizeVideoTask, videoTaskFormValues} from '../../../static/modules/video-tasks.js';

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
    async byRequest(requestId: string, signal: AbortSignal) {
      const value = await request<{request_id:string;task:VideoRecord}>(url + '/by-request/' + encodeURIComponent(requestId), {signal});
      if (value.request_id !== requestId) throw new Error('切帧请求回执身份不一致');
      return checked(value.task);
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
