import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

test('native material library keeps scoped browsing, selection and original workflow links',async({page})=>{
  await page.setViewportSize({width:1920,height:1080});
  const queries:URL[]=[];
  const names=new Map<string,string>();
  let renameRequests=0;
  const sha='a'.repeat(64);
  const written:Record<string,unknown>[]=[];
  const originalBox={id:'existing',class_id:1,label:'person',x1:2,y1:2,x2:6,y2:6,source:'manual'};
  let formal={version:3,annotation_state:'annotated',annotation_scope:['person'],boxes:[originalBox]};
  let releaseSlow!:()=>void,notifySlow!:()=>void;
  const slowGate=new Promise<void>(done=>{releaseSlow=done});
  const slowStarted=new Promise<void>(done=>{notifySlow=done});
  await page.route('**/app/**',route=>{
    const path=new URL(route.request().url()).pathname.slice(5)||'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'tester'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目甲'},{id:'q',name:'项目乙'}]});
    const project=path.includes('/projects/q/')?'q':'p';
    const row=(id:string)=>({id,filename:names.get(id)||id+'.png',width:32,height:32,annotation_state:'annotated',box_count:1,content_sha256:sha,quality_status:'processed',
      storage_source_id:'local',content_url:'/api/v61/projects/'+project+'/materials/'+id+'/content',
      thumbnail_url:'/api/v61/projects/'+project+'/materials/'+id+'/content/thumbnail',
      annotation_preview:[{label:'smoke',x1:1,y1:1,x2:7,y2:7}]});
    if(path==='/api/v47/projects/p/images/p1'&&route.request().method()==='PUT'){
      renameRequests++;
      expect(route.request().postDataJSON()).toEqual({name:'现场照片.png'});
      names.set('p1','现场照片.png');
      // The write may have committed even when the client misses the response.
      return route.abort('failed');
    }
    if(path.endsWith('/materials')){
      queries.push(url);
      const itemPage=Number(url.searchParams.get('page'));
      expect(url.searchParams.get('reader_view')).toBe('true');
      expect(url.searchParams.get('page_size')).toBe('48');
      const term=url.searchParams.get('query');
      if(term==='慢查询'){notifySlow();await slowGate;}
      const id=term==='慢查询'?'stale':term==='新查询'?'fresh':project+itemPage;
      return route.fulfill({json:{ok:true,project_id:project,page:itemPage,page_size:48,total:96,total_pages:2,has_next:itemPage===1,items:[row(id)]}}).catch(()=>{});
    }
    if(path.endsWith('/labels'))return route.fulfill({json:{items:[{code:'smoke',class_id:0},{code:'person',class_id:1}]}});
    if(path.includes('/annotations/')){
      const id=path.split('/').at(-1)!;
      if(route.request().method()==='POST'){
        expect(id).toBe('p2');
        const body=route.request().postDataJSON();
        written.push(body);
        expect(body.expected_version).toBe(3);
        expect(body.source_content_sha256).toBe(sha);
        expect(body.annotation_state).toBe('annotated');
        expect(body.reviewed_label_codes).toEqual([]);
        expect(body.boxes[0]).toEqual(originalBox);
        formal={...formal,version:4,boxes:body.boxes.map((box:typeof originalBox)=>({...box,source:box.source||'manual'}))};
        return route.abort('failed');
      }
      if(!url.searchParams.has('reader_view'))return route.fulfill({json:{ok:true,image:row(id),
        annotation:id==='p2'?formal:{version:0,boxes:[],annotation_state:'unannotated',annotation_scope:[]}}});
      expect(url.searchParams.get('reader_view')).toBe('true');
      return route.fulfill({json:{ok:true,project_id:id==='foreign'?'q':project,image:row(id),annotation:{boxes:row(id).annotation_preview,annotation_state:'annotated'},boxes_total:1}});
    }
    if(url.searchParams.has('expected_sha256')){
      expect(url.searchParams.get('expected_sha256')).toBe(sha);
      return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="gray"/></svg>'});
    }
    if(path.endsWith('/history'))return route.fulfill({json:{page:1,page_size:20,total:1,items:[{task_id:'frozen-task',role:'test'}]}});
    if(path.includes('/content'))return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+nmZcAAAAASUVORK5CYII=','base64')});
    return route.fulfill({status:404,json:{detail:'unexpected request'}});
  });
  await page.goto('/app/#/projects/p/materials?label=smoke&annotation_state=annotated&quality_status=processed&source_batch_id=zip-1');
  await expect(page.getByRole('heading',{name:'素材库',exact:true})).toBeVisible();
  const image=page.getByRole('img',{name:'p1.png',exact:true});
  await expect(image).toHaveAttribute('loading','lazy');
  for(const [key,value] of Object.entries({label:'smoke',annotation_state:'annotated',quality_status:'processed',source_batch_id:'zip-1'}))
    expect(queries[0].searchParams.get(key)).toBe(value);
  await expect(page.locator('.material-card').getByRole('button',{name:'人工标注',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'改名',exact:true}).click();
  await page.getByRole('textbox',{name:'新素材名称'}).fill('现场照片.png');
  await page.getByRole('button',{name:'保存名称'}).click();
  await expect(page.getByText('未收到改名回执，请核对当前名称。')).toBeVisible();
  await page.getByRole('button',{name:'核对名称',exact:true}).click();
  await expect(page.getByRole('img',{name:'现场照片.png',exact:true})).toBeVisible();
  expect(renameRequests).toBe(1);
  expect(queries).toHaveLength(1);
  await page.getByRole('button',{name:'选择本页'}).click();
  await page.getByRole('button',{name:'下一页',exact:true}).click();
  await expect(page.getByRole('img',{name:'p2.png',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'选择本页'}).click();
  await page.getByRole('button',{name:'列表',exact:true}).click();
  await expect(page.locator('.material-results')).toHaveClass(/list/);
  await page.getByRole('button',{name:'详情',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'素材详情'});
  await expect(drawer.getByRole('heading',{name:'p2.png'})).toBeVisible();
  await expect(drawer.getByRole('img',{name:'p2.png'})).toHaveAttribute('src','/api/v61/projects/p/materials/p2/content');
  await expect(drawer.locator('svg rect')).toHaveCount(1);
  await drawer.getByRole('button',{name:'读取历史使用记录'}).click();
  await expect(drawer.getByText('frozen-task')).toBeVisible();
  await page.reload();
  await expect(drawer.getByRole('heading',{name:'p2.png'})).toBeVisible();
  await expect(page.getByText('已选 2 张',{exact:false}).first()).toBeVisible();
  await drawer.getByRole('button',{name:'人工标注',exact:true}).click();
  await expect(page).toHaveURL(/materials\/annotate.*image=p2/);
  const editor=page.getByRole('region',{name:'正式人工标注编辑'});
  const draw=editor.getByRole('button',{name:'画框',exact:true});
  await expect(draw).toBeEnabled();
  await expect(editor.locator('.a9s-annotation')).toHaveCount(1);
  await editor.getByLabel('显示类别').selectOption('smoke');
  await expect(editor.locator('.a9s-annotation')).toHaveCount(0);
  await draw.click();
  const frame=await editor.locator('.editor-world img').boundingBox();
  if(!frame)throw new Error('原图未渲染');
  const x=(value:number)=>frame.x+frame.width*value/32;
  const y=(value:number)=>frame.y+frame.height*value/32;
  await page.mouse.move(x(10),y(10));await page.mouse.down();await page.mouse.move(x(20),y(20),{steps:8});await page.mouse.up();
  await expect(editor.locator('.a9s-annotation')).toHaveCount(1);
  await editor.getByRole('button',{name:'保存标注',exact:true}).click();
  await expect(editor.getByRole('button',{name:'核对保存结果'})).toBeVisible();
  await editor.getByRole('button',{name:'核对保存结果'}).click();
  await expect(editor.getByText('已核对当前正式标注')).toBeVisible();
  expect(written).toHaveLength(1);
  expect(formal.boxes).toHaveLength(2);
  expect(formal.boxes[1].x1).toBeCloseTo(10,0);
  expect(formal.boxes[1].y2).toBeCloseTo(20,0);
  await page.getByRole('button',{name:'上一张',exact:true}).click();
  await expect(editor.getByRole('heading',{name:'现场照片.png'})).toBeVisible();
  await expect(editor.locator('.a9s-annotation')).toHaveCount(0);
  await editor.getByRole('button',{name:'返回素材库',exact:true}).click();
  await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);
  await expect(drawer.getByRole('heading',{name:'p2.png'})).toBeVisible();
  await drawer.getByRole('button',{name:'返回素材库'}).click();
  const search=page.getByRole('textbox',{name:'素材名称'});
  await search.fill('慢查询');
  await page.getByRole('button',{name:'查询素材'}).click();
  await slowStarted;
  await search.fill('新查询');
  await page.getByRole('button',{name:'查询素材'}).click();
  await expect(page.getByRole('img',{name:'fresh.png',exact:true})).toBeVisible();
  releaseSlow();
  await expect(page.getByRole('img',{name:'stale.png',exact:true})).toHaveCount(0);
  await expect(page.getByText('已选 2 张',{exact:false}).first()).toBeVisible();
  await page.getByText(/已选素材摘要/).click();
  await page.getByRole('button',{name:'移除',exact:true}).first().click();
  await expect(page.getByText('已选 1 张',{exact:false}).first()).toBeVisible();
  await page.locator('.session-tools .el-select__wrapper').click();
  await page.getByRole('option',{name:'项目乙',exact:true}).click();
  await expect(page).toHaveURL(/projects\/q\/materials/);
  await expect(page.getByRole('img',{name:'q1.png',exact:true})).toBeVisible();
  await expect(page.getByText('已选 0 张',{exact:false})).toBeVisible();
  await page.goto('/app/#/projects/p/materials?detail=foreign');
  await expect(drawer.getByText('素材响应项目身份不一致')).toBeVisible();
});
