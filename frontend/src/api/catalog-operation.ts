import type {CatalogOperation,CatalogReceipt} from '../types/catalog';

interface Transport {post(operation:CatalogOperation):Promise<unknown>;receipt(id:string):Promise<unknown>}
const rejected=new Set(['CATALOG_INVALID_REQUEST','CATALOG_VALIDATION_FAILED','CATALOG_REVISION_CONFLICT','CATALOG_NOT_FOUND','CATALOG_ID_IMMUTABLE','CATALOG_DUPLICATE_NAME','CATALOG_DUPLICATE_CODE','CATALOG_REFERENCED','CATALOG_DELETE_CONFIRMATION_REQUIRED','CATALOG_REFERENCE_CHECK_FAILED','CATALOG_BUSY','AUTH_REQUIRED','HTTP_401','HTTP_403']);
export function definiteRejection(error:unknown){return rejected.has(String((error as {code?:string})?.code||''))}
function checked(value:unknown,operation:CatalogOperation):CatalogReceipt{
 const result=value as CatalogReceipt;
 if(result?.ok!==true||result.operation_id!==operation.operation_id||result.entity!==operation.entity||result.action!==operation.action||typeof result.id!=='string'||!result.id||(operation.id&&result.id!==operation.id)||!Number.isInteger(result.revision)||result.revision<=operation.expected_revision||(operation.action==='delete'?result.item!==null:result.item?.id!==result.id))throw new Error('操作回执身份或格式不一致，结果待确认');
 return result;
}
export async function recoverCatalogOperation(api:Transport,operation:CatalogOperation,replay=false):Promise<CatalogReceipt>{
 try{return checked(await api.receipt(operation.operation_id),operation)}
 catch(error){
  if(replay&&(error as {code?:string}).code==='CATALOG_OPERATION_NOT_FOUND')return checked(await api.post(operation),operation);
  throw new Error(`提交结果待确认，请查询回执或使用原请求恢复。${error instanceof Error?error.message:''}`);
 }
}
export async function submitCatalogOperation(api:Transport,operation:CatalogOperation):Promise<CatalogReceipt>{
 try{return checked(await api.post(operation),operation)}
 catch(error){if(definiteRejection(error))throw error;return recoverCatalogOperation(api,operation)}
}
