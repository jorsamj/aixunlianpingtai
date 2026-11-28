import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',workers:1,timeout:30000,outputDir:'../test-results/vue-catalog',
  use:{baseURL:'http://127.0.0.1:8027',channel:'chrome',screenshot:'only-on-failure',trace:'retain-on-failure'},
  webServer:{command:'python -m http.server 8027 --bind 127.0.0.1 --directory ..',url:'http://127.0.0.1:8027/static/index.html',reuseExistingServer:false}});
