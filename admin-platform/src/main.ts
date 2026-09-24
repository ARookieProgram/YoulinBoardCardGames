/**
 * 前端入口。
 *
 * 技术栈：Vue 3（`<script setup>` + TS）+ Element Plus + Pinia + Vue Router。
 *
 * Element Plus 采用**全量引入**：登录页与后台用到的组件遍布各处，
 * 全量引入省掉了按需引入的插件与 `components.d.ts` 维护成本；
 * 这是内部管理系统，首屏体积不在关键路径上。
 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIcons from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
import '@/assets/main.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 中文语言包：分页、日期、确认框的默认文案都会跟着变中文。
app.use(ElementPlus, { locale: zhCn })

// 全局注册图标。图标的"名字"来自路由表的 `meta.icon`，侧边栏用
// `<component :is="item.icon" />` 按名字渲染，所以必须是全局组件。
for (const [name, component] of Object.entries(ElementPlusIcons)) {
  app.component(name, component)
}

app.mount('#app')
