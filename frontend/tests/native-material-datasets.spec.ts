import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

test('native dataset membership moves an explicit selection and verifies an unread write once',async({page})=>{
  const membership=new Map([['p1','default'],['p2','default']]);
  const writes:{request_id:string;options:{dataset_id:string}}[]=[];
  const readbacks:string[]=[];
  const base='/api/v62/projects/p/material-batches';
  const revision='0'.repeat(64);
  const task=(target:string)=>({task_id:'membership-'+target,project_id:'p',operation:'MOVE_DATASET',
    target_dataset_id:target,total:2,processed:2,succeeded:2,failed:0,status:'SUCCEEDED'});
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
    if(path===base+'/estimate'){
      const {operation,selection_spec}=route.request().postDataJSON();
      expect(operation).toBe('MOVE_DATASET');
      expect(selection_spec).toEqual({scope:'SELECTED',image_ids:['p1','p2']});
      return route.fulfill({json:{supported:true,operation,count:2,dataset_revision:revision,
        selection_spec:{...selection_spec,repository_revision:1}}});
    }
    if(path===base){
      const packet=route.request().postDataJSON();
      const {dataset_id,dataset_revision}=packet.options;
      expect(dataset_revision).toBe(revision);
      expect(packet.selection_spec.repository_revision).toBe(1);
      writes.push(packet);
      for(const id of packet.selection_spec.image_ids)membership.set(id,dataset_id);
      if(dataset_id==='review')return route.abort('failed');
      return route.fulfill({json:task(dataset_id)});
    }
    if(path.startsWith(base+'/by-request/')){
      const id=path.split('/').at(-1)!;
      readbacks.push(id);
      expect(id).toBe(writes[0]?.request_id);
      return route.fulfill({json:task('review')});
    }
    if(path===base+'/membership-review/results'){
      return route.fulfill({json:{items:['p1','p2'].map(image_id=>({image_id,outcome:'updated'})),next_cursor:null}});
    }
    return route.fulfill({status:404,json:{detail:'unexpected route'}});
  });
  await page.goto('/app/#/projects/p/materials');
  await page.getByRole('button',{name:'选择本页'}).click();
  await page.screenshot({path:'../test-results/vue-catalog/native-materials-selected.png',animations:'disabled'});
  await page.getByRole('button',{name:'数据集目录'}).click();
  const dialog=page.getByRole('dialog',{name:'数据集目录'});
  await expect(dialog.getByRole('cell',{name:'质检素材'})).toBeVisible();
  const choose=async(name:string)=>{
    await dialog.getByRole('combobox',{name:'目标数据集'}).press('Enter');
    await page.getByRole('option',{name,exact:true}).click();
    await dialog.getByRole('button',{name:'预检范围'}).click();
    await expect(dialog.getByText('将处理 2 张素材。')).toBeVisible();
    await dialog.getByRole('button',{name:'确认执行'}).click();
  };
  await choose('质检素材');
  await dialog.getByRole('button',{name:'刷新任务'}).click();
  await expect(dialog.getByRole('status')).toContainText('完成 · 已处理 2 / 2 张');
  await dialog.getByRole('button',{name:'查看结果'}).click();
  await expect(dialog.getByRole('cell',{name:'已更新'})).toHaveCount(2);
  expect(writes.map(row=>row.options.dataset_id)).toEqual(['review']);
  expect(readbacks).toEqual([writes[0].request_id]);
  await dialog.getByRole('button',{name:'完成核对'}).click();
  await choose('默认数据集');
  await expect(dialog.getByRole('status')).toContainText('完成 · 已处理 2 / 2 张');
  expect(writes.map(row=>row.options.dataset_id)).toEqual(['review','default']);
});
