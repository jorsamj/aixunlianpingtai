import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],define:{'process.env.NODE_ENV':JSON.stringify('production')},base:'/static/vue-catalog/',build:{outDir:'../static/vue-catalog',emptyOutDir:true,
  lib:{entry:'src/main.ts',formats:['es'],fileName:()=> 'catalog-preview.js',cssFileName:'catalog-preview'},
  cssCodeSplit:false,rollupOptions:{output:{assetFileNames:'[name][extname]'}}}});
