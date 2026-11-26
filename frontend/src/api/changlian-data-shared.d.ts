declare module '*changlian-data-browser.js' {
  type Row = Record<string, unknown>;
  export function providerItems(value: unknown): Row[];
  export function providerDetail(value: unknown): {data?: Row|null};
  export function productIdentity(row: Row): string;
  export function versionIdentity(row: Row): string;
  export function weightIdentity(row: Row): string;
  export function weightRemoteLink(row: Row): string;
  export function remoteField(row: Row, key: string): string;
  export function tagsView(row: Row): {state:string;label:string;items:string[]};
}
