import type {MaterialContext,MaterialRow} from './materials';
export interface PoolFilters {query:string;category_id:string;label:string;joined_days:string;review_status:string;target_label:string}
export interface PoolPacket {project_id:string;algorithm_id:string;image_ids:string[];action:'add'|'remove';expected_revision:string;operation_id:string;report_counts:true}
export interface PoolReceipt {operation_kind:string;operation_id:string;project_id:string;algorithm_id:string;action:'add'|'remove';negative_pool_revision:string;affected:number;added?:number;already_present?:number;removed?:number;already_absent?:number}
export interface PoolRow extends MaterialRow {negative_pool:{algorithm_id:string;joined_at?:string;categories?:{id:string;name:string;enabled?:boolean}[];review_status?:string;training_usage?:string|{state?:string;current_algorithm_trained?:boolean;other_algorithm_trained?:boolean};qualification?:string;algorithm_qualification?:string}}
export interface PoolPage {items:PoolRow[];page:number;page_size:number;total:number;total_pages?:number;negative_pool_revision:string;effective_label_codes?:string[];scope_kind?:string}
export interface PoolMemory {algorithmId:string;filters:PoolFilters;page:number;selected:string[]}
export interface PoolContext extends MaterialContext {memory:MaterialContext['memory']&{negativePool?:PoolMemory};poolPending:{value:unknown;save(value:PoolPacket|null):void};poolWrite(packet:PoolPacket):Promise<unknown>;legacyPool():void;createOperationId():string}
