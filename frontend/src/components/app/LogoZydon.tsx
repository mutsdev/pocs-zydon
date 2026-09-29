export const POLIGONOS_Z = [
  '50.56 2.48 41.81 19.99 6.79 19.99 6.79 2.48',
  '76.83 19.99 76.83 37.5 33.05 37.5 41.81 19.99',
  '33.05 37.5 24.3 55.01 6.79 55.01 6.79 37.5',
  '76.83 55.01 76.83 72.52 15.55 72.52 24.3 55.01',
]

export default function LogoZydon({ tamanho = 28, cor = 'var(--color-primary)' }: { tamanho?: number; cor?: string }) {
  return (
    <svg width={tamanho} height={tamanho * 75 / 83.61} viewBox="0 0 83.61 75" aria-hidden="true">
      {POLIGONOS_Z.map((p) => <polygon key={p} points={p} fill={cor} />)}
    </svg>
  )
}
