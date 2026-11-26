import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

test('native dataset membership moves an explicit selection and verifies an unread write once',async({page})=>{
  const membership=new Map([['p1','default'],['p2','default']]);
  const writes:string[]=[];
  const readbacks:string[]=[];
  const row=(id:string)=>({id,filename:id+'.png',dataset_id:membership.get(id)});
  await page.route('**/app/**',route=>{
    const path=new URL(route.request().url()).pathname.slice(5)||'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'tester'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目甲'}]});
    if(path==='/api/v61/projects/p/materials'){
      return route.fulfill({json:{ok:true,project_id:'p',page:1,page_size:48,total:2,total_pages:1,has_next:false,items:[row('p1'),row('p2')]}});
    }
    if(path==='/api/projects/p/datasets'){
      expect(url.searchParams.get('directory_only')).toBe('true');
      return route.fulfill({json:{ok:true,project_id:'p',items:[{id:'default',name:'默认数据集'},{id:'review',name:'质检素材'}]}});
    }
    if(path.startsWith('/api/v12/projects/p/images/')){
      expect(route.request().method()).toBe('PATCH');
      const id=path.split('/').at(-1)!;
      const {dataset_id}=route.request().postDataJSON();
      expect(membership.has(id)).toBeTruthy();
      expect(['review','default']).toContain(dataset_id);
      writes.push(id+':'+dataset_id);
      membership.set(id,dataset_id);
      if(id==='p2'&&dataset_id==='review')return route.abort('failed');
      return route.fulfill({json:{ok:true}});
    }
    if(path.startsWith('/api/projects/p/annotations/')){
      const id=path.split('/').at(-1)!;
      expect(route.request().method()).toBe('GET');
      expect(url.searchParams.get('reader_view')).toBe('true');
      readbacks.push(id);
      return route.fulfill({json:{ok:true,project_id:'p',image:row(id),annotation:{boxes:[]}}});
    }
    return route.fulfill({status:404,json:{detail:'unexpected route'}});
  });
  await page.goto('/app/#/projects/p/materials');
  await page.getByRole('button',{name:'选择本页'}).click();
  await page.getByRole('button',{name:'数据集目录'}).click();
  const dialog=page.getByRole('dialog',{name:'数据集目录'});
  await expect(dialog.getByRole('cell',{name:'质检素材'})).toBeVisible();
  const choose=async(name:string)=>{
    await dialog.getByRole('combobox',{name:'目标数据集'}).click();
    await page.getByRole('option',{name,exact:true}).click();
    await dialog.getByRole('button',{name:'确认批量调整归属'}).click();
  };
  await choose('质检素材');
  await dialog.getByText('归属处理结果',{exact:false}).click();
  await expect(dialog.getByRole('cell',{name:'已核验目标归属'})).toBeVisible();
  expect(writes).toEqual(['p1:review','p2:review']);
  expect(readbacks).toEqual(['p2']);
  await choose('默认数据集');
  await expect(dialog.getByRole('status')).toHaveText('已将 2 张素材的归属更新为 默认数据集。');
  expect(writes).toEqual(['p1:review','p2:review','p1:default','p2:default']);
});
