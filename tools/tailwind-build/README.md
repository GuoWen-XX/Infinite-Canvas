# Tailwind 预编译构建 (ic-tailwind-build)

将 Tailwind 从「397KB 浏览器运行时编译器」(`vendor/js/tailwindcss-cdn.js`，已弃用) 迁移为「26KB 静态预编译 CSS」(`static/vendor/css/tailwind.css`)。

## 何时需要重新构建

只要在前端代码（`static/**/*.html`、`static/js/**/*.js`）中**新增了此前从未使用过的 Tailwind 工具类**（如新的 `max-w-xl`、`md:flex` 等），就需要重新生成一次 CSS。只改动已有类的组合、增删 DOM 节点无需重建。

## 构建步骤

```bat
cd tools\tailwind-build
npm install      :: 首次
npm run build    :: 生成 static/vendor/css/tailwind.css
```

## 原理

- `tailwind.config.js` 的 `content` 扫描 `static/**/*.html` 与 `static/js/**/*.js` 的全部文本，提取所有 Tailwind 工具类（含 `hover:`/`md:` 等变体与 `text-[10px]` 等任意值）。
- 输出含 preflight（与旧 CDN 运行时行为一致，不会重置差异）。
- 已验证项目中不存在运行时拼接类名（`class="w-${x}"` / `'w-' + x` 均为 0），故静态扫描可 100% 覆盖。
- 项目自定义类（`ms-*`、`rh-*`、`mj-*`、`studio-*` 等）由内联 `<style>`、各 `css/*.css` 或 JS 注入样式表提供，不经过 Tailwind，不受本构建影响。
