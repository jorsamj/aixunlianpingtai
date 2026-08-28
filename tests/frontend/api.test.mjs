import test from 'node:test';
import assert from 'node:assert/strict';

import {messageFromApiError} from '../../static/modules/api.js';


test('api error includes detail and solution', () => {
  assert.equal(
    messageFromApiError({message: '标注保存失败', detail: '标签不存在', solution: '请创建标签'}),
    '标注保存失败：标签不存在\n建议：请创建标签'
  );
});

