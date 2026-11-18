declare module '*static/modules/api.js' {
  export function messageFromApiError(error:Record<string,unknown>):string;
  export function withRequestDeadline<T>(operation:(signal:AbortSignal)=>Promise<T>,options:{signal?:AbortSignal;mutation?:boolean}):Promise<T>;
}
declare module '*static/auth-session.js' {}
