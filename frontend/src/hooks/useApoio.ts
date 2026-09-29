import { useEffect, useState } from 'react'
import { consultar } from '../lib/mitra-api'
import type { Executivo } from '../lib/mitra-api'

export function useApoio() {
  const [executivos, setExecutivos] = useState<Executivo[]>([])
  const [segmentos, setSegmentos] = useState<string[]>([])
  const [erro, setErro] = useState<string | null>(null)
  useEffect(() => {
    let ativo = true
    Promise.allSettled([
      consultar<Executivo>('executivos_listar'),
      consultar<{ segmento: string }>('segmentos_listar'),
    ]).then(([e, s]) => {
      if (!ativo) return
      if (e.status === 'fulfilled') setExecutivos(e.value)
      else setErro('Não foi possível carregar os executivos.')
      if (s.status === 'fulfilled') setSegmentos(s.value.map((x) => x.segmento))
    })
    return () => { ativo = false }
  }, [])
  return { executivos, setExecutivos, segmentos, erro }
}
