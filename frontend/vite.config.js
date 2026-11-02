import {defineConfig} from "vite";
const backend=process.env.FOODOO_API_TARGET||"http://127.0.0.1:8001";
export default defineConfig({
  server:{host:"0.0.0.0",proxy:{"/api":{target:backend,changeOrigin:true}}}
});
