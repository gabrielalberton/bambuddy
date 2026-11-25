import type { MountInfo, PenTypeInfo, Settings } from './api';
import { MOUNT_ABOUT, mountOf, selectMount } from './mounts';

export function MountPicker({ settings, mounts, penTypes, disabled, onChange }: {
  settings: Settings; mounts: MountInfo[]; penTypes?: PenTypeInfo[]; disabled?: boolean; onChange: (next: Settings) => void;
}) {
  const current = mountOf(settings.pens[settings.active_pen]);
  const about = MOUNT_ABOUT[current];
  return <div className="plotter-mount">
    <div className="plotter-segments" role="group" aria-label="Suporte da caneta">
      {mounts.map(mount => <button key={mount.key} type="button" aria-pressed={current === mount.key} disabled={disabled}
        onClick={() => onChange(selectMount(settings, mount, penTypes))}>{mount.name}</button>)}
    </div>
    <p className="plotter-muted">{about.summary} <strong>Para:</strong> {about.use}</p>
    <details>
      <summary>Com mola × sem mola</summary>
      <div className="plotter-mount-compare">
        {mounts.map(mount => <div key={mount.key}>
          <h4>{mount.name}</h4>
          <ul>{MOUNT_ABOUT[mount.key].good.map(text => <li key={text} className="good">{text}</li>)}</ul>
          <ul>{MOUNT_ABOUT[mount.key].bad.map(text => <li key={text} className="bad">{text}</li>)}</ul>
        </div>)}
      </div>
      <p className="plotter-muted">Cada modo guarda a própria altura de contato e curva de pressão: travar a caneta muda a
        altura da ponta e a mola deixa de participar. Ao trocar o suporte, recalibre o contato.</p>
    </details>
  </div>;
}
