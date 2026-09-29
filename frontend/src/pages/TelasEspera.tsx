import { useState } from 'react'
import { Anchor, Atom, Cloud, Shuffle, Sigma } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Pagina } from '../components/app/Pagina'
import Espera, { CENAS, ConteudoCena, NOMES } from '../components/app/Espera'
import type { Cena } from '../components/app/Espera'

const DETALHES: Record<Cena, { icone: LucideIcon; tipo: string; descricao: string }> = {
  barcos: { icone: Anchor, tipo: 'Jogo', descricao: 'Tabuada contra o relógio: acerte a conta de vezes e pule para o barco certo antes que o tubarão coma o seu.' },
  pendulo: { icone: Atom, tipo: 'Animação', descricao: 'Pêndulo triplo em movimento caótico.' },
  nuvens: { icone: Cloud, tipo: 'Jogo', descricao: 'Contas de soma, subtração, multiplicação e divisão para subir de nuvem em nuvem.' },
  galton: { icone: Sigma, tipo: 'Animação', descricao: 'Bolinhas caindo pelos pinos e formando a curva normal.' },
  caos: { icone: Shuffle, tipo: 'Animação', descricao: '240 pêndulos duplos quase idênticos que se separam com o tempo.' },
}

type Modo = 'cena' | 'completa'

export default function TelasEspera() {
  const [cena, setCena] = useState<Cena>(CENAS[0])
  const [modo, setModo] = useState<Modo>('cena')
  const detalhe = DETALHES[cena]
  const Icone = detalhe.icone

  return (
    <Pagina titulo="Telas de espera" subtitulo="Veja e teste as cenas que aparecem enquanto um pedido está sendo processado.">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1">
          {CENAS.map((c) => {
            const I = DETALHES[c].icone
            const ativo = c === cena
            return (
              <button
                key={c}
                onClick={() => setCena(c)}
                className="inline-flex items-center gap-2 h-10 px-3 rounded-md text-sm cursor-pointer transition-colors"
                style={{
                  backgroundColor: ativo ? 'var(--color-primary-bg)' : 'transparent',
                  color: ativo ? 'var(--color-primary-text)' : 'var(--color-text-secondary)',
                  fontWeight: ativo ? 600 : 500,
                }}
              >
                <I size={16} /> <span className="first-letter:uppercase">{NOMES[c]}</span>
              </button>
            )
          })}
        </div>
        <div className="ml-auto flex gap-1 rounded-md p-1" style={{ backgroundColor: 'var(--color-surface)', boxShadow: 'var(--shadow-card)' }}>
          {([['cena', 'Só a cena'], ['completa', 'Como o usuário vê']] as [Modo, string][]).map(([m, r]) => (
            <button
              key={m}
              onClick={() => setModo(m)}
              className="h-8 px-3 rounded text-sm cursor-pointer"
              style={{
                backgroundColor: modo === m ? 'var(--color-primary-bg)' : 'transparent',
                color: modo === m ? 'var(--color-primary-text)' : 'var(--color-text-secondary)',
                fontWeight: modo === m ? 600 : 500,
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {modo === 'cena' ? (
        <div className="flex flex-col gap-3 rounded-lg overflow-hidden" style={{ backgroundColor: 'var(--color-surface)', boxShadow: 'var(--shadow-card)' }}>
          <div className="flex flex-wrap items-center gap-2 px-5 pt-5">
            <Icone size={18} style={{ color: 'var(--color-primary-text)' }} />
            <h2 className="text-base font-semibold first-letter:uppercase">{NOMES[cena]}</h2>
            <span className="text-meta px-2 py-0.5 rounded-full" style={{ backgroundColor: detalhe.tipo === 'Jogo' ? 'var(--color-success-bg)' : 'var(--color-info-bg)', color: detalhe.tipo === 'Jogo' ? 'var(--color-success)' : 'var(--color-info)' }}>{detalhe.tipo}</span>
            <span className="text-sm basis-full md:basis-auto md:ml-2" style={{ color: 'var(--color-text-secondary)' }}>{detalhe.descricao}</span>
          </div>
          <ConteudoCena key={cena} cena={cena} />
        </div>
      ) : (
        <Espera key={cena} titulo="Criando o portal de demonstração" mensagem="Exemplo de mensagem de andamento: lendo os produtos do site do cliente." cenaInicial={cena} />
      )}
    </Pagina>
  )
}
