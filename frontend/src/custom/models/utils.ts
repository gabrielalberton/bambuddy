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
  fragment.querySelectorAll('a').forEach((anchor) => {
    const href = safeExternalUrl(anchor.getAttribute('href') ?? '');
    if (!href) anchor.removeAttribute('href');
    else {
      anchor.setAttribute('href', href);
      anchor.setAttribute('target', '_blank');
      anchor.setAttribute('rel', 'noopener noreferrer');
    }
  });
  return fragment.innerHTML;
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
