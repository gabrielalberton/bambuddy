import { Link } from 'react-router-dom';
import { makerworldModelId } from '../models/utils';

/**
 * "Origem: MakerWorld" no detalhe do arquivo: abre o modelo dentro do catálogo do Bambuddy
 * (/model-sources, aba catálogo), não no site externo. URL que não é de modelo do MakerWorld continua externa.
 */
export function catalogPathForMakerworld(url: string): string | null {
  const id = makerworldModelId(url);
  return id ? `/model-sources?tab=catalog&model=${id}&msrc=makerworld` : null;
}

export function MakerworldSourceLink({ url, onNavigate }: { url: string; onNavigate?: () => void }) {
  const internal = catalogPathForMakerworld(url);
  const cls = 'text-bambu-green hover:underline';
  if (!internal) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" className={cls}>
        MakerWorld
      </a>
    );
  }
  return (
    <Link to={internal} onClick={onNavigate} className={cls} data-testid="custom-mw-source-link">
      MakerWorld
    </Link>
  );
}
