export type Entity = 'vendors' | 'chips';
export interface ResourceFact {resource_id:string;resource_name:string;ready?:boolean;status?:string;status_label?:string;sdk_version?:string;message?:string;last_checked_at?:string;allowed_precisions?:string[]}
export interface CatalogRecord {id:string;name:string;enabled?:boolean;template_id?:string;template_name?:string;vendor_id?:string;vendor_name?:string;code?:string;sdk_code?:string;chip_count?:number;enabled_chip_count?:number;implemented?:boolean;capability?:{sdk_ready?:boolean;status?:string;status_label?:string;allowed_precisions?:string[];resources?:ResourceFact[]}}
export interface CatalogPage {ok:boolean;items:CatalogRecord[];page:number;page_size:number;total:number;revision:number;templates:{id:string;name:string}[]}
export interface CatalogReferences {reference_count?:number;check_status?:string;can_delete?:boolean;solution?:string;references?:{kind?:string;id?:string;type?:string;identity?:string}[];diagnostics?:{code?:string;task_id?:string;resolved_path?:string;original_path?:string}[];diagnostic?:{code?:string;detail?:string;solution?:string}}
export interface CatalogDetail {ok:boolean;item:CatalogRecord;revision:number;references:CatalogReferences}
export type CatalogAction='create'|'update'|'enable'|'disable'|'delete';
export interface CatalogOperation {entity:Entity;action:CatalogAction;operation_id:string;expected_revision:number;id?:string;record?:Partial<CatalogRecord>;confirm_delete?:boolean}
export interface CatalogReceipt {ok:boolean;operation_id:string;entity:Entity;action:CatalogAction;id:string;item:CatalogRecord|null;revision:number;replayed?:boolean}
export interface PendingSlot {value:CatalogOperation|null;save(value:CatalogOperation|null):void}
export interface PreviewContext {signal:AbortSignal;get<T>(url:string,options?:{signal?:AbortSignal}):Promise<T>;returnToManagement():void;openConfiguration?():void;openResource?(kind:string):void;management?:boolean;post?<T>(url:string,body:unknown):Promise<T>;createOperationId?():string;pending?:PendingSlot;invalidate?():void}
export interface Filters {query:string;enabled:string;template_id:string;page:number;sort:string}
