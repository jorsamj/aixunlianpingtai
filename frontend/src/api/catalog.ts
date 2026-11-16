import type {CatalogPage,CatalogDetail,Entity,Filters,PreviewContext} from '../types/catalog';
export function catalogApi(context:PreviewContext) {
  const base='/api/v39/deploy/catalog/records';
  return {
    list(entity:Entity,filters:Filters,vendor:string,signal:AbortSignal) {
      const query=new URLSearchParams({entity,...Object.fromEntries(Object.entries(filters).map(([k,v])=>[k,String(v)])),page_size:'10',observe_only:'true'});
      if(entity==='chips')query.set('vendor_id',vendor);
      return context.get<CatalogPage>(`${base}?${query}`,{signal}).then(value=>{
        if(value.ok!==true||!Array.isArray(value.items)||!Number.isInteger(value.total)||value.total<0||!Number.isInteger(value.page)||!Number.isInteger(value.page_size))throw new Error('字典响应格式无效，请重试');
        return value;
      });
    },
    detail(entity:Entity,id:string,signal:AbortSignal) {
      return context.get<CatalogDetail>(`${base}/${entity}/${encodeURIComponent(id)}?observe_only=true`,{signal}).then(value=>{
        if(value.ok!==true||!value.item||value.item.id!==id)throw new Error('字典详情身份不一致');return value;
      });
    },
  };
}
