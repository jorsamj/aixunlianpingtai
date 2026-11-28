import {providerDetail, providerItems, weightIdentity} from '../../../static/modules/changlian-data-browser.js';
import {request} from '../app/http';

export const changLianProvider = '/api/v63/external-algorithm-platform/provider';
type Row = Record<string, unknown>;
export type WeightSelection = {
  productId: string;
  versionId: string;
  weightId: string;
  listWeight: Row;
};

export const weightDetailGroups = [
  {name: '模型基本信息', fields: [
    ['weightId', '权重文件 ID'], ['productId', '算法产品 ID'], ['analysisId', '分析方式 ID'],
    ['algoVersionId', '算法版本 ID'], ['versionName', '版本名称'], ['versionNo', '版本号'],
    ['fileName', '文件名称'], ['yoloVersion', 'YOLO 版本'], ['imageWidth', '输入宽度'], ['imageHeight', '输入高度'],
  ]},
  {name: '算力环境', fields: [
    ['computePlatformId', '算力环境 ID'], ['computePlatformName', '算力环境名称'],
    ['computePlatformCode', '算力环境编号'], ['chipCode', '芯片标识'],
  ]},
  {name: '文件属性', fields: [['filePath', '文件地址'], ['fileSize', '文件大小'], ['fileSha256', 'SHA256']]},
  {name: '创建与更新', fields: [
    ['createBy', '创建人'], ['createTime', '创建时间'], ['updateBy', '更新人'],
    ['updateTime', '更新时间'], ['delFlag', '删除标志'],
  ]},
  {name: '备注', fields: [['remark', '备注']]},
] as const;

const comparisonFields = [
  ['fileName', '文件名称'], ['filePath', '文件地址'], ['computePlatformId', '算力环境 ID'],
  ['chipCode', '芯片标识'], ['tags', '标签'],
] as const;
const owns = (row: Row, key: string) => Object.prototype.hasOwnProperty.call(row, key);

export function isProviderId(id: string) {
  return /^[1-9][0-9]{0,18}$/.test(id) && BigInt(id) <= 9223372036854775807n;
}

function exactId(value: unknown, expected: string) {
  return typeof value === 'string' ? value === expected :
    typeof value === 'number' && Number.isSafeInteger(value) && String(value) === expected;
}

function verifyIdentity(row: Row, {productId, versionId, weightId}: WeightSelection) {
  // Product/version may be omitted by the provider. Every returned alias must match.
  const scopes = [
    [['weightId', 'algorithmWeightId', 'id'], weightId],
    [['productId', 'product_id'], productId],
    [['algoVersionId', 'algorithmVersionId', 'versionId'], versionId],
  ] as const;
  if (weightIdentity(row) !== weightId || scopes.some(([keys, expected]) =>
    keys.some(key => owns(row, key) && !exactId(row[key], expected)))) {
    throw new Error('权重详情与所选产品、版本或文件身份不一致，请刷新列表核对。');
  }
}

function differences(list: Row, detail: Row, tags: Row) {
  return comparisonFields.flatMap(([key, name]) => {
    const current = key === 'tags' ? tags : detail;
    if (!owns(list, key) || !owns(current, key)) return [];
    const format = key === 'tags' ? JSON.stringify : String;
    const previous = format(list[key]), actual = format(current[key]);
    return previous === actual ? [] : [`${name}：列表 ${previous}，详情 ${actual}`];
  });
}

async function readPagedTags(selection: WeightSelection, pages: unknown[], signal: AbortSignal) {
  const seen = new Set<string>();
  const pageSize = 50;
  for (let page = 1; page <= 1000; page++) {
    const query = new URLSearchParams({
      pageNum: String(page), pageSize: String(pageSize), algoVersionId: selection.versionId, withTags: 'true',
    });
    const response = providerDetail(await request(`${changLianProvider}/weights/page?${query}`, {signal}));
    pages.push(response);
    const rows = providerItems(response);
    const matches = rows.filter(row => weightIdentity(row) === selection.weightId);
    if (matches.length > 1) throw new Error('分页返回重复权重 ID，无法唯一确认标签。');
    const match = matches[0];
    if (match) {
      verifyIdentity(match, selection);
      return match;
    }
    const total = response.total ?? response.data?.total;
    const totalText = total === undefined ? undefined : String(total);
    if (totalText !== undefined && (!/^\d+$/.test(totalText) ||
      (typeof total === 'number' && !Number.isSafeInteger(total)))) {
      throw new Error('分页总数异常。');
    }
    const count = totalText === undefined ? undefined : BigInt(totalText);
    if (!rows.length) {
      if (count !== undefined && count > BigInt((page - 1) * pageSize)) {
        throw new Error('分页提前返回空页，尚未读取完整结果。');
      }
      return null;
    }
    const fingerprint = JSON.stringify(rows);
    if (seen.has(fingerprint)) throw new Error('分页重复返回相同结果，已停止查询。');
    seen.add(fingerprint);
    if (count === undefined ? rows.length < pageSize : BigInt(page * pageSize) >= count) return null;
  }
  throw new Error('分页超过读取上限，未确认完整结果。');
}

export async function readWeightDetail(selection: WeightSelection, signal: AbortSignal) {
  const raw = providerDetail(await request(
    `${changLianProvider}/weights/${encodeURIComponent(selection.weightId)}?withTags=true`, {signal},
  ));
  const data = raw.data;
  if (data === null) return null;
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('远端详情 data 不是有效对象。');
  verifyIdentity(data, selection);

  const pages: unknown[] = [];
  let tags = data;
  let source = 'getInfo';
  let tagsError = '';
  if (!owns(data, 'tags')) {
    source = 'list · withTags=true';
    try {
      const match = await readPagedTags(selection, pages, signal);
      tags = match ?? {};
      if (!match) source += '（未找到该权重）';
    } catch (error) {
      if (signal.aborted) throw error;
      tagsError = error instanceof Error ? error.message : String(error);
    }
  }
  return {data, tags, source, tagsError, differences: differences(selection.listWeight, data, tags),
    evidence: {getInfo: raw, tagsQuery: pages}};
}
