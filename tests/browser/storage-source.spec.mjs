import {test, expect} from '@playwright/test';

async function openStoragePage(page) {
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => ({
    setPageReady: typeof window.setPage === 'function',
    uiReady: typeof state !== 'undefined' ? !!state.uiReady : false,
  })), {timeout: 20_000}).toEqual({setPageReady: true, uiReady: true});
  await page.evaluate(() => window.setPage('素材存储配置'));
  await expect(page.getByRole('heading', {name: '素材存储配置', level: 2})).toBeVisible({timeout: 10_000});
}



test('storage configuration creates, health-checks, and removes a real local source', async ({page}) => {
  const name = `浏览器本地源-${Date.now()}`;
  await openStoragePage(page);
  await expect(page.getByText('平台本地存储', {exact: true})).toBeVisible();

  await page.getByRole('button', {name: /新增存储源/}).click();
  await page.locator('#ss61Name').fill(name);
  await page.locator('#ss61Type').selectOption('local');
  await page.getByRole('button', {name: '保存'}).click();

  const row = page.locator('.storage61-row').filter({hasText: name});
  await expect(row).toBeVisible();
  await row.getByRole('button', {name: '测试连接'}).click();
  await expect(row.getByText('AVAILABLE')).toBeVisible();

  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('.storage61-row').filter({hasText: name})).toHaveCount(0);
});


test('object storage import exposes Agent flow and posts remote storage_scan contract', async ({page}) => {
  let submitted = null;

  await page.route('**/api/v61/storage-sources', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{
          id: 's3-ui',
          name: '生产素材库',
          type: 's3',
          enabled: true,
          is_default: false,
          health_status: 'AVAILABLE',
          health_message: 'available',
          config: {
            endpoint: 'https://s3.example.test',
            bucket: 'materials',
            prefix: '',
            use_ssl: true,
          },
        }],
      }),
    });
  });

  await page.route('**/api/v61/projects/*/storage-imports/scan', async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'remote-storage-scan-ui',
        project_id: 'browser-project',
        kind: 'MATERIAL_IMPORT',
        status: 'AWAITING_CONFIRMATION',
        progress: 48,
        stage: 'REMOTE_MATERIAL_REVIEWING',
        current_item: 'datasets/fire/2026/a.jpg',
        mode: 'storage_scan',
        execution_mode: 'agent',
        storage_source_id: 's3-ui',
        import_format: 'coco',
        prefix: 'datasets/fire/2026',
        recursive: true,
        metrics: {},
        result: {
          scanned_files: 1,
          importable_images: 1,
          duplicates: 0,
          failed: 0,
        },
      }),
    });
  });

  await openStoragePage(page);

  await page.getByRole('button', {name: '从存储导入素材'}).click();
  await expect(page.getByRole('button', {name: '对象存储目录'})).toHaveClass(/on/);
  await expect(page.locator('#si61RemoteSource')).toHaveValue('s3-ui');
  await expect(page.getByText('由远程素材节点执行')).toBeVisible();
  await expect(page.getByText(/中央端保管长期存储凭据/)).toBeVisible();

  await page.locator('#si61RemotePrefix').fill('datasets/fire/2026');
  await expect(page.locator('#si61Format')).toHaveValue('images');
  await expect(page.locator('#si61Format option[value="auto"]')).toBeDisabled();
  await expect(page.locator('#si61Format option[value="coco"]')).toBeEnabled();
  await expect(page.locator('#si61Format option[value="voc"]')).toBeEnabled();
  await page.locator('#si61Format').selectOption('coco');
  await expect(page.locator('#si61DatasetYaml')).toBeDisabled();
  await page.getByRole('button', {name: '开始远程扫描'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toEqual({
    mode: 'storage_scan',
    execution_mode: 'agent',
    import_format: 'coco',
    storage_source_id: 's3-ui',
    prefix: 'datasets/fire/2026',
    recursive: true,
  });
  await expect(page.locator('#si61Status')).toContainText('扫描完成，等待确认建立素材索引');
});


test('server ZIP switches target storage by execution location and submits COCO Agent contract', async ({page}) => {
  let submitted = null;
  await page.route('**/api/v61/storage-sources', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [
        {id:'local-ui',name:'平台本地',type:'local',enabled:true,is_default:false,config:{root:'/tmp/materials'}},
        {id:'s3-ui',name:'对象素材库',type:'s3',enabled:true,is_default:false,config:{endpoint:'https://s3.example.test',bucket:'materials',prefix:'',use_ssl:true}},
      ]}),
    });
  });
  await page.route('**/api/v61/projects/*/storage-imports/scan', async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id:'remote-coco-zip-ui',project_id:'browser-project',kind:'MATERIAL_IMPORT',
        status:'AWAITING_CONFIRMATION',execution_mode:'agent',mode:'server_zip',
        import_format:'coco',stage:'REMOTE_MATERIAL_REVIEWING',metrics:{},
        result:{scanned_files:1,importable_images:1,duplicates:0,failed:0},
      }),
    });
  });

  await openStoragePage(page);
  await page.getByRole('button', {name: '从存储导入素材'}).click();
  await page.getByRole('button', {name: '服务器 ZIP'}).click();

  await expect(page.locator('#si61ZipExecution')).toHaveValue('local');
  await expect(page.locator('#si61Format option[value="coco"]')).toBeDisabled();
  await expect(page.locator('#si61ZipLocalSourceWrap')).toBeVisible();

  await page.locator('#si61ZipExecution').selectOption('agent');
  await expect(page.locator('#si61ZipRemoteSourceWrap')).toBeVisible();
  await expect(page.locator('#si61ZipLocalSourceWrap')).toBeHidden();
  await expect(page.locator('#si61ZipRemoteSource')).toHaveValue('s3-ui');
  await expect(page.locator('#si61Format option[value="coco"]')).toBeEnabled();
  await page.locator('#si61Format').selectOption('coco');
  await page.locator('#si61ZipPath').fill('datasets/coco.zip');
  await page.locator('#si61TargetPrefix').fill('incoming/coco');
  await page.getByRole('button', {name: '开始 ZIP 导入'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toEqual({
    mode:'server_zip',execution_mode:'agent',import_format:'coco',
    storage_source_id:'s3-ui',zip_path:'datasets/coco.zip',
    target_prefix:'incoming/coco',recursive:true,
  });
  await expect(page.locator('#si61Status')).toContainText('扫描完成，等待确认建立素材索引');
});


test('storage rescan uses backend preflight and submits real Agent execution mode', async ({page}) => {
  let submitted = null;
  await page.route('**/api/v61/storage-sources', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 's3-rescan-ui',
        name: '长期素材库',
        type: 's3',
        enabled: true,
        is_default: false,
        health_status: 'AVAILABLE',
        config: {endpoint: 'https://s3.example.test', bucket: 'materials', prefix: '', use_ssl: true},
      }]}),
    });
  });
  await page.route('**/api/v61/projects/*/storage-sources/s3-rescan-ui/rescans/preflight', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        local_available: true,
        default_execution_mode: 'local',
        agent_available: true,
        reason: '',
        eligible_nodes: [{node_id: 'material-agent-01', display_name: '远程素材节点 01', build_id: 'build-1'}],
      }),
    });
  });
  await page.route('**/api/v61/projects/*/storage-sources/s3-rescan-ui/rescans', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'remote-rescan-ui',
        project_id: 'browser-project',
        status: 'QUEUED',
        stage: 'queued',
        execution_mode: 'agent',
        worker_id: '',
        resource_wait_reason: '',
        counts: {},
        examples: {},
        applied: 0,
      }),
    });
  });
  await page.route('**/api/v61/projects/*/storage-rescans/remote-rescan-ui', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'remote-rescan-ui',
        project_id: 'browser-project',
        status: 'AWAITING_CONFIRMATION',
        stage: 'REMOTE_MATERIAL_CONFIRMING_REVIEW',
        execution_mode: 'agent',
        worker_id: 'agent:material-agent-01',
        resource_wait_reason: '',
        current_item: '校验审查结果',
        counts: {NEW: 2, MISSING: 1, CHANGED: 3, UNCHANGED: 40, INVALID: 0, SKIPPED: 0},
        examples: {NEW: ['images/new-a.jpg'], CHANGED: ['images/changed-a.jpg']},
        applied: 0,
      }),
    });
  });

  await openStoragePage(page);
  const row = page.locator('.storage61-row').filter({hasText: '长期素材库'});
  await row.getByRole('button', {name: '重新扫描 / 恢复'}).click();

  await expect(page.locator('#sr61Execution')).toHaveValue('local');
  await expect(page.locator('#sr61AgentOption')).toBeEnabled();
  await expect(page.locator('#sr61AgentTruth')).toContainText('远程素材节点 01');

  await page.locator('#sr61Execution').selectOption('agent');
  await page.getByRole('button', {name: '开始新的扫描'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toEqual({execution_mode: 'agent'});
  await expect(page.locator('#sr61Status')).toContainText('待确认');
  await expect(page.locator('#sr61Status')).toContainText('远程 Agent');
  await expect(page.locator('#sr61Status')).toContainText('新增 2');
  await expect(page.locator('#sr61Status')).toContainText('缺失 1');
  await expect(page.locator('#sr61Status')).toContainText('内容变更 3');
  await expect(page.locator('#sr61Policy')).toBeVisible();
});


test('YOLO rescan keeps frontend request, review truth, mapping and conflict policy aligned', async ({page}) => {
  let submitted = null;
  let confirmation = null;
  await page.route('**/api/v61/storage-sources', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({items:[{
        id:'s3-yolo-rescan',name:'YOLO 长期素材库',type:'s3',enabled:true,
        health_status:'AVAILABLE',config:{endpoint:'https://s3.example.test',bucket:'materials',prefix:''},
      }]}),
    });
  });
  await page.route('**/api/v61/projects/*/storage-sources/s3-yolo-rescan/rescans/preflight', async route => {
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({
        local_available:true,default_execution_mode:'local',
        local_supported_formats:['images','yolo'],
        agent_available:true,agent_supported_formats:['images','yolo'],reason:'',
        eligible_nodes:[{node_id:'agent-yolo-01',display_name:'YOLO 节点 01'}],
      }),
    });
  });
  await page.route('**/api/v61/projects/*/storage-sources/s3-yolo-rescan/rescans', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submitted=route.request().postDataJSON();
    await route.fulfill({
      status:202,contentType:'application/json',
      body:JSON.stringify({
        task_id:'yolo-rescan-ui',project_id:'browser-project',status:'QUEUED',
        execution_mode:'agent',import_format:'yolo',dataset_yaml:'datasets/fire/data.yaml',
        counts:{},annotation_counts:{},examples:{},annotation_examples:{},
      }),
    });
  });
  await page.route('**/api/v61/projects/*/storage-rescans/yolo-rescan-ui/confirm', async route => {
    confirmation=route.request().postDataJSON();
    await route.fulfill({
      status:202,contentType:'application/json',
      body:JSON.stringify({
        task_id:'yolo-rescan-ui',project_id:'browser-project',status:'QUEUED',
        execution_mode:'agent',import_format:'yolo',dataset_yaml:'datasets/fire/data.yaml',
        counts:{NEW:1},annotation_counts:{ANNOTATION_CHANGED:2},examples:{},annotation_examples:{},
      }),
    });
  });
  let getCount=0;
  await page.route('**/api/v61/projects/*/storage-rescans/yolo-rescan-ui', async route => {
    getCount+=1;
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify(getCount===1?{
        task_id:'yolo-rescan-ui',project_id:'browser-project',status:'AWAITING_CONFIRMATION',
        execution_mode:'agent',import_format:'yolo',dataset_yaml:'datasets/fire/data.yaml',
        worker_id:'agent:agent-yolo-01',counts:{NEW:1,MISSING:0,CHANGED:0,UNCHANGED:8},
        annotation_counts:{ANNOTATION_NEW:1,ANNOTATION_CHANGED:2,ANNOTATION_REMOVED:1,ANNOTATION_CONFLICT:1,ANNOTATION_UNCHANGED:4,ANNOTATION_INVALID:0},
        examples:{NEW:['images/train/new.jpg']},
        annotation_examples:{ANNOTATION_CHANGED:['images/train/a.jpg'],ANNOTATION_CONFLICT:['images/train/manual.jpg']},
        quality:{boxes:3,issues:{}},
        external_classes:[{class_id:'0',name:'smoke',target_label_code:'smoke'}],
      }:{
        task_id:'yolo-rescan-ui',project_id:'browser-project',status:'SUCCEEDED',
        execution_mode:'agent',import_format:'yolo',counts:{NEW:1},annotation_counts:{ANNOTATION_CHANGED:2},
        examples:{},annotation_examples:{},
      }),
    });
  });

  await openStoragePage(page);
  const row=page.locator('.storage61-row').filter({hasText:'YOLO 长期素材库'});
  await row.getByRole('button',{name:'重新扫描 / 恢复'}).click();
  await page.locator('#sr61Execution').selectOption('agent');
  await page.locator('#sr61Format').selectOption('yolo');
  await page.locator('#sr61DatasetYaml').fill('datasets/fire/data.yaml');
  await page.getByRole('button',{name:'开始新的扫描'}).click();

  await expect.poll(()=>submitted).toEqual({
    execution_mode:'agent',import_format:'yolo',dataset_yaml:'datasets/fire/data.yaml',
  });
  await expect(page.locator('#sr61Status')).toContainText('标注变化 2');
  await expect(page.locator('#sr61Status')).toContainText('标注冲突 1');
  await expect(page.locator('#sr61Mapping')).toContainText('smoke');
  await expect(page.locator('[data-rescan-class="0"] [data-label-code]')).toHaveValue('smoke');
  await page.locator('#sr61AnnotationRemoved').check();
  await page.locator('#sr61AnnotationConflicts').check();
  await page.getByRole('button',{name:'确认应用'}).click();
  await expect.poll(()=>confirmation).not.toBeNull();
  expect(confirmation.annotation_changed).toBe('update');
  expect(confirmation.annotation_removed).toBe('clear');
  expect(confirmation.annotation_conflicts).toBe('overwrite');
  expect(confirmation.label_mapping).toEqual({'0':'smoke'});
});
