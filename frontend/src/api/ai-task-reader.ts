import type {AiTaskPage} from '../types/ai-tasks';
// Read-only owner of the existing v60 annotation-task list GET. The legacy
// pilot reader stays untouched; this one is the native /app projection.
interface ReadOwner {projectId:string;get<T>(url:string,options?:{signal?:AbortSignal}):Promise<T>}
export function aiTaskReaderApi(context:ReadOwner){
 const base=`/api/v60/projects/${encodeURIComponent(context.projectId)}/annotation-tasks`;
 return {
  async tasks(status:string,cursor:string,signal:AbortSignal,limit=20){
   if(!Number.isInteger(limit)||limit<1||limit>20)throw new Error('AI任务读取数量超出边界');
   const query=new URLSearchParams({reader_view:'true',limit:String(limit)});
   if(status)query.set('status',status);
   if(cursor)query.set('cursor',cursor);
   const result=await context.get<AiTaskPage>(`${base}?${query}`,{signal});
   if(result?.ok!==true||result.project_id!==context.projectId)throw new Error('AI任务响应项目身份不一致');
   if(!Array.isArray(result.items)||result.items.some(row=>row.project_id!==context.projectId))throw new Error('AI任务分页身份不一致');
   if(result.next_cursor!==null&&typeof result.next_cursor!=='string')throw new Error('AI任务分页游标无效');
   return result;
  },
 };
}
