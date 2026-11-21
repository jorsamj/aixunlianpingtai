export interface DeviceReport {id?:string;index?:number;name?:string;utilization_percent?:number;memory_used_bytes?:number;memory_total_bytes?:number;memory_free_bytes?:number;temperature_c?:number}
export interface NodeTask {task_id?:string;kind?:string;status?:string;stage?:string;progress?:number}
export interface ServiceNode {node_id:string;display_name?:string;connection_mode?:string;status?:string;hostname?:string;last_heartbeat_at?:string;heartbeat_age_seconds?:number;os_name?:string;os_version?:string;architecture?:string;agent_version?:string;build_id?:string;allowed_capabilities?:string[];reported_capabilities?:string[];effective_capabilities?:string[];last_error?:string;
 resources?:{cpu?:{usage_percent?:number;physical_cores?:number;logical_cores?:number};memory?:{usage_percent?:number;used_bytes?:number;total_bytes?:number;available_bytes?:number};gpu?:{gpus?:DeviceReport[];error?:string};disk?:{free_bytes?:number;total_bytes?:number}};
 runtime?:{torch_version?:string;cuda_version?:string;cuda_available?:boolean};
 workers?:{worker_id?:string;online?:boolean;roles?:string[]}[];durable_tasks?:NodeTask[];reported_active_tasks?:NodeTask[]}
export interface ServiceNodeList {items:ServiceNode[];supported_capabilities:string[]}
