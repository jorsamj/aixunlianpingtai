export type Entity = 'vendors' | 'chips';
export interface ResourceFact {resource_id:string;resource_name:string;ready?:boolean;sdk_version?:string;message?:string;last_checked_at?:string;allowed_precisions?:string[]}
export interface CatalogRecord {id:string;name:string;enabled?:boolean;template_id?:string;template_name?:string;vendor_id?:string;vendor_name?:string;code?:string;sdk_code?:string;chip_count?:number;enabled_chip_count?:number;implemented?:boolean;capability?:{sdk_ready?:boolean;allowed_precisions?:string[];resources?:ResourceFact[]}}
export interface CatalogPage {ok:boolean;items:CatalogRecord[];page:number;page_size:number;total:number;revision:number;templates:{id:string;name:string}[]}
export interface CatalogDetail {ok:boolean;item:CatalogRecord;revision:number;references:{reference_count?:number;check_status?:string;diagnostic?:{code?:string;detail?:string;solution?:string}}}
export interface PreviewContext {signal:AbortSignal;get<T>(url:string,options?:{signal?:AbortSignal}):Promise<T>;returnToManagement():void}
export interface Filters {query:string;enabled:string;template_id:string;page:number;sort:string}
