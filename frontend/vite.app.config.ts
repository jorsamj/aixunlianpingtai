import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
import {readFileSync} from 'node:fs';

const hashLicense = new URL('./node_modules/@noble/hashes/LICENSE', import.meta.url);

export default defineConfig({
  plugins:[vue()],base:'/app/',
  build:{outDir:'../static/vue-app',emptyOutDir:true,manifest:'manifest.json',
    rollupOptions:{
      external:id=>id.startsWith('/static/vendor/uppy/'),
      output:{banner:chunk=>chunk.moduleIds.some(id=>id.includes('/node_modules/@noble/hashes/'))
        ? `/*!\n${readFileSync(hashLicense,'utf8')}\n*/` : ''},
    },
    commonjsOptions:{include:[/node_modules/,/vendor[\\/]echarts[\\/]echarts\.min\.js$/]}},
});
