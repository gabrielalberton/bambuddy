import DOMPurify from 'dompurify';

export function safeExternalUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

/** Texto formatado sim; imagens remotas, estilos, embeds e scripts não (CSP + privacidade). */
export function sanitizeDescription(html: string): string {
  const fragment = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'ul', 'ol', 'li', 'h2', 'h3', 'h4', 'blockquote', 'pre', 'code', 'a', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
    ALLOWED_ATTR: ['href', 'title'],
    RETURN_DOM: true,
  }) as HTMLElement;
  linkifyText(fragment);
  fragment.querySelectorAll('a').forEach((anchor) => {
    const href = safeExternalUrl(anchor.getAttribute('href') ?? '');
    if (!href) anchor.removeAttribute('href');
    else {
      anchor.setAttribute('href', href);
      anchor.setAttribute('target', '_blank');
      anchor.setAttribute('rel', 'noopener noreferrer');
      const internal = makerworldModelId(href);
      if (internal) anchor.setAttribute('data-internal-model', internal);
    }
  });
  return fragment.innerHTML;
}

const URL_IN_TEXT = /https?:\/\/[^\s<>"')\]]+[^\s<>"')\].,;:!?]/g;

/** URLs soltas no texto viram <a> (fora de links existentes e de <code>/<pre>). */
function linkifyText(root: HTMLElement) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n as Text;
    if (text.parentElement?.closest('a, code, pre')) continue;
    URL_IN_TEXT.lastIndex = 0;
    if (URL_IN_TEXT.test(text.data)) nodes.push(text);
  }
  for (const text of nodes) {
    const parts = document.createDocumentFragment();
    let last = 0;
    URL_IN_TEXT.lastIndex = 0;
    for (let m = URL_IN_TEXT.exec(text.data); m; m = URL_IN_TEXT.exec(text.data)) {
      if (m.index > last) parts.append(text.data.slice(last, m.index));
      const a = document.createElement('a');
      a.setAttribute('href', m[0]);
      a.textContent = m[0];
      parts.append(a);
      last = m.index + m[0].length;
    }
    if (last < text.data.length) parts.append(text.data.slice(last));
    text.replaceWith(parts);
  }
}

/** ID do modelo quando o link aponta para outro modelo do MakerWorld (abre dentro do catálogo). */
export function makerworldModelId(href: string): string | null {
  try {
    const u = new URL(href);
    if (!/(^|\.)makerworld\.com(\.cn)?$/.test(u.hostname)) return null;
    const m = /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?models\/(\d+)/i.exec(u.pathname);
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

export const PRINTER_FILTER_KEY = 'custom.models.printerFilter';
export const AUTHOR_PRINTER_KEY = 'custom.models.printablesAuthorPrinter';

/** Preferência por navegador; padrão ligado (pedido do Gabriel). */
export function readBool(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    if (raw === '1') return true;
    if (raw === '0') return false;
  } catch {
    /* modo privado etc. */
  }
  return fallback;
}

export function writeBool(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch {
    /* só não lembra */
  }
}
