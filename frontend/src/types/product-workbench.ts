import type {BrowseContext} from './model-browse';

export interface ProductWorkbenchEntry {
  id:string;
  title:string;
  description:string;
}

export interface ProductWorkbenchContext extends BrowseContext {
  entries:ProductWorkbenchEntry[];
  open(id:string):unknown|Promise<unknown>;
  legacyWorkbench():unknown|Promise<unknown>;
}
