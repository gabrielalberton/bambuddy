import { mm, SWEEP_VARIANTS, type SweepVariant } from './thickness';

const EXPLAIN: Record<SweepVariant, string> = {
  reference: 'Cinco linhas iguais: serve de referência para comparar com as próximas calibrações.',
  speeds: 'Seis linhas, alternando velocidade cheia e 40%: mostra se a velocidade muda onde o traço some.',
  reverse: 'As mesmas cinco linhas desenhadas de baixo para cima: separa o efeito da posição na folha do efeito da ordem em que a tinta é usada.',
};

/** Teste de altura: o que ele faz e a variação desejada. O botão que gera o plano fica em "Enviar". */
export function ZSweepTest({ contact, variant, onVariant }: {
  contact: number | null; variant: SweepVariant; onVariant: (next: SweepVariant) => void;
}) {
  const range = contact === null ? '2 mm abaixo a 2 mm acima do contato' : `Z ${mm(contact - 2)} a ${mm(contact + 2)} mm`;
  return <div className="plotter-tests">
    <p className="plotter-muted">
      Cada linha horizontal sobe de {range}, da esquerda para a direita: começa apertada e termina com o bico no ar.
      Só elas são o teste; as verticais, a régua e os números são marcação (cada número é o Z do bico naquele ponto).
      Veja em que número o traço começa a afinar e em que número ele some.
    </p>
    <label className="plotter-field"><span>Variação</span>
      <select aria-label="Variação do teste" value={variant} onChange={e => onVariant(e.target.value as SweepVariant)}>
        {SWEEP_VARIANTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
    <p className="plotter-muted">{EXPLAIN[variant]}</p>
  </div>;
}
