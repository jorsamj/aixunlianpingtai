import type {CatalogPage,CatalogDetail,CatalogOperation,CatalogReceipt,Entity,Filters,PreviewContext} from '../types/catalog';
export function catalogApi(context:PreviewContext) {
  const base='/api/v39/deploy/catalog/records';
  return {
    post(operation:CatalogOperation){if(!context.post)throw new Error('只读页面不允许写入');return context.post<CatalogReceipt>('/api/v39/deploy/catalog/operations',operation)},
    receipt(id:string){return context.get<CatalogReceipt>(`/api/v39/deploy/catalog/operations/${encodeURIComponent(id)}`)},
    detect(id:string){if(!context.post)throw new Error('只读页面不允许检测');return context.post<{ok:boolean;id:string;capability:NonNullable<CatalogDetail['item']['capability']>}>(`/api/v39/deploy/catalog/chips/${encodeURIComponent(id)}/detect`,{})},
    list(entity:Entity,filters:Filters,vendor:string,signal:AbortSignal) {
      const query=new URLSearchParams({entity,...Object.fromEntries(Object.entries(filters).map(([k,v])=>[k,String(v)])),page_size:'10',observe_only:'true'});
      if(entity==='chips')query.set('vendor_id',vendor);
      return context.get<CatalogPage>(`${base}?${query}`,{signal}).then(value=>{
        if(value.ok!==true||!Array.isArray(value.items)||!Array.isArray(value.templates)||!Number.isInteger(value.revision)||value.revision<0||!Number.isInteger(value.total)||value.total<0||!Number.isInteger(value.page)||!Number.isInteger(value.page_size))throw new Error('字典响应格式无效，请重试');
        return value;
      });
    },
    detail(entity:Entity,id:string,signal:AbortSignal) {
      return context.get<CatalogDetail>(`${base}/${entity}/${encodeURIComponent(id)}?observe_only=true`,{signal}).then(value=>{
        if(value.ok!==true||!value.item||value.item.id!==id||!Number.isInteger(value.revision)||!value.references||typeof value.references!=='object')throw new Error('字典详情身份或响应格式不一致');return value;
      });
    },
  };
}
