import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],base:'/app/',build:{outDir:'../static/vue-app',emptyOutDir:true,manifest:'manifest.json'}});
