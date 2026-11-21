export type ConfigurationGroup = '计算资源' | '模型与标注' | '模型交付与存储' | '基础字典';

export interface ConfigurationEntry {
  id: string;
  title: string;
  description: string;
  group: ConfigurationGroup;
  enabled: boolean;
  reason?: string;
}

export interface ConfigurationCenterContext {
  signal: AbortSignal;
  projectId: string;
  entries: ConfigurationEntry[];
  open(id: string): unknown;
  back(): unknown;
}
