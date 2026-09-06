/**
 * @module widgetMarkdown
 * @description Widget Markdown 处理模块，提供 markdown-it 的 adp-widget 插件和 HTML 编解码工具函数
 */

import type MarkdownIt from 'markdown-it';

/** Widget 渲染选项 */
export interface WidgetRenderOptions {
  /** 语言环境 */
  locale: string;
  /** Widget ID（后备值） */
  widgetId?: string;
  /** Widget Run ID（后备值） */
  widgetRunId?: string;
  /** 消息 Record ID */
  recordId?: string;
}

/**
 * 将字符串转换为 HTML 实体编码，用于安全地放入 HTML 属性中
 */
export function escapeHtmlAttr(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * 将 HTML 属性编码还原为原始字符串
 */
export function unescapeHtmlAttr(str: string): string {
  return str
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

/**
 * 格式化 JSON 字符串，带语法高亮（用于 fallback 展示）
 */
export function formatJsonWithHighlight(jsonStr: string): string {
  try {
    const obj = JSON.parse(jsonStr);
    const formatted = JSON.stringify(obj, null, 2);
    return formatted
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
      .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
      .replace(/: (\d+)/g, ': <span class="json-number">$1</span>')
      .replace(/: (true|false)/g, ': <span class="json-boolean">$1</span>')
      .replace(/: (null)/g, ': <span class="json-null">$1</span>');
  } catch {
    return jsonStr;
  }
}

/**
 * 简单字符串哈希函数，用于生成稳定的 elementId
 */
function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0; // Convert to 32bit integer
  }
  return Math.abs(hash).toString(36);
}

/**
 * widget-json 内容存储：elementId → widgetJson 字符串。
 *
 * 安全设计：widget-json 不通过 HTML 属性传递（避免 DOMPurify 清洗超长属性、
 * 避免用户伪造 wrapper 绕过 sanitize）。fence 渲染时把 widgetJson 存入此 Map，
 * 生成的 <adp-widget> 只带 data-widget-key（data- 属性 DOMPurify 保留），
 * useWidgetInit 在 DOM 升级时按 key 从 Map 取 widgetJson，用 JS 设置 widget-json 属性。
 * 用户伪造的 wrapper 没有 Map 条目 → 取不到 → 不渲染，杜绝 XSS。
 */
const widgetJsonStore = new Map<string, string>();

/** 读取指定 key 的 widgetJson（只读不删，支持 v-html 重渲染时重新取值设置） */
export function peekWidgetJson(key: string): string | undefined {
  return widgetJsonStore.get(key);
}

/**
 * 自定义 markdown-it 插件：处理 adp-widget 代码块
 * 将 ```adp-widget 代码块渲染为 <adp-widget> 组件
 */
export function createMarkdownItWidgetPlugin(options: WidgetRenderOptions) {
  return function markdownItWidgetPlugin(md: MarkdownIt): void {
    const defaultFence = md.renderer.rules.fence!;

    md.renderer.rules.fence = (tokens, idx, opts, env, self) => {
      const token = tokens[idx];
      if (!token) {
        return '';
      }
      const info = token.info.trim();

      // 检测 adp-widget 代码块
      if (info === 'adp-widget' || info.startsWith('adp-widget ')) {
        const widgetJson = token.content.trim();

        // 尝试从 widget JSON 中解析 _adp_widget_meta 获取真正的 widgetId 和 widgetRunId
        let parsedWidgetId = '';
        let parsedWidgetRunId = '';
        try {
          const widgetObj = JSON.parse(widgetJson);
          if (widgetObj._adp_widget_meta) {
            parsedWidgetId = widgetObj._adp_widget_meta.widgetId || '';
            parsedWidgetRunId = widgetObj._adp_widget_meta.widgetRunId || '';
          }
        } catch {
          // 解析失败，使用空值
        }

        const actualWidgetId = parsedWidgetId || options.widgetId || '';
        const actualWidgetRunId = parsedWidgetRunId || options.widgetRunId || '';

        // 生成稳定的 DOM ID（基于内容哈希 + 索引，不使用 Date.now()）
        // 这样 computed 重新计算时生成相同的 HTML，减少不必要的 DOM 重建
        const elementId = `widget-${simpleHash(widgetJson)}-${idx}`;

        // widgetJson 存入模块级 Map，由 useWidgetInit 消费（不放入 HTML 属性）。
        // 同一 elementId 覆盖旧值（computed 重算时内容相同 → key 相同 → 无副作用）。
        widgetJsonStore.set(elementId, widgetJson);

        // 生成的 HTML 中：data-widget-key 关联 Map；widgetId/runId/recordId 用 escapeHtmlAttr 转义防属性注入。
        // widget-json 属性不在这里设置（由 useWidgetInit JS 设置），避免 DOMPurify 清洗超长值。
        return `<div class="adp-widget-wrapper" data-widget-id="${escapeHtmlAttr(actualWidgetId)}" data-widget-run-id="${escapeHtmlAttr(actualWidgetRunId)}" data-record-id="${escapeHtmlAttr(options.recordId || '')}" data-element-id="${escapeHtmlAttr(elementId)}">
        <adp-widget 
          id="${escapeHtmlAttr(elementId)}"
          data-widget-key="${escapeHtmlAttr(elementId)}"
          locale="${escapeHtmlAttr(options.locale)}"
        ></adp-widget>
      </div>`;
      }

      // 其他代码块使用默认渲染
      return defaultFence(tokens, idx, opts, env, self);
    };
  };
}

/**
 * 在 widget 加载失败时显示 JSON 回退视图
 * @param {NodeListOf<Element>} wrappers - widget wrapper DOM 节点列表
 */
export function showFallbackJson(wrappers: NodeListOf<Element>): void {
  wrappers.forEach((wrapper) => {
    const widgetEl = wrapper.querySelector('adp-widget');
    if (!widgetEl) return;

    const encodedJson = widgetEl.getAttribute('widget-json') || '';
    const originalJson = unescapeHtmlAttr(encodedJson);

    const fallbackEl = document.createElement('div');
    fallbackEl.className = 'adp-widget-fallback';
    fallbackEl.innerHTML = `
      <div class="fallback-header">
        <span class="fallback-icon">⚠️</span>
        <span class="fallback-title">Widget 加载失败</span>
      </div>
      <div class="fallback-content">
        <pre class="fallback-json"><code>${formatJsonWithHighlight(originalJson)}</code></pre>
      </div>
    `;

    wrapper.innerHTML = '';
    wrapper.appendChild(fallbackEl);
  });
}
